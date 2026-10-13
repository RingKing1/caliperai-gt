"""Semantic scene search over frame image embeddings (Chinese-CLIP).

Pipeline: query text -> CLIP text vector (anno-clip GPU service) ->
pgvector HNSW nearest frames -> per-scene aggregation (mean of the scene's
top-K frame similarities) so results rank whole scenes rather than frames.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.clip_client_service import clip_client

# Canonical tag stored in frame_image_embeddings.model; keep in sync with
# the backfill script and the vector(512) column.
EMBEDDING_MODEL_TAG = "cn_clip_vit_b_16"


async def embedding_coverage(db: AsyncSession) -> List[Dict[str, Any]]:
    """Per-scene embedding counts for the configured model."""
    rows = await db.execute(
        text(
            """
            SELECT s.id AS scene_id, s.name AS scene_name,
                   count(e.id) AS embedded_frames,
                   count(DISTINCT e.camera) AS cameras
            FROM scenes s
            LEFT JOIN frames f ON f.scene_id = s.id
            LEFT JOIN frame_image_embeddings e
              ON e.frame_id = f.id AND e.model = :model
            WHERE s.is_deleted = FALSE
            GROUP BY s.id, s.name
            ORDER BY s.name
            """
        ),
        {"model": EMBEDDING_MODEL_TAG},
    )
    return [dict(row) for row in rows.mappings()]


async def search_scenes_semantic(
    db: AsyncSession,
    query_text: str,
    dataset_id: Optional[UUID] = None,
    cameras: Optional[List[str]] = None,
    min_similarity: float = 0.18,
    top_k_frames: Optional[int] = None,
    candidate_pool: Optional[int] = None,
    preview_frames: int = 5,
    limit: int = 50,
) -> Dict[str, Any]:
    """Rank scenes by how well their best-matching frames fit the query."""
    top_k_frames = top_k_frames or settings.CLIP_SCENE_TOP_K_FRAMES
    vectors = await clip_client.embed_texts([query_text])
    query_vector = vectors[0]
    vector_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"

    where_extra = ""
    params: Dict[str, Any] = {"model": EMBEDDING_MODEL_TAG, "qvec": vector_literal}
    pool_sql = " LIMIT :pool" if candidate_pool else ""
    if candidate_pool:
        params["pool"] = candidate_pool
    params["top_k"] = top_k_frames
    if dataset_id is not None:
        where_extra += " AND s.dataset_id = :dataset_id"
        params["dataset_id"] = dataset_id
    if cameras:
        where_extra += " AND nn.camera = ANY(:cameras)"
        params["cameras"] = cameras

    # 1) HNSW-accelerated nearest-neighbour frame pool (cosine distance).
    # 2) Per-scene mean of top-K frame similarities = scene score.
    sql = text(
        f"""
        WITH ranked AS (
            SELECT
                s.id AS scene_id,
                s.name AS scene_name,
                s.dataset_id AS dataset_id,
                s.frame_count AS frame_count,
                f.frame_index AS frame_index,
                nn.camera AS camera,
                nn.sim AS similarity,
                row_number() OVER (
                    PARTITION BY s.id ORDER BY nn.sim DESC
                ) AS rn
            FROM (
                SELECT e.frame_id, e.camera,
                       1 - (e.embedding <=> CAST(:qvec AS vector)) AS sim
                FROM frame_image_embeddings e
                WHERE e.model = :model
                ORDER BY e.embedding <=> CAST(:qvec AS vector)
                {pool_sql}
            ) nn
            JOIN frames f ON f.id = nn.frame_id
            JOIN scenes s ON s.id = f.scene_id
            WHERE s.is_deleted = FALSE{where_extra}
        )
        SELECT
            scene_id,
            scene_name,
            dataset_id,
            frame_count,
            avg(similarity) AS score,
            max(similarity) AS max_similarity,
            count(*) AS matched_frames
        FROM ranked
        WHERE rn <= :top_k AND similarity >= :min_sim
        GROUP BY scene_id, scene_name, dataset_id, frame_count
        HAVING avg(similarity) >= :min_sim
        ORDER BY score DESC, max_similarity DESC
        LIMIT :limit
        """
    )
    params["min_sim"] = min_similarity
    params["limit"] = limit
    # HNSW index scans return at most hnsw.ef_search (default 40) candidates
    # regardless of LIMIT. Widen it; for very large pools force an exact
    # sequential scan so every stored frame participates in ranking.
    if candidate_pool is None or candidate_pool >= 1000:
        # Accurate ranking over all (or most) embeddings.
        await db.execute(text("SET LOCAL enable_indexscan = OFF"))
    else:
        # SET does not accept bind parameters; candidate_pool is an integer
        # constrained by the API layer, so inlining is safe here.
        await db.execute(text(f"SET LOCAL hnsw.ef_search = {int(candidate_pool)}"))
    result = await db.execute(sql, params)
    scenes = [dict(row) for row in result.mappings()]

    if not scenes:
        return {
            "query": query_text,
            "model": EMBEDDING_MODEL_TAG,
            "cameras": cameras or [],
            "min_similarity": min_similarity,
            "total": 0,
            "results": [],
        }

    # Top preview frames per matched scene (for UI thumbnails).
    scene_ids = [row["scene_id"] for row in scenes]
    preview_sql = text(
        """
        SELECT scene_id, frame_index, camera, similarity FROM (
            SELECT s.id AS scene_id, f.frame_index AS frame_index,
                   e.camera AS camera,
                   1 - (e.embedding <=> CAST(:qvec AS vector)) AS similarity,
                   row_number() OVER (
                       PARTITION BY s.id
                       ORDER BY e.embedding <=> CAST(:qvec AS vector)
                   ) AS rn
            FROM frame_image_embeddings e
            JOIN frames f ON f.id = e.frame_id
            JOIN scenes s ON s.id = f.scene_id
            WHERE s.id = ANY(:scene_ids) AND e.model = :model
        ) ranked_preview
        WHERE rn <= :preview_per_scene
        ORDER BY scene_id, similarity DESC
        """
    )
    await db.execute(text("SET LOCAL hnsw.ef_search = 1000"))
    previews = await db.execute(
        preview_sql,
        {
            "qvec": vector_literal,
            "scene_ids": scene_ids,
            "model": EMBEDDING_MODEL_TAG,
            "preview_per_scene": preview_frames,
        },
    )
    preview_by_scene: Dict[UUID, List[Dict[str, Any]]] = {}
    for row in previews.mappings():
        bucket = preview_by_scene.setdefault(row["scene_id"], [])
        if len(bucket) < preview_frames:
            bucket.append(
                {
                    "frame_index": row["frame_index"],
                    "camera": row["camera"],
                    "similarity": round(float(row["similarity"]), 4),
                }
            )

    results = []
    for row in scenes:
        scene_id = row["scene_id"]
        results.append(
            {
                "scene_id": scene_id,
                "scene_name": row["scene_name"],
                "dataset_id": row["dataset_id"],
                "frame_count": row["frame_count"],
                "score": round(float(row["score"]), 4),
                "max_similarity": round(float(row["max_similarity"]), 4),
                "matched_frames": row["matched_frames"],
                "preview_frames": preview_by_scene.get(scene_id, []),
            }
        )

    return {
        "query": query_text,
        "model": EMBEDDING_MODEL_TAG,
        "cameras": cameras or [],
        "min_similarity": min_similarity,
        "total": len(results),
        "results": results,
    }
