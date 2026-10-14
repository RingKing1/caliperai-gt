"""Parsers for external annotation formats (COCO, KITTI, CVAT, CaliperGT)."""
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


from app.models.models import (
    AnnotationSource,
    Scene,
    Task,
    TaxonomyAnnotationMode,
)
from app.services.dataset_import.constants import (
    FUSION_3D_TYPES,
    LIDAR_SENSOR_PATTERNS,
    ONLY_2D_TYPES,
)

from app.services.dataset_import.taxonomy import map_source_class_to_taxonomy
def detect_annotation_mode_from_data(
    annotation_data: Dict[str, Any],
    sensor_name: Optional[str] = None,
) -> str:
    """
    Smart auto-detection of annotation mode based on annotation data.
    
    Returns:
        "fusion_3d" if the data contains 3D information (cuboids, 3D segmentation)
        "2d_only" if the data is pure 2D without 3D association
    """
    has_3d_position = any(key in annotation_data for key in [
        "position_x", "position_y", "position_z",
        "center", "position", "location"
    ])
    
    has_3d_dimensions = any(key in annotation_data for key in [
        "dimension_length", "dimension_width", "dimension_height",
        "dimensions", "size"
    ])
    
    has_rotation = any(key in annotation_data for key in [
        "rotation_yaw", "rotation_pitch", "rotation_roll",
        "rotation", "yaw"
    ])
    
    ann_type = annotation_data.get("type", "").lower()
    if ann_type in FUSION_3D_TYPES:
        return TaxonomyAnnotationMode.FUSION_3D.value
    
    if ann_type in ONLY_2D_TYPES and not has_3d_position and not has_3d_dimensions:
        return TaxonomyAnnotationMode.ONLY_2D.value
    
    if sensor_name:
        sensor_lower = sensor_name.lower()
        if any(pattern in sensor_lower for pattern in LIDAR_SENSOR_PATTERNS):
            return TaxonomyAnnotationMode.FUSION_3D.value
    
    if has_3d_position and has_3d_dimensions:
        return TaxonomyAnnotationMode.FUSION_3D.value
    
    return TaxonomyAnnotationMode.ONLY_2D.value


def detect_annotation_mode_from_file(
    file_content: Dict[str, Any],
    file_name: str,
) -> str:
    """
    Detect annotation mode from a file's structure and name.
    
    Returns:
        "fusion_3d" for 3D annotation files
        "2d_only" for pure 2D annotation files
    """
    sensor_name = file_name.replace('.json', '').split('/')[-1].lower()
    
    if any(pattern in sensor_name for pattern in LIDAR_SENSOR_PATTERNS):
        return TaxonomyAnnotationMode.FUSION_3D.value
    
    has_frames = "frames" in file_content
    has_images = "images" in file_content
    
    if has_frames and not has_images:
        return TaxonomyAnnotationMode.FUSION_3D.value
    
    annotations = file_content.get("annotations", [])
    if annotations:
        sample_ann = annotations[0] if isinstance(annotations, list) else annotations
        if isinstance(sample_ann, dict):
            if any(key in sample_ann for key in ["cuboid_3d", "position_3d", "dimensions_3d"]):
                return TaxonomyAnnotationMode.FUSION_3D.value
    
    return TaxonomyAnnotationMode.ONLY_2D.value


def parse_calipergt_2d_annotations(
    coco_data: dict,
    camera_id: str,
    frame_id_map: Dict[int, UUID],
    taxonomy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Parse CaliperGT export format 2D annotations.

    CaliperGT format::

        {
            "categories": {
                "label": {
                    "labels": [{"name": "car", ...}, ...],
                    "attributes": [...]
                }
            },
            "items": [
                {
                    "id": "frame_basename",
                    "annotations": [
                        {"id": 0, "type": "bbox", "label_id": 0, "bbox": [x,y,w,h], "attributes": {...}}
                    ],
                    "attr": {"frame": 0}
                }
            ]
        }
    """
    annotations_to_create = []

    label_map: Dict[int, str] = {}
    labels = coco_data.get("categories", {}).get("label", {}).get("labels", [])
    for idx, label in enumerate(labels):
        label_name = label.get("name")
        if label_name:
            label_map[idx] = label_name
        else:
            label_map[idx] = f"unknown_class_{idx}"

    for item in coco_data.get("items", []):
        attr = item.get("attr", {})
        frame_index = attr.get("frame")
        if frame_index is None:
            try:
                frame_index = int(str(item.get("id", "0")).split(".")[0].lstrip("0") or "0")
            except (ValueError, TypeError):
                continue

        frame_id = frame_id_map.get(frame_index)
        if frame_id is None:
            continue

        for ann in item.get("annotations", []):
            if ann.get("type") != "bbox":
                continue

            bbox = ann.get("bbox", [0, 0, 0, 0])
            if len(bbox) < 4:
                continue

            label_id = ann.get("label_id", 0)
            source_class_name = label_map.get(label_id)
            if not source_class_name:
                source_class_name = f"unknown_class_{label_id}"
            class_id = map_source_class_to_taxonomy(source_class_name, taxonomy) if taxonomy else source_class_name

            annotations_to_create.append({
                "type": "2d",
                "frame_index": frame_index,
                "frame_id": frame_id,
                "camera_id": camera_id,
                "class_id": class_id,
                "bbox_x": bbox[0],
                "bbox_y": bbox[1],
                "bbox_width": bbox[2],
                "bbox_height": bbox[3],
                "attributes": {k: v for k, v in ann.get("attributes", {}).items()
                               if k not in ("uuid", "rotation")},
                "source": AnnotationSource.AUTO.value,
                "confidence": ann.get("attributes", {}).get("score", 1.0),
                "track_id": ann.get("attributes", {}).get("track_id"),
            })

    return annotations_to_create


def parse_coco_2d_annotations(
    coco_data: dict, 
    camera_id: str,
    frame_id_map: Dict[int, UUID],
    taxonomy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Parse COCO format 2D annotations for a specific camera.
    
    COCO format structure:
    {
        "images": [{"id": 1, "file_name": "000001.jpg", "width": 1920, "height": 1080}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [x, y, w, h]}],
        "categories": [{"id": 1, "name": "car"}]
    }
    """
    annotations_to_create = []
    
    category_map = {}
    for cat in coco_data.get("categories", []):
        cat_id = cat.get("id")
        cat_name = cat.get("name", "")
        if cat_id is not None and cat_name:
            category_map[cat_id] = cat_name
            category_map[str(cat_id)] = cat_name
            if isinstance(cat_id, str):
                try:
                    category_map[int(cat_id)] = cat_name
                except ValueError:
                    pass
    
    image_to_frame = {}
    for img in coco_data.get("images", []):
        frame_index = img.get("frame_index")
        if frame_index is None:
            file_name = img.get("file_name", "")
            try:
                frame_index = int(file_name.split('.')[0].lstrip('0') or '0')
            except ValueError:
                frame_index = img["id"]
        image_to_frame[img["id"]] = frame_index
    
    for ann in coco_data.get("annotations", []):
        image_id = ann["image_id"]
        frame_index = image_to_frame.get(image_id)
        if frame_index is None:
            continue
        
        frame_id = frame_id_map.get(frame_index)
        if frame_id is None:
            continue
            
        bbox = ann.get("bbox", [0, 0, 0, 0])
        
        ann_type = ann.get("type", "").lower()

        polyline_points = None
        raw_polyline = ann.get("polyline")
        if ann_type in ("polyline", "line", "bezier") and raw_polyline:
            polyline_points = [{"x": p[0], "y": p[1]} for p in raw_polyline if len(p) >= 2]
        elif ann_type in ("polyline", "line", "bezier"):
            seg = ann.get("segmentation")
            if seg and isinstance(seg, list) and seg[0]:
                flat = seg[0]
                polyline_points = [
                    {"x": flat[i], "y": flat[i+1]}
                    for i in range(0, len(flat) - 1, 2)
                ]

        polygon_points = None
        if ann_type not in ("polyline", "line", "bezier"):
            segmentation = ann.get("segmentation")
            has_polygon = segmentation and isinstance(segmentation, list) and len(segmentation) > 0
            if has_polygon and isinstance(segmentation[0], list):
                polygon_points = segmentation[0]

        ellipse_data = ann.get("ellipse") if ann_type == "ellipse" else None

        rotated_box_data = ann.get("rotated_box") if ann_type in ("rotated_box", "rotated_rectangle") else None

        keypoints_flat = ann.get("keypoints") if ann_type in ("keypoints", "points") else None
        keypoint_names = ann.get("keypoint_names", []) if keypoints_flat else []
        
        cat_id = ann.get("category_id")
        source_class_name = category_map.get(cat_id) or category_map.get(str(cat_id) if cat_id else None)
        if not source_class_name:
            if cat_id is not None:
                if isinstance(cat_id, str) and not cat_id.isdigit():
                    source_class_name = cat_id
                else:
                    source_class_name = f"unknown_class_{cat_id}"
            else:
                source_class_name = "unknown"
        class_id = map_source_class_to_taxonomy(source_class_name, taxonomy) if taxonomy else source_class_name
        
        annotation_dict = {
            "type": "2d",
            "ann_type": ann_type,
            "frame_index": frame_index,
            "frame_id": frame_id,
            "camera_id": camera_id,
            "class_id": class_id,
            "bbox_x": bbox[0],
            "bbox_y": bbox[1],
            "bbox_width": bbox[2],
            "bbox_height": bbox[3],
            "attributes": ann.get("attributes", {}),
            "source": AnnotationSource.AUTO.value,
            "confidence": ann.get("score", 1.0),
            "track_id": ann.get("track_id"),
        }
        
        if polyline_points:
            annotation_dict["polyline_points"] = polyline_points
        elif polygon_points:
            annotation_dict["polygon_points"] = polygon_points
        if ellipse_data:
            annotation_dict["ellipse_data"] = ellipse_data
        if rotated_box_data:
            annotation_dict["rotated_box_data"] = rotated_box_data
        if keypoints_flat:
            annotation_dict["keypoints_flat"] = keypoints_flat
            annotation_dict["keypoint_names"] = keypoint_names
        
        annotations_to_create.append(annotation_dict)
    
    return annotations_to_create


def parse_coco_3d_annotations(
    coco_data: dict,
    frame_id_map: Dict[int, UUID],
    taxonomy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Parse COCO-like 3D annotations for LiDAR.
    
    Expected format:
    {
        "frames": [{"id": 0, "file_name": "000000.pcd", "timestamp": 0.0}],
        "annotations": [
            {
                "id": 1, 
                "frame_id": 0, 
                "category_id": 1, 
                "cuboid_3d": {
                    "position": {"x": 10.0, "y": 5.0, "z": 0.5},
                    "dimensions": {"length": 4.5, "width": 2.0, "height": 1.5},
                    "rotation": {"yaw": 0.1, "pitch": 0.0, "roll": 0.0}
                }
            }
        ],
        "categories": [{"id": 1, "name": "car"}]
    }
    """
    annotations_to_create = []
    
    category_map = {cat["id"]: cat["name"] for cat in coco_data.get("categories", [])}

    json_frame_id_to_index: Dict[Any, int] = {}
    for frame in coco_data.get("frames", []):
        json_id = frame.get("id")
        if json_id is None:
            continue
        frame_index_val = frame.get("frame_index")
        if frame_index_val is None:
            file_name = frame.get("file_name", "")
            try:
                frame_index_val = int(file_name.split(".")[0].lstrip("0") or "0")
            except ValueError:
                frame_index_val = json_id
        json_frame_id_to_index[json_id] = int(frame_index_val)

    uuid_to_frame_index: Dict[str, int] = {
        str(uuid_val): idx for idx, uuid_val in frame_id_map.items()
    }

    for ann in coco_data.get("annotations", []):
        raw_frame_ref = ann.get("frame_id", ann.get("frame_index", 0))

        if json_frame_id_to_index and raw_frame_ref in json_frame_id_to_index:
            frame_index = json_frame_id_to_index[raw_frame_ref]
        elif isinstance(raw_frame_ref, str) and raw_frame_ref in uuid_to_frame_index:
            frame_index = uuid_to_frame_index[raw_frame_ref]
        else:
            try:
                frame_index = int(raw_frame_ref)
            except (TypeError, ValueError):
                continue
        
        cuboid = ann.get("cuboid_3d", {})
        position = cuboid.get("position", {})
        dimensions = cuboid.get("dimensions", {})
        rotation = cuboid.get("rotation", {})
        
        if not position or not dimensions:
            continue
        
        source_class_name = category_map.get(ann.get("category_id"), f"class_{ann.get('category_id', 0)}")
        class_id = map_source_class_to_taxonomy(source_class_name, taxonomy) if taxonomy else source_class_name
        
        annotations_to_create.append({
            "type": "3d",
            "frame_index": frame_index,
            "class_id": class_id,
            "position_x": position.get("x", 0),
            "position_y": position.get("y", 0),
            "position_z": position.get("z", 0),
            "dimension_length": dimensions.get("length", 0),
            "dimension_width": dimensions.get("width", 0),
            "dimension_height": dimensions.get("height", 0),
            "rotation_yaw": rotation.get("yaw", 0),
            "rotation_pitch": rotation.get("pitch", 0),
            "rotation_roll": rotation.get("roll", 0),
            "attributes": ann.get("attributes", {}),
            "source": AnnotationSource.AUTO.value,
            "confidence": ann.get("confidence", ann.get("score", 1.0)),
            "track_id": ann.get("track_id"),
        })
    
    return annotations_to_create


def parse_coco_annotations(coco_data: dict, scene: Scene, task: Task) -> List[Dict[str, Any]]:
    """Parse COCO format annotations and convert to internal format (legacy function).
    
    COCO format structure:
    {
        "images": [{"id": 1, "file_name": "000001.jpg", "width": 1920, "height": 1080}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [x, y, w, h]}],
        "categories": [{"id": 1, "name": "car"}]
    }
    """
    annotations_to_create = []
    
    category_map = {cat["id"]: cat["name"] for cat in coco_data.get("categories", [])}
    
    image_map = {}
    for img in coco_data.get("images", []):
        file_name = img["file_name"]
        try:
            frame_idx = int(file_name.split('.')[0].lstrip('0') or '0')
        except ValueError:
            frame_idx = img["id"]
        image_map[img["id"]] = frame_idx
    
    for ann in coco_data.get("annotations", []):
        image_id = ann["image_id"]
        if image_id not in image_map:
            continue
            
        frame_index = image_map[image_id]
        bbox = ann["bbox"]
        
        annotations_to_create.append({
            "frame_index": frame_index,
            "class_id": category_map.get(ann["category_id"], f"class_{ann['category_id']}"),
            "bbox_x": bbox[0],
            "bbox_y": bbox[1],
            "bbox_width": bbox[2],
            "bbox_height": bbox[3],
            "attributes": {},
            "source": AnnotationSource.AUTO_INTERPOLATED.value,
            "confidence": ann.get("score", 1.0),
            "camera_id": ann.get("camera_id", "camera_front")
        })
    
    return annotations_to_create


def parse_kitti_annotations(
    kitti_lines: List[str], 
    scene: Scene, 
    task: Task,
    taxonomy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Parse KITTI format annotations and convert to internal format.
    
    KITTI format (one line per object):
    Type Truncated Occluded Alpha Bbox_2D[4] Dimensions[3] Location[3] Rotation_y Score
    Example: Car 0.00 0 -1.57 599.41 156.40 629.75 189.25 1.50 1.60 3.70 -0.30 1.65 46.70 -1.53
    """
    annotations_to_create = []
    
    for line in kitti_lines:
        parts = line.strip().split()
        if len(parts) < 15:
            continue
            
        class_name = parts[0]
        truncated = float(parts[1])
        occluded = int(parts[2])
        alpha = float(parts[3])
        
        bbox_2d = [float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])]
        
        height = float(parts[8])
        width = float(parts[9])
        length = float(parts[10])
        
        location_x = float(parts[11])
        location_y = float(parts[12])
        location_z = float(parts[13])
        
        rotation_y = float(parts[14])
        
        score = float(parts[15]) if len(parts) > 15 else 1.0
        
        class_id = map_source_class_to_taxonomy(class_name, taxonomy) if taxonomy else class_name.lower()
        
        annotations_to_create.append({
            "frame_index": 0,
            "class_id": class_id,
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
        })
    
    return annotations_to_create


def parse_cvat_xml_annotations(xml_content: str, frame_id_map: Dict[int, UUID]) -> List[Dict[str, Any]]:
    """Parse CVAT XML format annotations with 3D attributes into per-frame 3D boxes.
    
    CVAT exports 3D annotations with box elements containing position_3d, rotation_3d, 
    and dimensions_3d as attributes. This parser handles both image-based and track-based formats.
    
    Expected format:
    <annotations>
      <image id="0" name="0">
        <box label="Car" track_id="0" ...>
          <attribute name="position_3d">x,y,z</attribute>
          <attribute name="rotation_3d">rx,ry,rz</attribute>
          <attribute name="dimensions_3d">l,w,h</attribute>
        </box>
      </image>
    </annotations>
    
    Or track-based format:
    <annotations>
      <track id="0" label="Car">
        <box frame="0" ...>
          <attribute name="position_3d">x,y,z</attribute>
          ...
        </box>
      </track>
    </annotations>
    """
    import logging
    logger = logging.getLogger(__name__)
    
    annotations: List[Dict[str, Any]] = []

    def parse_3d_values(value_str: str) -> tuple:
        """Parse comma-separated 3D values like 'x,y,z' into tuple of floats."""
        try:
            parts = value_str.split(',')
            return tuple(float(p.strip()) for p in parts)
        except Exception as e:
            logger.warning(f"Failed to parse 3D values '{value_str}': {e}")
            return (0.0, 0.0, 0.0)

    def get_box_attributes(box_el: ET.Element) -> Dict[str, Any]:
        """Extract 3D attributes from a box element."""
        attrs = {}
        for attr_el in box_el.findall('attribute'):
            name = attr_el.get('name', '')
            value = attr_el.text or ''
            attrs[name] = value
        return attrs

    try:
        root = ET.fromstring(xml_content)
        logger.info(f"Parsing CVAT XML, root tag: {root.tag}")
    except ET.ParseError as e:
        logger.error(f"Failed to parse XML: {e}")
        return annotations

    images_found = 0
    boxes_found = 0
    for image_el in root.findall('.//image'):
        images_found += 1
        frame_index = 0
        image_id = image_el.get('id', '')
        image_name = image_el.get('name', '')
        
        try:
            if image_id and image_id.isdigit():
                frame_index = int(image_id)
            elif image_name:
                name_clean = image_name.split('.')[0]
                name_clean = ''.join(filter(str.isdigit, name_clean)) or '0'
                frame_index = int(name_clean.lstrip('0') or '0')
        except ValueError:
            frame_index = 0

        for box_el in image_el.findall('box'):
            boxes_found += 1
            label = box_el.get('label', 'unknown').lower()
            track_id = box_el.get('track_id', '')
            occluded = int(box_el.get('occluded', '0'))
            
            attrs = get_box_attributes(box_el)
            
            position_3d = attrs.get('position_3d', '0,0,0')
            rotation_3d = attrs.get('rotation_3d', '0,0,0')
            dimensions_3d = attrs.get('dimensions_3d', '1,1,1')
            
            px, py, pz = parse_3d_values(position_3d)
            rx, ry, rz = parse_3d_values(rotation_3d)
            dim_l, dim_w, dim_h = parse_3d_values(dimensions_3d)
            
            if 'dimensions_3d' not in attrs:
                logger.warning(f"Box {track_id} at frame {frame_index} missing dimensions_3d attribute")
                continue
            
            annotations.append({
                "frame_index": frame_index,
                "class_id": label,
                "position_x": px,
                "position_y": py,
                "position_z": pz,
                "dimension_length": dim_l,
                "dimension_width": dim_w,
                "dimension_height": dim_h,
                "rotation_yaw": rz,
                "rotation_pitch": ry,
                "rotation_roll": rx,
                "attributes": {
                    "occluded": occluded,
                    "track_id": track_id,
                    "det_id": attrs.get('det_id', ''),
                },
                "source": AnnotationSource.AUTO.value,
                "confidence": 1.0,
                "track_id": track_id if track_id else None,
            })
    
    logger.info(f"Found {images_found} images, {boxes_found} boxes, created {len(annotations)} annotations from image format")

    tracks_found = 0
    track_boxes_found = 0
    for track_el in root.findall('.//track'):
        tracks_found += 1
        label = track_el.get('label', 'unknown').lower()
        track_id = track_el.get('id', '')
        
        for box_el in track_el.findall('box'):
            track_boxes_found += 1
            frame_str = box_el.get('frame', '0')
            try:
                frame_index = int(frame_str)
            except ValueError:
                frame_index = 0
            
            occluded = int(box_el.get('occluded', '0'))
            outside = int(box_el.get('outside', '0'))
            
            if outside:
                continue
            
            attrs = get_box_attributes(box_el)
            
            position_3d = attrs.get('position_3d', '0,0,0')
            rotation_3d = attrs.get('rotation_3d', '0,0,0')
            dimensions_3d = attrs.get('dimensions_3d', '1,1,1')
            
            px, py, pz = parse_3d_values(position_3d)
            rx, ry, rz = parse_3d_values(rotation_3d)
            dim_l, dim_w, dim_h = parse_3d_values(dimensions_3d)
            
            if 'dimensions_3d' not in attrs:
                logger.warning(f"Track {track_id} box at frame {frame_index} missing dimensions_3d attribute")
                continue
            
            annotations.append({
                "frame_index": frame_index,
                "class_id": label,
                "position_x": px,
                "position_y": py,
                "position_z": pz,
                "dimension_length": dim_l,
                "dimension_width": dim_w,
                "dimension_height": dim_h,
                "rotation_yaw": rz,
                "rotation_pitch": ry,
                "rotation_roll": rx,
                "attributes": {
                    "occluded": occluded,
                    "track_id": track_id,
                    "det_id": attrs.get('det_id', ''),
                },
                "source": AnnotationSource.AUTO.value,
                "confidence": 1.0,
                "track_id": track_id if track_id else None,
            })
    
    logger.info(f"Found {tracks_found} tracks, {track_boxes_found} track boxes, total annotations: {len(annotations)}")
    return annotations


def parse_cvat_json_annotations(
    cvat_data: dict,
    frame_id_map: Dict[int, UUID],
    taxonomy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Parse CVAT JSON format 3D cuboid annotations.

    CVAT JSON structure (from auto-annotation export):
    {
        "version": "1.0",
        "tags": [],
        "shapes": [],
        "tracks": [
            {
                "frame": 0,
                "label": "truck",
                "shapes": [
                    {
                        "type": "cuboid",
                        "frame": 0,
                        "outside": false,
                        "points": [x, y, z, rx, ry, rz, length, width, height, 0, 0, 0, 0, 0, 0, 0]
                    }
                ]
            }
        ]
    }

    Points layout (16 values):
        [0:3]  position  x, y, z
        [3:6]  rotation  rx, ry, rz  (rz = yaw)
        [6:9]  dimensions  length, width, height
        [9:16] reserved / zeros
    """
    annotations: List[Dict[str, Any]] = []

    track_id_map_local: Dict[int, UUID] = {}

    for track_idx, track in enumerate(cvat_data.get("tracks", [])):
        label = track.get("label", "unknown").lower()
        class_id = map_source_class_to_taxonomy(label, taxonomy) if taxonomy else label

        if track_idx not in track_id_map_local:
            track_id_map_local[track_idx] = uuid4()
        track_uuid = track_id_map_local[track_idx]

        for shape in track.get("shapes", []):
            if shape.get("outside", False):
                continue

            if shape.get("type") != "cuboid":
                continue

            frame_index = shape.get("frame", 0)
            if frame_index not in frame_id_map:
                continue

            pts = shape.get("points", [])
            if len(pts) < 9:
                continue

            x, y, z = pts[0], pts[1], pts[2]
            rx, ry, rz = pts[3], pts[4], pts[5]
            width, length, height = pts[6], pts[7], pts[8]

            annotations.append({
                "type": "3d",
                "frame_index": frame_index,
                "class_id": class_id,
                "position_x": x,
                "position_y": y,
                "position_z": z,
                "dimension_length": length,
                "dimension_width": width,
                "dimension_height": height,
                "rotation_yaw": rz,
                "rotation_pitch": ry,
                "rotation_roll": rx,
                "attributes": shape.get("attributes", {}),
                "source": AnnotationSource.AUTO.value,
                "confidence": shape.get("confidence", 1.0),
                "track_id": str(track_uuid),
            })

    for shape in cvat_data.get("shapes", []):
        if shape.get("outside", False) or shape.get("type") != "cuboid":
            continue

        label = shape.get("label", "unknown").lower()
        class_id = map_source_class_to_taxonomy(label, taxonomy) if taxonomy else label
        frame_index = shape.get("frame", 0)
        if frame_index not in frame_id_map:
            continue

        pts = shape.get("points", [])
        if len(pts) < 9:
            continue

        x, y, z = pts[0], pts[1], pts[2]
        rx, ry, rz = pts[3], pts[4], pts[5]
        width, length, height = pts[6], pts[7], pts[8]

        annotations.append({
            "type": "3d",
            "frame_index": frame_index,
            "class_id": class_id,
            "position_x": x,
            "position_y": y,
            "position_z": z,
            "dimension_length": length,
            "dimension_width": width,
            "dimension_height": height,
            "rotation_yaw": rz,
            "rotation_pitch": ry,
            "rotation_roll": rx,
            "attributes": shape.get("attributes", {}),
            "source": AnnotationSource.AUTO.value,
            "confidence": shape.get("confidence", 1.0),
            "track_id": None,
        })

    return annotations


def parse_kitti_tracklet_annotations(xml_content: str, frame_id_map: Dict[int, UUID]) -> List[Dict[str, Any]]:
    """Parse KITTI tracklet_labels.xml annotations into per-frame 3D boxes.
    
    KITTI raw sequences provide 3D boxes in tracklet_labels.xml with one tracklet per object
    and per-frame poses. This converts each pose into an Annotation3D entry keyed by frame index.
    """
    annotations: List[Dict[str, Any]] = []

    def _get_float(el: Optional[ET.Element], tag: str, default: float = 0.0) -> float:
        try:
            text = el.find(tag).text if el is not None else None
            return float(text) if text is not None else default
        except Exception:
            return default

    def _get_int(el: Optional[ET.Element], tag: str, default: int = 0) -> int:
        try:
            text = el.find(tag).text if el is not None else None
            return int(text) if text is not None else default
        except Exception:
            return default

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return annotations

    for tracklet in root.findall('item'):
        class_name = (tracklet.findtext('objectType') or 'unknown').lower()
        height = _get_float(tracklet, 'h')
        width = _get_float(tracklet, 'w')
        length = _get_float(tracklet, 'l')
        first_frame = _get_int(tracklet, 'first_frame', 0)

        poses_el = tracklet.find('poses')
        if poses_el is None:
            continue

        for frame_offset, pose_el in enumerate(poses_el.findall('item')):
            frame_index = first_frame + frame_offset
            if frame_index not in frame_id_map:
                continue

            tx = _get_float(pose_el, 'tx')
            ty = _get_float(pose_el, 'ty')
            tz = _get_float(pose_el, 'tz')
            rx = _get_float(pose_el, 'rx')
            ry = _get_float(pose_el, 'ry')
            rz = _get_float(pose_el, 'rz')

            occlusion = _get_int(pose_el, 'occlusion', _get_int(pose_el, 'occlusion_kf', 0))
            truncation = _get_float(pose_el, 'truncation', 0.0)
            state = _get_int(pose_el, 'state', 0)

            annotations.append({
                "frame_index": frame_index,
                "class_id": class_name,
                "position_x": tx,
                "position_y": ty,
                "position_z": tz,
                "dimension_length": length,
                "dimension_width": width,
                "dimension_height": height,
                "rotation_yaw": rz,
                "rotation_pitch": ry,
                "rotation_roll": rx,
                "attributes": {
                    "truncated": truncation,
                    "occluded": occlusion,
                    "state": state,
                },
                "source": AnnotationSource.AUTO.value,
                "confidence": 1.0,
            })

    return annotations


def compute_annotation_fingerprint(frame_id: UUID, camera_id: str, bbox_x: float, bbox_y: float, bbox_w: float, bbox_h: float) -> str:
    """Compute a fingerprint for a 2D annotation for deduplication.
    
    Uses frame_id, camera_id, and rounded bbox coordinates to identify duplicates.
    Coordinates are rounded to handle minor floating point differences.
    """
    return f"{frame_id}:{camera_id}:{round(bbox_x, 1)}:{round(bbox_y, 1)}:{round(bbox_w, 1)}:{round(bbox_h, 1)}"


def compute_3d_annotation_fingerprint(frame_id: UUID, pos_x: float, pos_y: float, pos_z: float, dim_l: float, dim_w: float, dim_h: float) -> str:
    """Compute a fingerprint for a 3D annotation for deduplication."""
    return f"{frame_id}:{round(pos_x, 1)}:{round(pos_y, 1)}:{round(pos_z, 1)}:{round(dim_l, 1)}:{round(dim_w, 1)}:{round(dim_h, 1)}"


