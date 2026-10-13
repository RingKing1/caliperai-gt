"""
Backfill Chinese-CLIP frame image embeddings for semantic scene search.

Runs inside the backend container (has DB + /uploads access) and calls the
anno-clip GPU microservice over HTTP. Resumable: frames already embedded for
the given model are skipped.

Examples:
  # all scenes, front camera only, every 5th frame (quick validation)
  python scripts/backfill_frame_embeddings.py --cameras front --stride 5 --limit 200

  # full backfill, all six cameras
  python scripts/backfill_frame_embeddings.py --cameras all
"""
import argparse
import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text

from app.core.database import async_session_factory
from app.services.scene_semantic_search_service import EMBEDDING_MODEL_TAG

CLIP_URL = os.getenv("CLIP_API_URL", "http://clip:8002").rstrip("/")
BATCH_SIZE = 32


def _resolve_image_path(
    file_paths: Dict[str, Any], camera: str, raw_key: str, filename: str
) -> Optional[str]:
    meta = file_paths.get("_meta") or {}
    lidar_dir = os.path.dirname(meta.get("absolute_path", ""))
    if not lidar_dir:
        return None
    scene_dir = os.path.dirname(lidar_dir)
    # Imported bundles use either canonical directories (front) or the raw
    # camera key from the bundle (camera_0_front100), depending on upload era.
    candidates = [
        os.path.join(scene_dir, "cameras", camera, filename),
        os.path.join(scene_dir, "cameras", raw_key, filename),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


async def wait_for_clip() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(60):
            try:
                response = await client.get(f"{CLIP_URL}/health")
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") == "healthy":
                    return payload
            except Exception:
                pass
            await asyncio.sleep(5)
    raise RuntimeError(f"CLIP service not healthy at {CLIP_URL}")


async def embed_batch(image_paths: List[str]) -> List[List[float]]:
    files = []
    opened = []
    try:
        for index, path in enumerate(image_paths):
            handle = open(path, "rb")
            opened.append(handle)
            files.append(("images", (f"img_{index}.jpg", handle, "image/jpeg")))
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{CLIP_URL}/embed/images", files=files)
            response.raise_for_status()
            return response.json()["vectors"]
    finally:
        for handle in opened:
            handle.close()


async def fetch_pending_frames(
    cameras: List[str], stride: int, scene: Optional[str], limit: Optional[int]
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"model": EMBEDDING_MODEL_TAG, "stride": stride}

    # Conditions on tables inside the subquery
    inner_clauses = [
        "s.is_deleted = FALSE",
        "mod(f.frame_index, :stride) = 0",
    ]
    if scene:
        inner_clauses.append("s.name ILIKE :scene")
        params["scene"] = f"%{scene}%"
    inner_where = " AND ".join(inner_clauses)

    limit_sql = " LIMIT :limit" if limit else ""
    if limit:
        params["limit"] = limit

    # Imported bundles keep raw camera keys like "camera_0_front100";
    # normalize them to canonical names (front, left_front, ...) which also
    # match the on-disk directories .../cameras/<canonical>/<file>.
    sql = text(
        f"""
        SELECT work.* FROM (
            SELECT f.id AS frame_id, f.frame_index AS frame_index,
                   s.name AS scene_name,
                   norm.raw_key AS raw_key,
                   regexp_replace(
                       regexp_replace(norm.raw_key, '^camera_[0-9]+_', ''),
                       '[0-9]+$', ''
                   ) AS camera,
                   norm.filename AS filename,
                   f.file_paths AS file_paths
            FROM frames f
            JOIN scenes s ON s.id = f.scene_id
            CROSS JOIN LATERAL jsonb_each_text(f.file_paths->'cameras')
                AS norm(raw_key, filename)
            WHERE {inner_where}
        ) work
        LEFT JOIN frame_image_embeddings e
          ON e.frame_id = work.frame_id
         AND e.camera = work.camera
         AND e.model = :model
        WHERE e.id IS NULL AND work.camera = ANY(:camera_list)
        ORDER BY work.scene_name, work.frame_index, work.camera
        {limit_sql}
        """
    )
    params["camera_list"] = cameras
    async with async_session_factory() as db:
        result = await db.execute(sql, params)
        return [dict(row) for row in result.mappings()]


async def insert_embeddings(rows: List[Dict[str, Any]]) -> None:
    async with async_session_factory() as db:
        for row in rows:
            vector_literal = "[" + ",".join(f"{v:.8f}" for v in row["vector"]) + "]"
            await db.execute(
                text(
                    """
                    INSERT INTO frame_image_embeddings (frame_id, camera, model, embedding)
                    VALUES (:frame_id, :camera, :model, CAST(:vec AS vector(512)))
                    ON CONFLICT (frame_id, camera, model) DO NOTHING
                    """
                ),
                {
                    "frame_id": row["frame_id"],
                    "camera": row["camera"],
                    "model": EMBEDDING_MODEL_TAG,
                    "vec": vector_literal,
                },
            )
        await db.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cameras", default="front", help="comma list or 'all'")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--scene", default=None, help="scene name ILIKE filter")
    parser.add_argument("--limit", type=int, default=None, help="max (frame,camera) rows")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    if args.cameras.strip().lower() == "all":
        cameras = ["front", "left_front", "right_front", "back", "left_back", "right_back"]
    else:
        cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]

    info = await wait_for_clip()
    print(f"CLIP ready: {info}")
    pending = await fetch_pending_frames(cameras, args.stride, args.scene, args.limit)
    print(f"Pending (frame, camera) rows: {len(pending)}  cameras={cameras} stride={args.stride}")
    if not pending:
        return

    # Resolve paths and drop missing files
    work = []
    missing = 0
    for row in pending:
        path = _resolve_image_path(row["file_paths"], row["camera"], row["raw_key"], row["filename"])
        if path and os.path.exists(path):
            row["image_path"] = path
            work.append(row)
        else:
            missing += 1
    if missing:
        print(f"WARNING: {missing} image files missing on disk, skipped")

    done = 0
    started = time.time()
    for start in range(0, len(work), args.batch_size):
        batch = work[start : start + args.batch_size]
        vectors = await embed_batch([row["image_path"] for row in batch])
        if len(vectors) != len(batch):
            raise RuntimeError(
                f"CLIP returned {len(vectors)} vectors for {len(batch)} images"
            )
        for row, vector in zip(batch, vectors):
            row["vector"] = vector
        await insert_embeddings(batch)
        done += len(batch)
        elapsed = time.time() - started
        rate = done / elapsed if elapsed else 0.0
        print(
            f"  {done}/{len(work)} embedded  ({rate:.1f} img/s, "
            f"{elapsed:.0f}s elapsed)",
            flush=True,
        )
    print(f"DONE: {done} embeddings written, model={EMBEDDING_MODEL_TAG}")


if __name__ == "__main__":
    asyncio.run(main())
