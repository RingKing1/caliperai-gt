"""ZIP annotation import pipeline: fingerprinting, dedupe, DB persistence."""
import io
import json
import os
import zipfile
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation2D,
    Annotation3D,
    AnnotationSource,
    Dataset,
    Frame,
    Scene,
    Task,
    TaxonomyAnnotationMode,
    Track2D,
)
from app.services.dataset_import.annotation_parsers import (
    compute_3d_annotation_fingerprint,
    compute_annotation_fingerprint,
    detect_annotation_mode_from_file,
    parse_calipergt_2d_annotations,
    parse_coco_2d_annotations,
    parse_coco_3d_annotations,
    parse_cvat_json_annotations,
)
from app.services.dataset_import.constants import SEGMENTATION_ROOT
from app.services.dataset_import.taxonomy import map_source_class_to_taxonomy


def build_empty_import_results() -> dict[str, Any]:
    """Create a blank import results structure compatible with process_zip_annotations output."""
    return {
        "sensors_processed": {},
        "total_imported": 0,
        "errors": [],
        "unique_class_ids": set(),
        "coco_categories": {},
        "detected_modes": set(),
        "class_ids_by_mode": {
            TaxonomyAnnotationMode.FUSION_3D.value: set(),
            TaxonomyAnnotationMode.ONLY_2D.value: set(),
        },
        "skipped_duplicates": 0,
    }


def merge_import_results(base: dict[str, Any], part: dict[str, Any], sensor_prefix: str | None = None) -> None:
    """Merge a per-task import result into an aggregated result."""
    for sensor_name, count in (part.get("sensors_processed") or {}).items():
        key = f"{sensor_prefix}/{sensor_name}" if sensor_prefix else sensor_name
        base["sensors_processed"][key] = base["sensors_processed"].get(key, 0) + count

    base["total_imported"] += int(part.get("total_imported", 0))
    base["errors"].extend(part.get("errors") or [])
    base["unique_class_ids"].update(part.get("unique_class_ids") or set())
    base["coco_categories"].update(part.get("coco_categories") or {})
    base["detected_modes"].update(part.get("detected_modes") or set())

    base_fusion = base["class_ids_by_mode"][TaxonomyAnnotationMode.FUSION_3D.value]
    base_2d = base["class_ids_by_mode"][TaxonomyAnnotationMode.ONLY_2D.value]
    part_modes = part.get("class_ids_by_mode") or {}
    base_fusion.update(part_modes.get(TaxonomyAnnotationMode.FUSION_3D.value, set()))
    base_2d.update(part_modes.get(TaxonomyAnnotationMode.ONLY_2D.value, set()))

    base["skipped_duplicates"] += int(part.get("skipped_duplicates", 0))


def extract_task_id_from_folder_name(folder_name: str) -> UUID | None:
    """Extract a UUID from a task export folder name like 'Task_Name__ab12cd34' when possible."""
    if "__" not in folder_name:
        return None
    maybe_id = folder_name.split("__", 1)[1]
    try:
        return UUID(maybe_id)
    except Exception:
        return None


def build_subzip_for_task_folder(zip_content: bytes, task_folder_prefix: str, metadata: dict[str, Any] | None = None) -> bytes | None:
    """Create an in-memory ZIP containing just one task folder remapped under annotations/."""
    if not task_folder_prefix:
        return None

    prefix = task_folder_prefix.strip("/") + "/"
    out = io.BytesIO()
    copied = 0

    with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as src:
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
            for name in src.namelist():
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
                if not rel:
                    continue
                dst.writestr(f"annotations/{rel}", src.read(name))
                copied += 1

            if copied > 0 and metadata:
                dst.writestr("metadata.json", json.dumps(metadata, indent=2))

    if copied == 0:
        return None
    return out.getvalue()


async def process_zip_annotations(
    zip_content: bytes,
    scene: Scene,
    task: Task,
    frame_id_map: dict[int, UUID],
    db: AsyncSession,
    taxonomy_id: UUID | None = None,
) -> dict[str, Any]:
    """
    Process a ZIP file containing per-sensor annotation files.

    Expected ZIP structure:
        annotations/
        ├── lidar/
        │   ├── 000000.txt    # KITTI format per frame
        │   ├── 000001.txt
        │   └── ...
        ├── camera_front.json  # COCO format
        ├── camera_rear.json
        └── ...

    Returns dict with counts per sensor and any errors.
    """
    results = {
        "sensors_processed": {},
        "total_imported": 0,
        "errors": [],
        "unique_class_ids": set(),
        "coco_categories": {},
        "detected_modes": set(),
        "class_ids_by_mode": {
            TaxonomyAnnotationMode.FUSION_3D.value: set(),
            TaxonomyAnnotationMode.ONLY_2D.value: set(),
        }
    }

    dataset_result = await db.execute(
        select(Dataset).where(Dataset.id == scene.dataset_id)
    )
    dataset = dataset_result.scalar_one_or_none()
    taxonomy = dataset.taxonomy if dataset else None

    default_camera_id = "default"
    if frame_id_map:
        first_frame_id = list(frame_id_map.values())[0]
        frame_result = await db.execute(select(Frame).where(Frame.id == first_frame_id))
        first_frame = frame_result.scalar_one_or_none()
        if first_frame and first_frame.file_paths:
            cameras = first_frame.file_paths.get("cameras", {})
            if cameras:
                default_camera_id = list(cameras.keys())[0]

    existing_2d_fingerprints = set()
    existing_3d_fingerprints = set()

    existing_2d_query = select(Annotation2D).where(Annotation2D.task_id == task.id)
    existing_2d_result = await db.execute(existing_2d_query)
    for ann in existing_2d_result.scalars().all():
        data = ann.data or {}
        bbox = data.get("bbox", {})
        fp = compute_annotation_fingerprint(
            ann.frame_id, ann.camera_id or "",
            bbox.get("x", 0), bbox.get("y", 0), bbox.get("width", 0), bbox.get("height", 0)
        )
        existing_2d_fingerprints.add(fp)

    existing_3d_query = select(Annotation3D).where(Annotation3D.task_id == task.id)
    existing_3d_result = await db.execute(existing_3d_query)
    for ann in existing_3d_result.scalars().all():
        data = ann.data or {}
        center = data.get("center", {})
        dims = data.get("dimensions", {})
        fp = compute_3d_annotation_fingerprint(
            ann.frame_id,
            center.get("x", 0), center.get("y", 0), center.get("z", 0),
            dims.get("length", 0), dims.get("width", 0), dims.get("height", 0)
        )
        existing_3d_fingerprints.add(fp)

    skipped_duplicates = 0

    try:
        with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
            json_files = [
                f for f in zf.namelist()
                if f.endswith('.json')
                and '__MACOSX' not in f
                and not any(part.startswith('.') for part in f.split('/'))
            ]

            lidar_txt_files = [
                f for f in zf.namelist()
                if f.endswith('.txt')
                and ('lidar/' in f.lower() or '/lidar/' in f.lower() or 'label_2/' in f.lower() or '/label_2/' in f.lower())
                and '__MACOSX' not in f
                and not any(part.startswith('.') for part in f.split('/'))
            ]

            for json_file in json_files:
                file_name = json_file.split('/')[-1]
                if file_name == 'metadata.json':
                    continue

                sensor_name = file_name.replace('.json', '')

                try:
                    try:
                        content = zf.read(json_file).decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            content = zf.read(json_file).decode('latin-1')
                        except:
                            results["errors"].append(f"Encoding error in {json_file}")
                            continue

                    coco_data = json.loads(content)

                    if "categories" in coco_data and isinstance(coco_data["categories"], list):
                        for cat in coco_data["categories"]:
                            if isinstance(cat, dict) and "id" in cat:
                                results["coco_categories"][cat["id"]] = cat

                    annotations_to_create = []

                    is_lidar = sensor_name.lower() in ['lidar', 'lidar_4d', 'velodyne', 'point_cloud']
                    has_frames = 'frames' in coco_data
                    is_coco_2d = 'images' in coco_data and 'annotations' in coco_data
                    cvat_shaped_tracks = (
                        isinstance(coco_data.get('tracks'), list)
                        and any(isinstance(t, dict) and 'shapes' in t for t in coco_data['tracks'])
                    )
                    is_cvat_json = (not is_coco_2d) and (
                        cvat_shaped_tracks or ('shapes' in coco_data and 'version' in coco_data)
                    )
                    is_calipergt = (
                        "items" in coco_data
                        and isinstance(coco_data.get("categories"), dict)
                        and "label" in coco_data.get("categories", {})
                    )

                    file_mode = detect_annotation_mode_from_file(coco_data, sensor_name)
                    results["detected_modes"].add(file_mode)

                    if is_cvat_json:
                        annotations_to_create = parse_cvat_json_annotations(coco_data, frame_id_map, taxonomy)
                    elif is_calipergt:
                        annotations_to_create = parse_calipergt_2d_annotations(
                            coco_data, default_camera_id, frame_id_map, taxonomy
                        )
                    elif is_lidar or has_frames:
                        annotations_to_create = parse_coco_3d_annotations(coco_data, frame_id_map, taxonomy)
                    else:
                        annotations_to_create = parse_coco_2d_annotations(
                            coco_data, default_camera_id, frame_id_map, taxonomy
                        )

                    track_id_remap: dict[str, UUID] = {}
                    is_2d_file = not is_cvat_json and not (is_lidar or has_frames)
                    if is_2d_file:
                        for tr in (coco_data.get("tracks") or []):
                            orig_id = tr.get("id")
                            if orig_id is None:
                                continue
                            new_track = Track2D(
                                id=uuid4(),
                                task_id=task.id,
                                camera_id=default_camera_id,
                                class_id=tr.get("class_id") or "unknown",
                                name=tr.get("name"),
                                color=tr.get("color"),
                                start_frame_index=tr.get("start_frame_index"),
                                end_frame_index=tr.get("end_frame_index"),
                                is_interpolated=bool(tr.get("is_interpolated", False)),
                                is_complete=bool(tr.get("is_complete", False)),
                                attributes=tr.get("attributes") or {},
                            )
                            db.add(new_track)
                            track_id_remap[str(orig_id)] = new_track.id

                    sensor_count = 0
                    for ann_data in annotations_to_create:
                        try:
                            if ann_data.get("type") == "3d" or "position_x" in ann_data:
                                frame_id = frame_id_map.get(ann_data["frame_index"])
                                if not frame_id:
                                    continue

                                fp = compute_3d_annotation_fingerprint(
                                    frame_id,
                                    ann_data["position_x"], ann_data["position_y"], ann_data["position_z"],
                                    ann_data["dimension_length"], ann_data["dimension_width"], ann_data["dimension_height"]
                                )
                                if fp in existing_3d_fingerprints:
                                    skipped_duplicates += 1
                                    continue
                                existing_3d_fingerprints.add(fp)

                                results["class_ids_by_mode"][TaxonomyAnnotationMode.FUSION_3D.value].add(ann_data["class_id"])

                                annotation = Annotation3D(
                                    id=uuid4(),
                                    task_id=task.id,
                                    track_id=uuid4() if ann_data.get("track_id") else None,
                                    frame_id=frame_id,
                                    class_id=ann_data["class_id"],
                                    taxonomy_id=taxonomy_id,
                                    data={
                                        "center": {
                                            "x": ann_data["position_x"],
                                            "y": ann_data["position_y"],
                                            "z": ann_data["position_z"],
                                        },
                                        "dimensions": {
                                            "length": ann_data["dimension_length"],
                                            "width": ann_data["dimension_width"],
                                            "height": ann_data["dimension_height"],
                                        },
                                        "rotation": {
                                            "yaw": ann_data["rotation_yaw"],
                                            "pitch": ann_data.get("rotation_pitch", 0.0),
                                            "roll": ann_data.get("rotation_roll", 0.0),
                                        },
                                        "confidence": ann_data.get("confidence", 1.0),
                                    },
                                    attributes=ann_data.get("attributes", {}),
                                    source=ann_data.get("source", AnnotationSource.AUTO.value),
                                )
                            else:
                                frame_id = ann_data.get("frame_id")
                                if not frame_id:
                                    frame_id = frame_id_map.get(ann_data["frame_index"])
                                if not frame_id:
                                    continue

                                results["class_ids_by_mode"][TaxonomyAnnotationMode.ONLY_2D.value].add(ann_data["class_id"])

                                resolved_track_id = None
                                orig_track_id = ann_data.get("track_id")
                                if orig_track_id is not None:
                                    track_key = str(orig_track_id)
                                    resolved_track_id = track_id_remap.get(track_key)
                                    if resolved_track_id is None:
                                        fallback_track = Track2D(
                                            id=uuid4(),
                                            task_id=task.id,
                                            camera_id=ann_data.get("camera_id", sensor_name),
                                            class_id=ann_data["class_id"],
                                            is_interpolated=False,
                                            is_complete=False,
                                            attributes={},
                                        )
                                        db.add(fallback_track)
                                        track_id_remap[track_key] = fallback_track.id
                                        resolved_track_id = fallback_track.id

                                polyline_points = ann_data.get("polyline_points")
                                polygon_points = ann_data.get("polygon_points")
                                if polyline_points:
                                    annotation = Annotation2D(
                                        id=uuid4(),
                                        task_id=task.id,
                                        track_id=resolved_track_id,
                                        frame_id=frame_id,
                                        camera_id=ann_data.get("camera_id", sensor_name),
                                        class_id=ann_data["class_id"],
                                        taxonomy_id=taxonomy_id,
                                        type="polyline",
                                        data={
                                            "points": polyline_points,
                                            "isBezier": False,
                                        },
                                        attributes=ann_data.get("attributes", {}),
                                        source=ann_data.get("source", AnnotationSource.AUTO.value)
                                    )
                                elif ann_data.get("ellipse_data"):
                                    ed = ann_data["ellipse_data"]
                                    annotation = Annotation2D(
                                        id=uuid4(),
                                        task_id=task.id,
                                        track_id=resolved_track_id,
                                        frame_id=frame_id,
                                        camera_id=ann_data.get("camera_id", sensor_name),
                                        class_id=ann_data["class_id"],
                                        taxonomy_id=taxonomy_id,
                                        type="ellipse",
                                        data={
                                            "cx": ed["cx"], "cy": ed["cy"],
                                            "rx": ed["rx"], "ry": ed["ry"],
                                        },
                                        attributes=ann_data.get("attributes", {}),
                                        source=ann_data.get("source", AnnotationSource.AUTO.value)
                                    )
                                elif ann_data.get("rotated_box_data"):
                                    rb = ann_data["rotated_box_data"]
                                    annotation = Annotation2D(
                                        id=uuid4(),
                                        task_id=task.id,
                                        track_id=resolved_track_id,
                                        frame_id=frame_id,
                                        camera_id=ann_data.get("camera_id", sensor_name),
                                        class_id=ann_data["class_id"],
                                        taxonomy_id=taxonomy_id,
                                        type="rotated_box",
                                        data={
                                            "cx": rb["cx"], "cy": rb["cy"],
                                            "width": rb["width"], "height": rb["height"],
                                            "rotation": rb.get("angle", rb.get("rotation", 0)),
                                        },
                                        attributes=ann_data.get("attributes", {}),
                                        source=ann_data.get("source", AnnotationSource.AUTO.value)
                                    )
                                elif ann_data.get("keypoints_flat"):
                                    kf = ann_data["keypoints_flat"]
                                    knames = ann_data.get("keypoint_names", [])
                                    pts = []
                                    for i in range(0, len(kf), 3):
                                        label = knames[i // 3] if i // 3 < len(knames) else f"P{i // 3 + 1}"
                                        pts.append({"x": kf[i], "y": kf[i+1], "label": label, "visibility": int(kf[i+2]) if i+2 < len(kf) else 2})
                                    annotation = Annotation2D(
                                        id=uuid4(),
                                        task_id=task.id,
                                        track_id=resolved_track_id,
                                        frame_id=frame_id,
                                        camera_id=ann_data.get("camera_id", sensor_name),
                                        class_id=ann_data["class_id"],
                                        taxonomy_id=taxonomy_id,
                                        type="keypoints",
                                        data={"points": pts},
                                        attributes=ann_data.get("attributes", {}),
                                        source=ann_data.get("source", AnnotationSource.AUTO.value)
                                    )
                                elif polygon_points:
                                    pts = []
                                    for i in range(0, len(polygon_points), 2):
                                        if i + 1 < len(polygon_points):
                                            pts.append({"x": polygon_points[i], "y": polygon_points[i + 1]})

                                    orig_type = ann_data.get("ann_type", "")
                                    if orig_type == "semantic_segment":
                                        ann_db_type = "semantic_segment"
                                        ann_db_data = {
                                            "polygon": pts,
                                            "isClosed": True,
                                        }
                                    else:
                                        ann_db_type = "polygon"
                                        ann_db_data = {"points": pts}

                                    annotation = Annotation2D(
                                        id=uuid4(),
                                        task_id=task.id,
                                        track_id=resolved_track_id,
                                        frame_id=frame_id,
                                        camera_id=ann_data.get("camera_id", sensor_name),
                                        class_id=ann_data["class_id"],
                                        taxonomy_id=taxonomy_id,
                                        type=ann_db_type,
                                        data=ann_db_data,
                                        attributes=ann_data.get("attributes", {}),
                                        source=ann_data.get("source", AnnotationSource.AUTO.value)
                                    )
                                else:
                                    fp = compute_annotation_fingerprint(
                                        frame_id, ann_data.get("camera_id", sensor_name),
                                        ann_data["bbox_x"], ann_data["bbox_y"],
                                        ann_data["bbox_width"], ann_data["bbox_height"]
                                    )
                                    if fp in existing_2d_fingerprints:
                                        skipped_duplicates += 1
                                        continue
                                    existing_2d_fingerprints.add(fp)

                                    annotation = Annotation2D(
                                        id=uuid4(),
                                        task_id=task.id,
                                        track_id=resolved_track_id,
                                        frame_id=frame_id,
                                        camera_id=ann_data.get("camera_id", sensor_name),
                                        class_id=ann_data["class_id"],
                                        taxonomy_id=taxonomy_id,
                                        type="box2d",
                                        data={
                                            "bbox": {
                                                "x": ann_data["bbox_x"],
                                                "y": ann_data["bbox_y"],
                                                "width": ann_data["bbox_width"],
                                                "height": ann_data["bbox_height"]
                                            }
                                        },
                                        attributes=ann_data.get("attributes", {}),
                                        source=ann_data.get("source", AnnotationSource.AUTO.value)
                                    )

                            results["unique_class_ids"].add(ann_data["class_id"])

                            db.add(annotation)
                            sensor_count += 1

                        except Exception as e:
                            import traceback
                            error_msg = f"{type(e).__name__}: {str(e)}"
                            if not str(e):
                                error_msg = f"{type(e).__name__}: {traceback.format_exc()}"
                            results["errors"].append(f"Error creating annotation in {sensor_name}: {error_msg}")

                    results["sensors_processed"][sensor_name] = sensor_count
                    results["total_imported"] += sensor_count

                except json.JSONDecodeError as e:
                    results["errors"].append(f"Invalid JSON in {json_file}: {str(e)}")
                except Exception as e:
                    import traceback
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    if not str(e):
                        error_msg = f"{type(e).__name__}: {traceback.format_exc()}"
                    results["errors"].append(f"Error processing {json_file}: {error_msg}")

            if lidar_txt_files:
                sensor_name = "lidar"
                sensor_count = 0

                try:
                    kitti_annotations = []

                    for txt_file in lidar_txt_files:
                        try:
                            file_name = txt_file.split('/')[-1]
                            frame_index_str = file_name.replace('.txt', '')
                            try:
                                frame_index = int(frame_index_str.lstrip('0') or '0')
                            except ValueError:
                                results["errors"].append(f"Could not parse frame index from {txt_file}")
                                continue

                            content = zf.read(txt_file).decode('utf-8')
                            kitti_lines = content.strip().split('\n')

                            for line in kitti_lines:
                                parts = line.strip().split()
                                if len(parts) < 15:
                                    continue

                                offset = 0
                                track_id_from_file = None
                                if len(parts) >= 17:
                                    try:
                                        int(parts[0])
                                        track_id_from_file = int(parts[1])
                                        offset = 2
                                    except ValueError:
                                        pass

                                class_name = parts[0 + offset]
                                truncated = float(parts[1 + offset])
                                occluded = int(parts[2 + offset])
                                alpha = float(parts[3 + offset])

                                height = float(parts[8 + offset])
                                width = float(parts[9 + offset])
                                length = float(parts[10 + offset])

                                location_x = float(parts[11 + offset])
                                location_y = float(parts[12 + offset])
                                location_z = float(parts[13 + offset])

                                rotation_y = float(parts[14 + offset])

                                score = float(parts[15 + offset]) if len(parts) > (15 + offset) else 1.0

                                class_id = map_source_class_to_taxonomy(class_name, taxonomy) if taxonomy else class_name.lower()

                                if class_name.lower() == 'dontcare':
                                    continue

                                ann_data = {
                                    "frame_index": frame_index,
                                    "class_id": class_id,
                                    "track_id_num": track_id_from_file,
                                    "position_x": location_x,
                                    "position_y": location_y,
                                    "position_z": location_z,
                                    "dimension_length": length,
                                    "dimension_width": width,
                                    "dimension_height": height,
                                    "rotation_yaw": rotation_y,
                                    "rotation_pitch": 0.0,
                                    "rotation_roll": 0.0,
                                    "attributes": {
                                        "truncated": truncated,
                                        "occluded": occluded,
                                        "alpha": alpha
                                    },
                                    "source": AnnotationSource.AUTO.value,
                                    "confidence": score
                                }

                                kitti_annotations.append(ann_data)

                        except Exception as e:
                            import traceback
                            error_msg = f"{type(e).__name__}: {str(e)}"
                            if not str(e):
                                error_msg = f"{type(e).__name__}: {traceback.format_exc()}"
                            results["errors"].append(f"Error reading {txt_file}: {error_msg}")

                    track_id_mapping: dict[int, UUID] = {}

                    for ann_data in kitti_annotations:
                        try:
                            frame_id = frame_id_map.get(ann_data["frame_index"])
                            if not frame_id:
                                continue

                            track_uuid = None
                            track_id_num = ann_data.get("track_id_num")
                            if track_id_num is not None:
                                if track_id_num not in track_id_mapping:
                                    track_id_mapping[track_id_num] = uuid4()
                                track_uuid = track_id_mapping[track_id_num]

                            annotation = Annotation3D(
                                id=uuid4(),
                                task_id=task.id,
                                track_id=track_uuid,
                                frame_id=frame_id,
                                class_id=ann_data["class_id"],
                                taxonomy_id=taxonomy_id,
                                data={
                                    "center": {
                                        "x": ann_data["position_x"],
                                        "y": ann_data["position_y"],
                                        "z": ann_data["position_z"],
                                    },
                                    "dimensions": {
                                        "length": ann_data["dimension_length"],
                                        "width": ann_data["dimension_width"],
                                        "height": ann_data["dimension_height"],
                                    },
                                    "rotation": {
                                        "yaw": ann_data["rotation_yaw"],
                                        "pitch": ann_data.get("rotation_pitch", 0.0),
                                        "roll": ann_data.get("rotation_roll", 0.0),
                                    },
                                    "confidence": ann_data.get("confidence", 1.0),
                                },
                                attributes=ann_data.get("attributes", {}),
                                source=ann_data.get("source", AnnotationSource.AUTO.value),
                            )

                            results["unique_class_ids"].add(ann_data["class_id"])

                            db.add(annotation)
                            sensor_count += 1

                        except Exception as e:
                            import traceback
                            error_msg = f"{type(e).__name__}: {str(e)}"
                            if not str(e):
                                error_msg = f"{type(e).__name__}: {traceback.format_exc()}"
                            results["errors"].append(f"Error creating 3D annotation from KITTI: {error_msg}")

                    if sensor_count > 0:
                        results["sensors_processed"][sensor_name] = sensor_count
                        results["total_imported"] += sensor_count

                except Exception as e:
                    import traceback
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    if not str(e):
                        error_msg = f"{type(e).__name__}: {traceback.format_exc()}"
                    results["errors"].append(f"Error processing KITTI lidar annotations: {error_msg}")

            all_label_files = sorted(f for f in zf.namelist() if f.endswith('.label'))
            semantic_label_files = [f for f in all_label_files if 'lidar_segmentation_semantic/' in f]
            label_files = [f for f in all_label_files if f not in set(semantic_label_files)]
            if all_label_files:
                seg_frames_imported = 0
                try:
                    int_to_class: dict[int, str] = {}
                    all_names = zf.namelist()
                    for info_path in (
                        "annotations/lidar_segmentation/labels_info.json",
                        "segmentation/class_mapping.json",
                        "class_mapping.json",
                    ):
                        if info_path in all_names:
                            info_data = json.loads(zf.read(info_path))
                            if "categories" in info_data:
                                int_to_class = {c["id"]: c["name"] for c in info_data["categories"] if c["id"] != 0}
                            elif "classes" in info_data:
                                int_to_class = {int(k): v for k, v in info_data["classes"].items() if k != "0"}
                            break

                    seg_dir = os.path.join(SEGMENTATION_ROOT, str(scene.id))
                    os.makedirs(seg_dir, exist_ok=True)

                    for label_file in label_files:
                        try:
                            fname = label_file.split('/')[-1]
                            frame_index = int(fname.replace('.label', '').lstrip('0') or '0')
                        except ValueError:
                            results["errors"].append(f"Cannot parse frame index from {label_file}")
                            continue

                        frame_id = frame_id_map.get(frame_index)
                        if not frame_id:
                            results["errors"].append(f"No frame for index {frame_index} in {label_file}")
                            continue

                        raw = zf.read(label_file)
                        kitti = np.frombuffer(raw, dtype=np.uint32)

                        semantic = (kitti & 0xFFFF).astype(np.int32)
                        instances = (kitti >> 16).astype(np.int32)

                        labels = np.where(semantic == 0, -1, semantic - 1).astype(np.int32)
                        inst_arr = np.where(instances == 0, -1, instances).astype(np.int32)

                        np.save(os.path.join(seg_dir, f"{frame_id}.npy"), labels)
                        if np.any(inst_arr >= 0):
                            np.save(os.path.join(seg_dir, f"{frame_id}_instances.npy"), inst_arr)

                        seg_frames_imported += 1

                    for label_file in semantic_label_files:
                        try:
                            fname = label_file.split('/')[-1]
                            frame_index = int(fname.replace('.label', '').lstrip('0') or '0')
                        except ValueError:
                            results["errors"].append(f"Cannot parse frame index from {label_file}")
                            continue

                        frame_id = frame_id_map.get(frame_index)
                        if not frame_id:
                            results["errors"].append(f"No frame for index {frame_index} in {label_file}")
                            continue

                        kitti = np.frombuffer(zf.read(label_file), dtype=np.uint32)
                        sem = np.where(kitti == 0, -1, kitti.astype(np.int64) - 1).astype(np.int32)
                        np.save(os.path.join(seg_dir, f"{frame_id}_semantic.npy"), sem)
                        seg_frames_imported += 1

                    if seg_frames_imported:
                        results["sensors_processed"]["segmentation_3d"] = seg_frames_imported
                        results["total_imported"] += seg_frames_imported
                        if int_to_class:
                            for class_name in int_to_class.values():
                                results["unique_class_ids"].add(class_name)

                except Exception as e:
                    import traceback
                    results["errors"].append(
                        f"Error processing segmentation .label files: {type(e).__name__}: {str(e) or traceback.format_exc()}"
                    )

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid ZIP file"
        )

    results["skipped_duplicates"] = skipped_duplicates
    return results



