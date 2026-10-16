"""Export service package.

Provides domain logic, serialization, and streaming bundle builders for
dataset, scene, and task exports in various formats (COCO, JSON, KITTI segmentation).
"""
from app.services.export.archive import (
    add_scene_data_to_zip,
    build_task_export_folder_name,
    resolve_storage_path,
)
from app.services.export.coco_converter import (
    add_sensor_annotations_to_zip,
    build_coco_categories,
    convert_2d_annotations_to_coco,
    convert_3d_annotations_to_coco,
    convert_fusion_annotations_to_coco,
    get_cameras_from_annotations,
    get_category_id_map,
)
from app.services.export.export_service import (
    ExportNotFoundError,
    export_dataset_bundle,
    export_scene_bundle,
    export_task_bundle,
    get_annotations_for_task,
    get_frames_metadata,
    get_scene_metadata,
)
from app.services.export.merge import (
    merge_overlapping_annotations,
)
from app.services.export.segmentation_exporter import (
    add_segmentation_kitti_to_zip,
    get_segmentation_taxonomy_classes,
)

__all__ = [
    "ExportNotFoundError",
    "export_task_bundle",
    "export_scene_bundle",
    "export_dataset_bundle",
    "get_annotations_for_task",
    "get_scene_metadata",
    "get_frames_metadata",
    "merge_overlapping_annotations",
    "resolve_storage_path",
    "add_scene_data_to_zip",
    "build_task_export_folder_name",
    "get_segmentation_taxonomy_classes",
    "add_segmentation_kitti_to_zip",
    "build_coco_categories",
    "get_category_id_map",
    "convert_2d_annotations_to_coco",
    "convert_3d_annotations_to_coco",
    "convert_fusion_annotations_to_coco",
    "get_cameras_from_annotations",
    "add_sensor_annotations_to_zip",
]
