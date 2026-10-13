#!/usr/bin/env python3
"""
Incremental track update script for CaliperAI.

Updates 3D annotations in existing scenes with tracking IDs (track_id)
from tracked KITTI bundles without re-uploading large bundles or recomputing
CLIP image embeddings.
"""

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def run_psql_query(sql: str) -> str:
    """Run a query via docker exec anno-postgres and return stripped stdout."""
    cmd = [
        "docker", "exec", "-i", "anno-postgres",
        "psql", "-U", "postgres", "-d", "annotation_platform",
        "-t", "-A", "-c", sql
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"psql query failed: {res.stderr.strip()}\nSQL: {sql}")
    return res.stdout.strip()


def get_scene_info(scene_name: str) -> Optional[dict]:
    """Retrieve scene, task, taxonomy and directory info from database."""
    sql = f"""
    SELECT 
        s.id::text, 
        s.dataset_id::text, 
        t.id::text, 
        t.taxonomy_id::text,
        (SELECT f.file_paths->'_meta'->>'absolute_path' FROM frames f WHERE f.scene_id = s.id AND f.frame_index = 0 LIMIT 1),
        (SELECT count(*) FROM frame_image_embeddings fie JOIN frames f ON f.id = fie.frame_id WHERE f.scene_id = s.id)
    FROM scenes s
    JOIN tasks t ON t.scene_id = s.id
    WHERE s.name = '{scene_name}' AND s.is_deleted = false
    ORDER BY t.created_at ASC
    LIMIT 1;
    """
    out = run_psql_query(sql)
    if not out:
        return None
    parts = out.split("|")
    if len(parts) < 6:
        return None

    scene_id, dataset_id, task_id, taxonomy_id, abs_path, embedding_count = parts
    
    # Extract directory uuid from path like /uploads/<dataset_id>/<dir_uuid>/lidar/...
    dir_uuid = None
    if abs_path:
        path_parts = Path(abs_path).parts
        for i, part in enumerate(path_parts):
            if part == dataset_id and i + 1 < len(path_parts):
                dir_uuid = path_parts[i + 1]
                break

    return {
        "scene_id": scene_id,
        "dataset_id": dataset_id,
        "task_id": task_id,
        "taxonomy_id": taxonomy_id,
        "dir_uuid": dir_uuid,
        "embedding_count": int(embedding_count or 0),
    }


def get_frame_index_mapping(scene_id: str) -> Dict[int, str]:
    """Return mapping of frame_index -> frame_id (UUID string)."""
    sql = f"""
    SELECT frame_index, id::text 
    FROM frames 
    WHERE scene_id = '{scene_id}' 
    ORDER BY frame_index;
    """
    out = run_psql_query(sql)
    mapping = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        idx_str, fid = line.split("|")
        mapping[int(idx_str)] = fid
    return mapping


def parse_tracked_kitti_line(line: str) -> Optional[dict]:
    """Parse a single line of KITTI tracking format.
    
    Expected format (17 or 18 columns):
    frame_index track_id class_name truncated occluded alpha bbox[4] h w l x y z yaw [score]
    """
    parts = line.strip().split()
    if len(parts) < 17:
        return None

    try:
        frame_index = int(parts[0])
        track_id = int(parts[1])
        class_name = parts[2].lower()
        if class_name in ("dontcare", "dont_care"):
            return None

        truncated = float(parts[3])
        occluded = int(parts[4])
        alpha = float(parts[5])

        # 3D bounding box dimensions and location
        height = float(parts[10])
        width = float(parts[11])
        length = float(parts[12])
        x = float(parts[13])
        y = float(parts[14])
        z = float(parts[15])
        yaw = float(parts[16])
        score = float(parts[17]) if len(parts) > 17 else 1.0

        return {
            "frame_index": frame_index,
            "track_id": track_id,
            "class_name": class_name,
            "attributes": {"truncated": truncated, "occluded": occluded, "alpha": alpha, "score": score},
            "dimensions": {"length": length, "width": width, "height": height},
            "center": {"x": x, "y": y, "z": z},
            "rotation": {"yaw": yaw, "pitch": 0.0, "roll": 0.0},
        }
    except (ValueError, IndexError):
        return None


def update_scene_with_tracks(
    scene_name: str,
    zip_path: Path,
    dry_run: bool = False,
    sync_disk: bool = True
) -> dict:
    """Execute incremental track update for a single scene."""
    print(f"\n==================================================")
    print(f"[*] Processing scene: {scene_name}")
    print(f"[*] Tracked bundle:  {zip_path}")
    if not zip_path.is_file():
        raise FileNotFoundError(f"Bundle file not found: {zip_path}")

    scene_info = get_scene_info(scene_name)
    if not scene_info:
        raise ValueError(f"Scene '{scene_name}' not found in database!")

    scene_id = scene_info["scene_id"]
    task_id = scene_info["task_id"]
    taxonomy_id = scene_info["taxonomy_id"]
    dir_uuid = scene_info["dir_uuid"]
    dataset_id = scene_info["dataset_id"]
    orig_embeddings = scene_info["embedding_count"]

    print(f"[*] Scene ID:        {scene_id}")
    print(f"[*] Task ID:         {task_id}")
    print(f"[*] Directory UUID:  {dir_uuid}")
    print(f"[*] Active CLIP Embeddings: {orig_embeddings} (must be preserved!)")

    frame_map = get_frame_index_mapping(scene_id)
    print(f"[*] Found {len(frame_map)} frames registered in database.")

    # Read all txt files from zip
    annotations_data = []
    unique_tracks = set()
    class_counter = Counter()

    temp_extract_dir = None
    if sync_disk:
        temp_extract_dir = tempfile.mkdtemp(prefix="caliper_track_txt_")

    with zipfile.ZipFile(zip_path, "r") as zf:
        txt_names = sorted([
            n for n in zf.namelist() 
            if n.endswith(".txt") and "annotations/lidar/" in n and not n.startswith("__MACOSX")
        ])
        print(f"[*] Found {len(txt_names)} label files in ZIP.")

        for name in txt_names:
            content = zf.read(name).decode("utf-8")
            if sync_disk and temp_extract_dir:
                dest_file = Path(temp_extract_dir) / Path(name).name
                dest_file.write_text(content, encoding="utf-8")

            for line in content.splitlines():
                parsed = parse_tracked_kitti_line(line)
                if not parsed:
                    continue

                f_idx = parsed["frame_index"]
                frame_uuid = frame_map.get(f_idx)
                if not frame_uuid:
                    continue

                track_int = parsed["track_id"]
                unique_tracks.add(track_int)
                class_counter[parsed["class_name"]] += 1

                # Deterministic UUID for each track in this scene
                track_uuid = str(uuid.uuid5(uuid.UUID(scene_id), f"track-{track_int}"))

                ann_id = str(uuid.uuid4())
                cuboid_data = {
                    "center": parsed["center"],
                    "dimensions": parsed["dimensions"],
                    "rotation": parsed["rotation"],
                }

                annotations_data.append((
                    ann_id,
                    task_id,
                    frame_uuid,
                    track_uuid,
                    "cuboid",
                    parsed["class_name"],
                    json.dumps(cuboid_data),
                    json.dumps(parsed["attributes"]),
                    "auto",
                    "false",  # is_migrated_to_fusion
                    "false",  # is_verified
                    "false",  # is_keyframe
                    "false",  # is_static
                    taxonomy_id if taxonomy_id else "",
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ))

    print(f"[*] Parsed {len(annotations_data)} annotations across {len(unique_tracks)} unique tracks.")
    print(f"[*] Class breakdown: {dict(class_counter)}")

    if dry_run:
        print("[*] DRY RUN mode enabled. No changes applied.")
        if temp_extract_dir:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
        return {
            "annotations_count": len(annotations_data),
            "tracks_count": len(unique_tracks),
            "dry_run": True,
        }

    # Step 1: Replace database annotations in a single atomic transaction
    print("[*] Writing updated annotations to PostgreSQL via temporary CSV...")
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f_csv:
        tmp_csv_host = Path(f_csv.name)
        writer = csv.writer(f_csv, lineterminator="\n")
        for row in annotations_data:
            writer.writerow(row)

    container_csv = f"/tmp/annos_{task_id}.csv"
    try:
        # Copy CSV into postgres container and allow postgres user to read it
        subprocess.run(["docker", "cp", str(tmp_csv_host), f"anno-postgres:{container_csv}"], check=True)
        subprocess.run(["docker", "exec", "anno-postgres", "chmod", "666", container_csv], check=True)

        sql_script = f"""
        BEGIN;
        DELETE FROM annotations_3d WHERE task_id = '{task_id}';
        COPY annotations_3d (id, task_id, frame_id, track_id, type, class_id, data, attributes, source, is_migrated_to_fusion, is_verified, is_keyframe, is_static, taxonomy_id, created_at, updated_at) 
        FROM '{container_csv}' WITH (FORMAT csv, HEADER false);
        COMMIT;
        """
        copy_cmd = [
            "docker", "exec", "-i", "anno-postgres",
            "psql", "-U", "postgres", "-d", "annotation_platform",
            "-v", "ON_ERROR_STOP=1", "-c", sql_script
        ]
        proc = subprocess.run(copy_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Database update failed: {proc.stderr}\nStdout: {proc.stdout}")
    finally:
        subprocess.run(["docker", "exec", "anno-postgres", "rm", "-f", container_csv], check=False)
        tmp_csv_host.unlink(missing_ok=True)

    print("[*] Database atomic update successfully committed!")

    # Step 2: Sync files to container disk if requested
    if sync_disk and dir_uuid and temp_extract_dir:
        dest_container_path = f"/uploads/{dataset_id}/{dir_uuid}/annotations/lidar"
        print(f"[*] Syncing updated label files to container: {dest_container_path} ...")
        # Ensure directory exists in container
        subprocess.run([
            "docker", "exec", "-u", "root", "anno-backend",
            "mkdir", "-p", dest_container_path
        ], check=True)

        # Copy using docker cp
        cp_proc = subprocess.run([
            "docker", "cp", f"{temp_extract_dir}/.", f"anno-backend:{dest_container_path}/"
        ], capture_output=True, text=True)
        if cp_proc.returncode != 0:
            print(f"[!] Warning: docker cp failed: {cp_proc.stderr}")
        else:
            # Fix file ownership
            subprocess.run([
                "docker", "exec", "-u", "root", "anno-backend",
                "chown", "-R", "appuser:appuser", dest_container_path
            ], check=False)
            print("[*] Disk label files synced and permission fixed.")

        shutil.rmtree(temp_extract_dir, ignore_errors=True)

    # Step 3: Verify and validate database state
    verify_sql = f"""
    SELECT 
        count(a.id) as total_annos,
        count(a.track_id) as annos_with_track_id,
        count(DISTINCT a.track_id) as distinct_tracks,
        (SELECT count(*) FROM frame_image_embeddings fie JOIN frames f ON f.id = fie.frame_id WHERE f.scene_id = '{scene_id}') as remaining_embeddings
    FROM annotations_3d a
    WHERE a.task_id = '{task_id}';
    """
    verify_out = run_psql_query(verify_sql)
    tot, with_tid, dist_tid, rem_emb = verify_out.split("|")
    print(f"[+] Verification completed for {scene_name}:")
    print(f"    - Total 3D Annotations:     {tot}")
    print(f"    - Annotations with Track ID: {with_tid}")
    print(f"    - Distinct Tracks:          {dist_tid}")
    print(f"    - CLIP Image Embeddings:    {rem_emb} (Preserved: {int(rem_emb) == orig_embeddings})")

    return {
        "scene_name": scene_name,
        "total_annotations": int(tot),
        "with_track_id": int(with_tid),
        "distinct_tracks": int(dist_tid),
        "preserved_embeddings": int(rem_emb),
    }


EXISTING_SCENES = [
    {
        "name": "data_20260910_061820_transfusion_sweep5",
        "zip": Path("/home/nvidia/数据闭环实践/transfusion_caliper/output/bundles/data_20260910_061820_transfusion_sweep5_tracked_6cam.zip"),
    },
    {
        "name": "data_20260910_062659_transfusion_sweep5",
        "zip": Path("/home/nvidia/数据闭环实践/transfusion_caliper/output/bundles/data_20260910_062659_transfusion_sweep5_tracked_6cam.zip"),
    },
    {
        "name": "data_20260910_063822_transfusion_sweep5",
        "zip": Path("/home/nvidia/数据闭环实践/transfusion_caliper/output/bundles/data_20260910_063822_transfusion_sweep5_tracked_6cam.zip"),
    },
]


def main():
    parser = argparse.ArgumentParser(description="Incremental track update script for CaliperAI")
    parser.add_argument("--scene-name", help="Specific scene name to update")
    parser.add_argument("--zip", type=Path, help="Path to tracked zip bundle")
    parser.add_argument("--all", action="store_true", help="Update all 3 existing scenes sequentially")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without modifying database or disk")
    args = parser.parse_args()

    if args.all:
        print("[*] Running incremental update for all 3 existing scenes sequentially...")
        results = []
        for item in EXISTING_SCENES:
            res = update_scene_with_tracks(item["name"], item["zip"], dry_run=args.dry_run)
            results.append(res)
        print("\n==================================================")
        print("[✓] ALL 3 SCENES SUCCESSFULLY UPDATED!")
        for r in results:
            print(f" - {r.get('scene_name')}: {r.get('with_track_id')} annotations with {r.get('distinct_tracks')} tracks, embeddings={r.get('preserved_embeddings')}")
        return

    if args.scene_name:
        zip_path = args.zip
        if not zip_path:
            # Try to match from EXISTING_SCENES
            for item in EXISTING_SCENES:
                if item["name"] == args.scene_name:
                    zip_path = item["zip"]
                    break
        if not zip_path:
            print(f"Error: --zip must be specified for scene {args.scene_name}", file=sys.stderr)
            sys.exit(1)
        update_scene_with_tracks(args.scene_name, zip_path, dry_run=args.dry_run)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
