"""COCO-format annotation converter for 2D, 3D, 4D, and Fusion annotations."""
from __future__ import annotations

import json
import math
import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.models import Scene


def _pts_to_coords(raw: list) -> list[tuple[float, float]]:
    """Normalise a raw point list to [(x, y), ...] tuples.

    Accepts both [[x,y],...] and [{"x":x,"y":y},...] formats.
    """
    out: list[tuple[float, float]] = []
    for pt in raw or []:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            out.append((float(pt[0]), float(pt[1])))
        elif isinstance(pt, dict):
            out.append((float(pt.get("x", 0)), float(pt.get("y", 0))))
    return out


def _bbox_from_coords(coords: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Return (x, y, width, height) axis-aligned bounding box for a list of (x,y) pairs."""
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    x, y = min(xs), min(ys)
    return x, y, max(xs) - x, max(ys) - y


def build_coco_categories(taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    """Build COCO categories from taxonomy."""
    categories: list[dict[str, Any]] = []
    if not taxonomy:
        return categories

    classes = taxonomy.get("classes", [])
    for idx, cls in enumerate(classes):
        categories.append({
            "id": idx + 1,
            "name": cls.get("id", cls.get("name", f"class_{idx}")),
            "supercategory": cls.get("supercategory", "object"),
        })
    return categories


def get_category_id_map(taxonomy: dict[str, Any]) -> dict[str, int]:
    """Map class_id to COCO category ID."""
    category_map: dict[str, int] = {}
    if not taxonomy:
        return category_map

    classes = taxonomy.get("classes", [])
    for idx, cls in enumerate(classes):
        class_id = cls.get("id", cls.get("name", f"class_{idx}"))
        category_map[class_id] = idx + 1
    return category_map


def convert_2d_annotations_to_coco(
    annotations_2d: list[dict[str, Any]],
    frames_data: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    scene: Scene,
    camera_id: str,
) -> dict[str, Any]:
    """Convert 2D annotations for a specific camera to COCO format."""
    camera_annotations = [
        ann for ann in annotations_2d if ann.get("camera_id") == camera_id
    ]

    category_map = get_category_id_map(taxonomy)
    categories = build_coco_categories(taxonomy)

    unique_class_ids = set(ann.get("class_id", "unknown") for ann in camera_annotations)
    next_cat_id = len(categories) + 1
    for class_id in unique_class_ids:
        if class_id not in category_map:
            category_map[class_id] = next_cat_id
            categories.append({
                "id": next_cat_id,
                "name": str(class_id),
                "supercategory": "object",
            })
            next_cat_id += 1

    images: list[dict[str, Any]] = []
    frame_id_to_coco_id: dict[int, int] = {}

    for frame in frames_data:
        frame_index = frame["frame_index"]
        file_paths = frame.get("file_paths", {})
        camera_files = file_paths.get("cameras", {})
        camera_file = camera_files.get(camera_id, f"{frame_index:06d}.jpg")

        width, height = 1920, 1080
        if scene.calibration:
            lidar_to_cameras = scene.calibration.get("lidar_to_cameras", {})
            camera_calib = lidar_to_cameras.get(camera_id, {})
            intrinsic = camera_calib.get("intrinsic", {})
            if "cx" in intrinsic and "cy" in intrinsic:
                width = int(intrinsic.get("cx", 960) * 2)
                height = int(intrinsic.get("cy", 540) * 2)

        coco_image_id = frame_index + 1
        frame_id_to_coco_id[frame_index] = coco_image_id

        images.append({
            "id": coco_image_id,
            "file_name": camera_file,
            "width": width,
            "height": height,
            "frame_index": frame_index,
            "timestamp": frame.get("timestamp", 0.0),
        })

    coco_annotations: list[dict[str, Any]] = []
    for idx, ann in enumerate(camera_annotations):
        frame_index = ann.get("frame_index")
        if frame_index is None:
            continue

        coco_image_id = frame_id_to_coco_id.get(frame_index)
        if coco_image_id is None:
            continue

        class_id = ann.get("class_id", "unknown")
        category_id = category_map.get(class_id)
        if category_id is None:
            category_id = 1

        data = ann.get("data") or {}
        ann_type = ann.get("type", "box2d")
        x = y = width = height = 0.0
        segmentation = None
        extra_fields: dict[str, Any] = {}

        if ann_type in ("box2d", "box", "rectangle"):
            bbox_src = data.get("bbox", data)
            x = float(bbox_src.get("x", 0))
            y = float(bbox_src.get("y", 0))
            width = float(bbox_src.get("width", 0))
            height = float(bbox_src.get("height", 0))

        elif ann_type in ("rotated_box", "rotated_rectangle"):
            cx = float(data.get("cx", data.get("x", 0)))
            cy = float(data.get("cy", data.get("y", 0)))
            w = float(data.get("width", 0))
            h = float(data.get("height", 0))
            angle = float(data.get("angle", data.get("rotation", 0)))
            hw, hh = w / 2, h / 2
            cos_a = abs(math.cos(math.radians(angle)))
            sin_a = abs(math.sin(math.radians(angle)))
            dx = hw * cos_a + hh * sin_a
            dy = hw * sin_a + hh * cos_a
            x, y = cx - dx, cy - dy
            width, height = dx * 2, dy * 2
            extra_fields["rotated_box"] = {
                "cx": cx,
                "cy": cy,
                "width": w,
                "height": h,
                "angle": angle,
            }

        elif ann_type == "ellipse":
            cx = float(data.get("cx", data.get("x", 0)))
            cy = float(data.get("cy", data.get("y", 0)))
            rx = float(data["rx"]) if "rx" in data else float(data.get("width", 0)) / 2
            ry = float(data["ry"]) if "ry" in data else float(data.get("height", 0)) / 2
            x, y = cx - rx, cy - ry
            width, height = rx * 2, ry * 2
            extra_fields["ellipse"] = {"cx": cx, "cy": cy, "rx": rx, "ry": ry}

        elif ann_type in ("polygon", "semantic_segment"):
            coords = _pts_to_coords(data.get("polygon", data.get("points", [])))
            if not coords:
                continue
            x, y, width, height = _bbox_from_coords(coords)
            seg_flat: list[float] = []
            for px, py in coords:
                seg_flat.extend([px, py])
            segmentation = [seg_flat]
            extra_fields["polygon"] = [[px, py] for px, py in coords]

        elif ann_type in ("polyline", "line", "bezier"):
            coords = _pts_to_coords(data.get("points", []))
            if not coords:
                continue
            x, y, width, height = _bbox_from_coords(coords)
            segmentation = None
            extra_fields["polyline"] = [[px, py] for px, py in coords]

        elif ann_type in ("keypoints", "points"):
            kp_dict = data.get("keypoints", {})
            if kp_dict:
                coords = [
                    (float(v.get("x", 0)), float(v.get("y", 0)))
                    for v in kp_dict.values()
                    if isinstance(v, dict) and v.get("visibility", 2) > 0
                ]
                kp_flat: list[float] = []
                for name, v in kp_dict.items():
                    kp_flat.extend(
                        [float(v.get("x", 0)), float(v.get("y", 0)), int(v.get("visibility", 2))]
                    )
                extra_fields["keypoints"] = kp_flat
                extra_fields["keypoint_names"] = list(kp_dict.keys())
            else:
                coords = _pts_to_coords(data.get("points", []))
                extra_fields["keypoints"] = [v for px, py in coords for v in (px, py, 2)]
            if not coords:
                continue
            x, y, width, height = _bbox_from_coords(coords)
            extra_fields["num_keypoints"] = len(coords)

        elif ann_type in ("segmentation_2d", "mask"):
            all_coords: list[tuple[float, float]] = []
            seg_polys: list[list[float]] = []
            for poly in data.get("polygons", []):
                c = _pts_to_coords(poly)
                if c:
                    all_coords.extend(c)
                    seg_flat = []
                    for px, py in c:
                        seg_flat.extend([px, py])
                    seg_polys.append(seg_flat)
            if all_coords:
                x, y, width, height = _bbox_from_coords(all_coords)
                segmentation = seg_polys if seg_polys else None
            if "mask_url" in data:
                extra_fields["mask_url"] = data["mask_url"]

        else:
            bbox_src = data.get("bbox", data)
            x = float(bbox_src.get("x", 0)) if isinstance(bbox_src, dict) else 0.0
            y = float(bbox_src.get("y", 0)) if isinstance(bbox_src, dict) else 0.0
            width = float(bbox_src.get("width", 0)) if isinstance(bbox_src, dict) else 0.0
            height = float(bbox_src.get("height", 0)) if isinstance(bbox_src, dict) else 0.0

        area = width * height

        coco_ann: dict[str, Any] = {
            "id": idx + 1,
            "image_id": coco_image_id,
            "category_id": category_id,
            "class": class_id,
            "type": ann_type,
            "bbox": [x, y, width, height],
            "area": area,
            "iscrowd": 0,
            "attributes": ann.get("attributes", {}),
            "track_id": ann.get("track_id"),
            "source": ann.get("source", "manual"),
        }

        if segmentation:
            coco_ann["segmentation"] = segmentation

        coco_ann.update(extra_fields)
        coco_annotations.append(coco_ann)

    return {
        "info": {
            "description": f"Annotations for camera: {camera_id}",
            "version": "1.0",
            "year": datetime.now(UTC).year,
            "contributor": "CheryGT Export",
            "date_created": datetime.now(UTC).isoformat(),
            "scene_id": str(scene.id),
            "scene_name": scene.name,
        },
        "images": images,
        "annotations": coco_annotations,
        "categories": categories,
    }


def convert_3d_annotations_to_coco(
    annotations_3d: list[dict[str, Any]],
    frames_data: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    scene: Scene,
) -> dict[str, Any]:
    """Convert 3D LiDAR annotations to COCO-like format."""
    category_map = get_category_id_map(taxonomy)
    categories = build_coco_categories(taxonomy)

    unique_class_ids = set(ann.get("class_id", "unknown") for ann in annotations_3d)
    next_cat_id = len(categories) + 1
    for class_id in unique_class_ids:
        if class_id not in category_map:
            category_map[class_id] = next_cat_id
            categories.append({
                "id": next_cat_id,
                "name": str(class_id),
                "supercategory": "object",
            })
            next_cat_id += 1

    frames: list[dict[str, Any]] = []

    for frame in frames_data:
        frame_index = frame["frame_index"]
        file_paths = frame.get("file_paths", {})
        lidar_file = file_paths.get("lidar", f"{frame_index:06d}.pcd")

        frames.append({
            "id": frame_index,
            "file_name": lidar_file,
            "timestamp": frame.get("timestamp", 0.0),
            "ego_pose": frame.get("ego_pose"),
        })

    coco_annotations: list[dict[str, Any]] = []
    for idx, ann in enumerate(annotations_3d):
        frame_index = ann.get("frame_index", 0)

        class_id = ann.get("class_id", "unknown")
        category_id = category_map.get(class_id)
        if category_id is None:
            category_id = 1

        position = ann.get("position", {})
        dimensions = ann.get("dimensions", {})
        rotation = ann.get("rotation", {})

        coco_ann = {
            "id": idx + 1,
            "frame_id": frame_index,
            "category_id": category_id,
            "class": class_id,
            "cuboid_3d": {
                "position": {
                    "x": position.get("x", 0),
                    "y": position.get("y", 0),
                    "z": position.get("z", 0),
                },
                "dimensions": {
                    "length": dimensions.get("length", 0),
                    "width": dimensions.get("width", 0),
                    "height": dimensions.get("height", 0),
                },
                "rotation": {
                    "yaw": rotation.get("yaw", 0),
                    "pitch": rotation.get("pitch", 0),
                    "roll": rotation.get("roll", 0),
                },
            },
            "attributes": ann.get("attributes", {}),
            "track_id": ann.get("track_id"),
            "source": ann.get("source", "manual"),
            "confidence": ann.get("confidence", 1.0),
        }

        coco_annotations.append(coco_ann)

    return {
        "info": {
            "description": "LiDAR 3D Annotations",
            "version": "1.0",
            "year": datetime.now(UTC).year,
            "contributor": "CheryGT Export",
            "date_created": datetime.now(UTC).isoformat(),
            "scene_id": str(scene.id),
            "scene_name": scene.name,
            "coordinate_system": "lidar",
        },
        "frames": frames,
        "annotations": coco_annotations,
        "categories": categories,
    }


def convert_fusion_annotations_to_coco(
    annotations_fusion: list[dict[str, Any]],
    frames_data: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    scene: Scene,
) -> dict[str, Any]:
    """Convert Fusion annotations (3D + 2D projections) to COCO-like format."""
    category_map = get_category_id_map(taxonomy)
    categories = build_coco_categories(taxonomy)

    unique_class_ids = set(ann.get("class_id", "unknown") for ann in annotations_fusion)
    next_cat_id = len(categories) + 1
    for class_id in unique_class_ids:
        if class_id not in category_map:
            category_map[class_id] = next_cat_id
            categories.append({
                "id": next_cat_id,
                "name": str(class_id),
                "supercategory": "object",
            })
            next_cat_id += 1

    frames: list[dict[str, Any]] = []
    for frame in frames_data:
        frame_index = frame["frame_index"]
        file_paths = frame.get("file_paths", {})

        frames.append({
            "id": frame_index,
            "lidar_file": file_paths.get("lidar", f"{frame_index:06d}.pcd"),
            "camera_files": file_paths.get("cameras", {}),
            "timestamp": frame.get("timestamp", 0.0),
            "ego_pose": frame.get("ego_pose"),
        })

    coco_annotations: list[dict[str, Any]] = []
    for idx, ann in enumerate(annotations_fusion):
        frame_index = ann.get("frame_index", 0)

        class_id = ann.get("class_id", "unknown")
        category_id = category_map.get(class_id)
        if category_id is None:
            category_id = 1

        cuboid_3d = ann.get("cuboid_3d", {})

        coco_ann = {
            "id": idx + 1,
            "frame_id": frame_index,
            "category_id": category_id,
            "class": class_id,
            "cuboid_3d": cuboid_3d,
            "camera_projections": ann.get("camera_projections", {}),
            "attributes": ann.get("attributes", {}),
            "track_id": ann.get("track_id"),
            "source": ann.get("source", "manual"),
        }

        coco_annotations.append(coco_ann)

    return {
        "info": {
            "description": "Fusion Annotations (3D + 2D projections)",
            "version": "1.0",
            "year": datetime.now(UTC).year,
            "contributor": "CheryGT Export",
            "date_created": datetime.now(UTC).isoformat(),
            "scene_id": str(scene.id),
            "scene_name": scene.name,
        },
        "frames": frames,
        "annotations": coco_annotations,
        "categories": categories,
    }


def get_cameras_from_annotations(annotations_2d: list[dict[str, Any]]) -> list[str]:
    """Extract unique camera IDs from 2D annotations."""
    cameras: set[str] = set()
    for ann in annotations_2d:
        camera_id = ann.get("camera_id")
        if camera_id:
            cameras.add(camera_id)
    return sorted(list(cameras))


def add_sensor_annotations_to_zip(
    zf: zipfile.ZipFile,
    annotations: dict[str, list[dict[str, Any]]],
    frames_data: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    scene: Scene,
    prefix: str = "annotations",
) -> dict[str, int]:
    """Add per-sensor COCO format annotation files to the ZIP archive.

    Creates:
    - annotations/lidar.json for 3D cuboid annotations
    - annotations/{camera_id}.json for each camera's 2D annotations
    - annotations/fusion.json for fusion annotations
    - annotations/lidar_4d.json for 4D annotations

    Returns dict with counts per sensor.
    """
    counts: dict[str, int] = {}

    cuboids_3d = annotations.get("cuboids_3d", [])
    if cuboids_3d:
        coco_lidar = convert_3d_annotations_to_coco(
            cuboids_3d, frames_data, taxonomy, scene
        )
        zf.writestr(f"{prefix}/lidar.json", json.dumps(coco_lidar, indent=2))
        counts["lidar"] = len(cuboids_3d)

    boxes_2d = annotations.get("boxes_2d", [])
    tracks_2d = annotations.get("tracks_2d", [])
    if boxes_2d:
        cameras = get_cameras_from_annotations(boxes_2d)
        for camera_id in cameras:
            camera_annotations = [
                ann for ann in boxes_2d if ann.get("camera_id") == camera_id
            ]
            if camera_annotations:
                coco_camera = convert_2d_annotations_to_coco(
                    camera_annotations, frames_data, taxonomy, scene, camera_id
                )
                coco_camera["tracks"] = [
                    tr for tr in tracks_2d if tr.get("camera_id") == camera_id
                ]
                safe_camera_id = camera_id.replace("/", "_").replace("\\", "_")
                zf.writestr(
                    f"{prefix}/{safe_camera_id}.json", json.dumps(coco_camera, indent=2)
                )
                counts[camera_id] = len(camera_annotations)

    annotations_fusion = annotations.get("annotations_fusion", [])
    if annotations_fusion:
        coco_fusion = convert_fusion_annotations_to_coco(
            annotations_fusion, frames_data, taxonomy, scene
        )
        zf.writestr(f"{prefix}/fusion.json", json.dumps(coco_fusion, indent=2))
        counts["fusion"] = len(annotations_fusion)

    annotations_4d = annotations.get("annotations_4d", [])
    if annotations_4d:
        coco_4d = {
            "info": {
                "description": "4D Annotations (temporal tracking)",
                "version": "1.0",
                "year": datetime.now(UTC).year,
                "contributor": "CheryGT Export",
                "date_created": datetime.now(UTC).isoformat(),
                "scene_id": str(scene.id),
                "scene_name": scene.name,
            },
            "annotations": annotations_4d,
            "categories": build_coco_categories(taxonomy),
        }
        zf.writestr(f"{prefix}/lidar_4d.json", json.dumps(coco_4d, indent=2))
        counts["lidar_4d"] = len(annotations_4d)

    return counts
