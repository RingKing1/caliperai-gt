"""Per-scene annotation import: parse on-disk labels into 2D/3D/4D rows."""
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation2D,
    Annotation3D,
    Frame,
    Scene,
    Task,
    Taxonomy,
    Track2D,
    dataset_taxonomy_association,
)

from app.services.dataset_import.constants import SEGMENTATION_ROOT
from app.services.dataset_import.naming import match_folder_to_task
from app.services.dataset_import.taxonomy import (
    _read_segmentation_class_order,
    build_class_mapping,
    ensure_segmentation_taxonomy,
    map_class_to_taxonomy,
)

logger = logging.getLogger(__name__)

async def import_scene_annotations(
    db: AsyncSession,
    scene: Scene,
    scene_dir: Path,
    task: Task,
    overwrite: bool = False,
) -> tuple[int, int]:
    """Import annotations from a scene directory if they exist.
    
    Looks for:
    - annotations/lidar/*.txt (KITTI format 3D annotations)
    - label_2/*.txt (standard KITTI folder naming)
    - annotations/*.json (COCO format 2D annotations)
    - annotations/tasks/*/*.json (v3 per-task scene export layout)
    
    Also checks parent directory for annotations folder (for structures like scene/data/ and scene/annotations/)
    
    Performs taxonomy sync: maps imported class labels to existing taxonomy classes
    using case-insensitive matching and common naming variations.
    
    Args:
        db: Database session
        scene: Scene to import annotations for
        scene_dir: Path to scene directory
        task: Task to associate annotations with
        overwrite: If True, delete existing annotations for this task before importing
    
    Returns:
        Tuple of (annotations_3d_count, annotations_2d_count)
    """
    from sqlalchemy import delete
    
    logger.debug(f"[DEBUG] import_scene_annotations called for scene {scene.name} at {scene_dir}")
    
    if overwrite:
        deleted_3d = await db.execute(delete(Annotation3D).where(Annotation3D.task_id == task.id))
        deleted_2d = await db.execute(delete(Annotation2D).where(Annotation2D.task_id == task.id))
        await db.execute(delete(Track2D).where(Track2D.task_id == task.id))
        logger.info(f"[IMPORT] Overwrite mode: Deleted {deleted_3d.rowcount} 3D and {deleted_2d.rowcount} 2D existing annotations")
    
    annotations_dir = scene_dir / "annotations"
    logger.debug(f"[DEBUG] Checking annotations_dir: {annotations_dir}, exists: {annotations_dir.exists()}")
    
    if not annotations_dir.exists():
        parent_annotations_dir = scene_dir.parent / "annotations"
        logger.debug(f"[DEBUG] Checking parent annotations_dir: {parent_annotations_dir}, exists: {parent_annotations_dir.exists()}")
        if parent_annotations_dir.exists():
            annotations_dir = parent_annotations_dir
    
    if not annotations_dir.exists():
        logger.debug(f"[DEBUG] No annotations directory found, returning 0,0")

        return 0, 0
    
    class_mapping = {}
    class_info_by_id: Dict[str, Dict[str, Any]] = {}
    if scene.dataset_id:
        taxonomy_result = await db.execute(
            select(Taxonomy)
            .join(dataset_taxonomy_association)
            .where(dataset_taxonomy_association.c.dataset_id == scene.dataset_id)
            .where(Taxonomy.is_deleted == False)
        )
        taxonomies = taxonomy_result.scalars().all()

        for taxonomy in taxonomies:
            if taxonomy.classes:
                mapping = build_class_mapping(taxonomy.classes)
                class_mapping.update(mapping)
                for cls in taxonomy.classes:
                    cid = cls.get("id")
                    if cid:
                        class_info_by_id[cid] = {"name": cls.get("name") or cid, "color": cls.get("color")}
                logger.debug(f"[DEBUG] Loaded {len(taxonomy.classes)} classes from taxonomy '{taxonomy.name}'")
    
    if class_mapping:
        logger.debug(f"[DEBUG] Built class mapping with {len(class_mapping)} entries")
    else:
        logger.debug(f"[DEBUG] No taxonomy found for dataset, using raw class labels")
    
    annotations_3d_count = 0
    annotations_2d_count = 0

    imported_tracks_2d: Dict[uuid.UUID, Dict[str, Any]] = {}
    track_meta_overrides: Dict[uuid.UUID, Dict[str, Any]] = {}

    default_camera_id = "default"
    frames_result = await db.execute(
        select(Frame).where(Frame.scene_id == scene.id).order_by(Frame.frame_index)
    )
    frames = list(frames_result.scalars().all())
    frame_by_index = {f.frame_index: f for f in frames}
    if frames:
        first_paths = frames[0].file_paths or {}
        cameras = first_paths.get("cameras") or {}
        if cameras:
            default_camera_id = next(iter(cameras.keys()))

    task_taxonomy_result = await db.execute(
        select(Task, Taxonomy)
        .outerjoin(Taxonomy, Task.taxonomy_id == Taxonomy.id)
        .where(Task.scene_id == scene.id, Task.is_deleted == False)
        .order_by(Task.created_at.asc())
    )
    tasks_with_taxonomy: List[Tuple[Task, Optional[str]]] = [
        (t, tx.name if tx else None) for t, tx in task_taxonomy_result.all()
    ]
    logger.debug(f"[DEBUG] Loaded {len(tasks_with_taxonomy)} tasks for multi-taxonomy routing")

    lidar_annotations_dir = annotations_dir / "lidar"
    if not lidar_annotations_dir.exists():
        lidar_annotations_dir = annotations_dir / "label_2"
    if not lidar_annotations_dir.exists():
        lidar_annotations_dir = scene_dir / "label_2"
    if lidar_annotations_dir.exists():
        txt_files = sorted([f for f in lidar_annotations_dir.iterdir() if f.suffix == ".txt"])
        for txt_file in txt_files:
            try:
                frame_index = int(txt_file.stem)
            except ValueError:
                continue
            
            frame = frame_by_index.get(frame_index)
            if not frame:
                continue
            
            with open(txt_file, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) < 15:
                        continue
                    
                    track_id_val = None
                    if len(parts) >= 17 and parts[0].isdigit() and parts[1].isdigit():
                        class_label = parts[2]
                        if class_label.lower() in ("dontcare", "dont_care"):
                            continue
                        try:
                            track_int = int(parts[1])
                            track_id_val = uuid.uuid5(scene.id, f"track-{track_int}")
                            height = float(parts[10])
                            width = float(parts[11])
                            length = float(parts[12])
                            x = float(parts[13])
                            y = float(parts[14])
                            z = float(parts[15])
                            rotation_y = float(parts[16])
                        except (ValueError, IndexError):
                            continue
                    else:
                        class_label = parts[0]
                        if class_label.lower() in ("dontcare", "dont_care"):
                            continue
                        try:
                            height = float(parts[8])
                            width = float(parts[9])
                            length = float(parts[10])
                            x = float(parts[11])
                            y = float(parts[12])
                            z = float(parts[13])
                            rotation_y = float(parts[14])
                        except (ValueError, IndexError):
                            continue
                    
                    mapped_class_id = map_class_to_taxonomy(class_label, class_mapping) if class_mapping else class_label
                    
                    annotation_3d = Annotation3D(
                        task_id=task.id,
                        frame_id=frame.id,
                        track_id=track_id_val,
                        type="cuboid",
                        class_id=mapped_class_id,
                        taxonomy_id=task.taxonomy_id,
                        data={
                            "center": {"x": x, "y": y, "z": z},
                            "dimensions": {"length": length, "width": width, "height": height},
                            "rotation": {"yaw": rotation_y, "pitch": 0.0, "roll": 0.0}
                        },
                        source="auto",
                    )
                    db.add(annotation_3d)
                    annotations_3d_count += 1
    
    json_files = sorted(
        [
            f for f in annotations_dir.rglob("*.json")
            if f.is_file() and f.name != "metadata.json"
        ],
        key=lambda p: str(p),
    )
    for json_file in json_files:
        annotation_task = task
        if json_file.parent.parent.name == "tasks":
            matched_task = match_folder_to_task(json_file.parent.name, tasks_with_taxonomy)
            if matched_task:
                annotation_task = matched_task
                logger.debug(f"[DEBUG] Routing '{json_file.name}' in '{json_file.parent.name}' -> task '{matched_task.name}'")
            else:
                logger.debug(f"[DEBUG] No task match for folder '{json_file.parent.name}', using default task")

        camera_name = json_file.stem
        
        try:
            with open(json_file, "r") as f:
                coco_data = json.load(f)

            info = coco_data.get("info") or {}
            info_description = str(info.get("description") or "").strip()
            if info_description.lower().startswith("annotations for camera:"):
                extracted_camera = info_description.split(":", 1)[1].strip()
                if extracted_camera:
                    camera_name = extracted_camera
            elif camera_name.lower() in {"default", "images", "camera"}:
                camera_name = default_camera_id
            
            if "annotations" not in coco_data or "images" not in coco_data:
                continue

            for tr in coco_data.get("tracks", []):
                raw_tid = tr.get("id")
                if not raw_tid:
                    continue
                try:
                    tid = uuid.UUID(str(raw_tid))
                except (ValueError, AttributeError, TypeError):
                    continue
                track_meta_overrides[tid] = tr
            
            image_id_to_frame = {}
            for img in coco_data.get("images", []):
                frame_index = img.get("frame_index")
                if isinstance(frame_index, int):
                    image_id_to_frame[img["id"]] = frame_index
                    continue

                file_name = img.get("file_name", "")
                try:
                    parsed_index = int(Path(file_name).stem)
                    image_id_to_frame[img["id"]] = parsed_index
                except (ValueError, KeyError, TypeError):
                    continue
            
            for ann in coco_data.get("annotations", []):
                image_id = ann.get("image_id")
                frame_index = image_id_to_frame.get(image_id)
                if frame_index is None:
                    continue
                
                frame = frame_by_index.get(frame_index)
                if not frame:
                    continue
                
                category_id = ann.get("category_id")
                class_label = None
                for cat in coco_data.get("categories", []):
                    if cat["id"] == category_id:
                        class_label = cat.get("name", str(category_id))
                        break
                if not class_label:
                    class_label = ann.get("class")
                if not class_label:
                    class_label = str(category_id)
                
                mapped_class_id = map_class_to_taxonomy(class_label, class_mapping) if class_mapping else class_label

                ann_type = ann.get("type", "box2d").lower()
                ann_db_type: str
                ann_db_data: dict

                if ann_type in ("polyline", "line", "bezier"):
                    raw_polyline = ann.get("polyline")
                    if raw_polyline and isinstance(raw_polyline, list):
                        points = [{"x": p[0], "y": p[1]} for p in raw_polyline if len(p) >= 2]
                    else:
                        seg = ann.get("segmentation")
                        flat = seg[0] if seg and isinstance(seg, list) and seg else []
                        points = [{"x": flat[i], "y": flat[i + 1]} for i in range(0, len(flat) - 1, 2)]
                    if not points:
                        continue
                    ann_db_type = "polyline"
                    ann_db_data = {"points": points, "isBezier": False}

                elif ann_type in ("polygon", "semantic_segment"):
                    raw_polygon = ann.get("polygon")
                    if raw_polygon and isinstance(raw_polygon, list):
                        points = [{"x": p[0], "y": p[1]} for p in raw_polygon if len(p) >= 2]
                    else:
                        seg = ann.get("segmentation")
                        flat = seg[0] if seg and isinstance(seg, list) and seg else []
                        points = [{"x": flat[i], "y": flat[i + 1]} for i in range(0, len(flat) - 1, 2)]
                    if not points:
                        continue
                    if ann_type == "semantic_segment":
                        ann_db_type = "semantic_segment"
                        ann_db_data = {"polygon": points, "isClosed": True}
                    else:
                        ann_db_type = "polygon"
                        ann_db_data = {"points": points}

                elif ann_type == "ellipse":
                    ed = ann.get("ellipse")
                    if ed and isinstance(ed, dict):
                        ann_db_type = "ellipse"
                        ann_db_data = {"cx": ed["cx"], "cy": ed["cy"], "rx": ed["rx"], "ry": ed["ry"]}
                    else:
                        bbox = ann.get("bbox", [])
                        if len(bbox) < 4:
                            continue
                        ann_db_type = "ellipse"
                        ann_db_data = {"cx": bbox[0] + bbox[2] / 2, "cy": bbox[1] + bbox[3] / 2,
                                       "rx": bbox[2] / 2, "ry": bbox[3] / 2}

                elif ann_type in ("rotated_box", "rotated_rectangle"):
                    rb = ann.get("rotated_box")
                    if rb and isinstance(rb, dict):
                        ann_db_type = "rotated_box"
                        ann_db_data = {"cx": rb["cx"], "cy": rb["cy"],
                                       "width": rb["width"], "height": rb["height"],
                                       "rotation": rb.get("angle", rb.get("rotation", 0))}
                    else:
                        bbox = ann.get("bbox", [])
                        if len(bbox) < 4:
                            continue
                        ann_db_type = "rotated_box"
                        ann_db_data = {"cx": bbox[0] + bbox[2] / 2, "cy": bbox[1] + bbox[3] / 2,
                                       "width": bbox[2], "height": bbox[3], "rotation": 0.0}

                elif ann_type in ("keypoints", "points"):
                    kf = ann.get("keypoints")
                    knames = ann.get("keypoint_names", [])
                    if kf and isinstance(kf, list):
                        pts = []
                        for i in range(0, len(kf), 3):
                            label = knames[i // 3] if i // 3 < len(knames) else f"P{i // 3 + 1}"
                            pts.append({"x": kf[i], "y": kf[i + 1], "label": label,
                                        "visibility": int(kf[i + 2]) if i + 2 < len(kf) else 2})
                        ann_db_type = "keypoints"
                        ann_db_data = {"points": pts}
                    else:
                        bbox = ann.get("bbox", [0, 0, 0, 0])
                        ann_db_type = "box2d"
                        ann_db_data = {"bbox": {"x": bbox[0], "y": bbox[1], "width": bbox[2], "height": bbox[3]}}

                else:
                    bbox = ann.get("bbox", [])
                    if len(bbox) < 4:
                        continue
                    ann_db_type = "box2d"
                    ann_db_data = {"bbox": {"x": bbox[0], "y": bbox[1], "width": bbox[2], "height": bbox[3]}}

                source_track_uuid: Optional[uuid.UUID] = None
                raw_track_id = ann.get("track_id")
                if raw_track_id:
                    try:
                        source_track_uuid = uuid.UUID(str(raw_track_id))
                    except (ValueError, AttributeError, TypeError):
                        source_track_uuid = None

                new_track_uuid: Optional[uuid.UUID] = None
                if source_track_uuid is not None:
                    track_meta = imported_tracks_2d.get(source_track_uuid)
                    if track_meta is None:
                        new_track_uuid = uuid.uuid4()
                        imported_tracks_2d[source_track_uuid] = {
                            "new_id": new_track_uuid,
                            "task_id": annotation_task.id,
                            "camera_id": camera_name,
                            "class_id": mapped_class_id,
                            "start_frame_index": frame_index,
                            "end_frame_index": frame_index,
                        }
                    else:
                        new_track_uuid = track_meta["new_id"]
                        track_meta["start_frame_index"] = min(track_meta["start_frame_index"], frame_index)
                        track_meta["end_frame_index"] = max(track_meta["end_frame_index"], frame_index)

                annotation_2d = Annotation2D(
                    task_id=annotation_task.id,
                    frame_id=frame.id,
                    camera_id=camera_name,
                    type=ann_db_type,
                    class_id=mapped_class_id,
                    taxonomy_id=annotation_task.taxonomy_id,
                    data=ann_db_data,
                    attributes=ann.get("attributes", {}),
                    track_id=new_track_uuid,
                    source="auto",
                )
                db.add(annotation_2d)
                annotations_2d_count += 1
        except Exception:
            continue

    for source_track_uuid, track_meta in imported_tracks_2d.items():
        override = track_meta_overrides.get(source_track_uuid, {})
        start_idx = override.get("start_frame_index")
        end_idx = override.get("end_frame_index")

        class_id = track_meta["class_id"]
        class_info = class_info_by_id.get(class_id, {})

        name = override.get("name")
        if not name:
            name = f"{class_id}_{track_meta['new_id']}"

        color = override.get("color") or class_info.get("color")

        db.add(Track2D(
            id=track_meta["new_id"],
            task_id=track_meta["task_id"],
            camera_id=track_meta["camera_id"],
            class_id=class_id,
            name=name,
            color=color,
            start_frame_index=start_idx if start_idx is not None else track_meta["start_frame_index"],
            end_frame_index=end_idx if end_idx is not None else track_meta["end_frame_index"],
            is_interpolated=bool(override.get("is_interpolated", False)),
            is_complete=bool(override.get("is_complete", False)),
            attributes=override.get("attributes") or {},
        ))
    if imported_tracks_2d:
        logger.info(f"[IMPORT] Recreated {len(imported_tracks_2d)} 2D track(s) from imported annotations")

    try:
        label_files = sorted(annotations_dir.rglob("*.label"))
        if label_files:
            seg_dir = os.path.join(SEGMENTATION_ROOT, str(scene.id))
            os.makedirs(seg_dir, exist_ok=True)

            seg_frames_imported = 0
            for label_file in label_files:
                try:
                    frame_index = int(label_file.stem.lstrip("0") or "0")
                except ValueError:
                    logger.warning(f"[IMPORT] Cannot parse frame index from {label_file.name}")
                    continue

                frame = frame_by_index.get(frame_index)
                if not frame:
                    logger.warning(f"[IMPORT] No frame for index {frame_index} ({label_file.name})")
                    continue

                kitti = np.frombuffer(label_file.read_bytes(), dtype=np.uint32)

                semantic = (kitti & 0xFFFF).astype(np.int32)
                instances = (kitti >> 16).astype(np.int32)

                labels = np.where(semantic == 0, -1, semantic - 1).astype(np.int32)
                inst_arr = np.where(instances == 0, -1, instances).astype(np.int32)

                # Write BOTH segmentation layers. The editor opens in semantic mode
                # and renders the semantic layer (`_semantic.npy`); it also reads the
                # instance layer (`.npy` + `_instances.npy`). Writing only the instance
                # layer left the default semantic view empty ("labels not seen").
                np.save(os.path.join(seg_dir, f"{frame.id}_semantic.npy"), labels)
                np.save(os.path.join(seg_dir, f"{frame.id}.npy"), labels)
                if np.any(inst_arr >= 0):
                    np.save(os.path.join(seg_dir, f"{frame.id}_instances.npy"), inst_arr)

                seg_frames_imported += 1

            if seg_frames_imported:
                logger.info(f"[IMPORT] Restored 3D segmentation for {seg_frames_imported} frame(s)")
                # Ensure the dataset has a segmentation_3d taxonomy whose class order
                # matches the stored 0-based labels, so the editor can color points.
                try:
                    ordered = _read_segmentation_class_order(annotations_dir)
                    if ordered:
                        seg_tax = await ensure_segmentation_taxonomy(db, scene, ordered)
                        # Bind the import task to the segmentation taxonomy. The task
                        # is created at scene-creation time — before this taxonomy
                        # exists — so it starts with taxonomy_id=None; wire it up here
                        # so it becomes a proper segmentation task (correct editor,
                        # task lists, workflow).
                        if seg_tax and task is not None and getattr(task, "taxonomy_id", None) is None:
                            task.taxonomy_id = seg_tax.id
                            await db.flush()
                except Exception as tax_err:
                    logger.warning(f"[IMPORT] Could not derive segmentation taxonomy: {tax_err}")
    except Exception as e:
        import traceback
        logger.error(f"[IMPORT] Error restoring 3D segmentation: {type(e).__name__}: {str(e) or traceback.format_exc()}")

    return annotations_3d_count, annotations_2d_count


