"""Dataset & annotation import domain services.

Split out of the former god modules
``app/api/v1/endpoints/import_data.py`` (3k lines) and
``import_annotations.py`` (2.7k lines). Route handlers stay thin in the
endpoints package; parsing, discovery, taxonomy derivation, storage
mirroring and persistence live here.

Layout:
* constants           - paths and static sets/palettes
* schemas             - import request/response DTOs
* calibration         - calibration & ego-pose parsing
* naming              - smart scene/task naming, folder matching
* tasks               - import-time task creation/lookup
* discovery           - on-disk frame discovery / storage paths
* storage             - MinIO mirroring
* taxonomy            - class scanning and taxonomy derivation/merging
* scene_importer      - per-scene label files -> annotation rows
* scene_pipeline      - shared per-scene orchestration (upload + ZIP routes)
* annotation_parsers  - COCO/KITTI/CVAT/CaliperGT format parsers
* annotation_pipeline - ZIP annotation import pipeline
"""
from app.services.dataset_import.annotation_parsers import (
    compute_3d_annotation_fingerprint,
    compute_annotation_fingerprint,
    detect_annotation_mode_from_data,
    detect_annotation_mode_from_file,
    parse_calipergt_2d_annotations,
    parse_coco_2d_annotations,
    parse_coco_3d_annotations,
    parse_coco_annotations,
    parse_cvat_json_annotations,
    parse_cvat_xml_annotations,
    parse_kitti_annotations,
    parse_kitti_tracklet_annotations,
)
from app.services.dataset_import.annotation_pipeline import (
    build_empty_import_results,
    build_subzip_for_task_folder,
    extract_task_id_from_folder_name,
    merge_import_results,
    process_zip_annotations,
)
from app.services.dataset_import.calibration import (
    detect_ego_to_lidar_rotation,
    load_ego_poses,
    parse_calibration_file,
)
from app.services.dataset_import.constants import (
    AUTO_CLASS_COLORS,
    CLASS_COLOR_PALETTE,
    FUSION_3D_TYPES,
    GENERIC_FOLDER_NAMES,
    LIDAR_SENSOR_PATTERNS,
    ONLY_2D_TYPES,
    SEGMENTATION_ROOT,
    UPLOAD_DIR,
)
from app.services.dataset_import.discovery import discover_frames, get_storage_paths
from app.services.dataset_import.frame_rows import build_import_frame_rows
from app.services.dataset_import.naming import (
    generate_smart_scene_name,
    generate_smart_task_name,
    match_folder_to_task,
)
from app.services.dataset_import.pipeline_layout import (
    SUPPORTED_DATA_SUFFIXES,
    classify_scene_data_files,
    detect_scene_dirs,
    find_data_files,
    is_scene_folder,
)
from app.services.dataset_import.scene_importer import import_scene_annotations
from app.services.dataset_import.scene_pipeline import (
    UPLOAD_PIPELINE,
    ZIP_PIPELINE,
    SceneImportRequest,
    import_one_scene,
)
from app.services.dataset_import.schemas import (
    BrowseFolderResponse,
    DatasetMetadata,
    FolderItem,
    ImportProgress,
    ImportRequest,
    ImportResponse,
    RenamedScene,
    SceneConflict,
    SceneMetadata,
    SceneNameCheckRequest,
    SceneNameCheckResponse,
    SensorInfo,
)
from app.services.dataset_import.storage import (
    _mirror_scene_to_minio,
    schedule_scene_mirror,
)
from app.services.dataset_import.tasks import (
    frame_range_to_postgres,
    get_or_create_scene_import_task,
)
from app.services.dataset_import.taxonomy import (
    _read_segmentation_class_order,
    build_class_mapping,
    create_taxonomy_from_classes,
    derive_and_merge_taxonomy,
    derive_and_merge_taxonomy_for_scene,
    derive_taxonomy_from_annotations,
    ensure_segmentation_taxonomy,
    generate_random_color,
    map_class_to_taxonomy,
    map_source_class_to_taxonomy,
    scan_annotations_for_classes,
)

__all__ = [
    # constants
    "AUTO_CLASS_COLORS", "CLASS_COLOR_PALETTE", "FUSION_3D_TYPES",
    "GENERIC_FOLDER_NAMES", "LIDAR_SENSOR_PATTERNS", "ONLY_2D_TYPES",
    "SEGMENTATION_ROOT", "UPLOAD_DIR",
    # schemas
    "BrowseFolderResponse", "DatasetMetadata", "FolderItem", "ImportProgress",
    "ImportRequest", "ImportResponse", "RenamedScene", "SceneConflict",
    "SceneMetadata", "SceneNameCheckRequest", "SceneNameCheckResponse",
    "SensorInfo",
    # calibration / naming / tasks / discovery / storage
    "detect_ego_to_lidar_rotation", "load_ego_poses", "parse_calibration_file",
    "generate_smart_scene_name", "generate_smart_task_name", "match_folder_to_task",
    "frame_range_to_postgres", "get_or_create_scene_import_task",
    "discover_frames", "get_storage_paths", "_mirror_scene_to_minio",
    "schedule_scene_mirror", "build_import_frame_rows",
    "SUPPORTED_DATA_SUFFIXES", "classify_scene_data_files", "detect_scene_dirs",
    "find_data_files", "is_scene_folder",
    # taxonomy
    "_read_segmentation_class_order", "build_class_mapping",
    "create_taxonomy_from_classes", "derive_and_merge_taxonomy",
    "derive_and_merge_taxonomy_for_scene", "derive_taxonomy_from_annotations",
    "ensure_segmentation_taxonomy", "generate_random_color",
    "map_class_to_taxonomy", "map_source_class_to_taxonomy",
    "scan_annotations_for_classes",
    # scene / annotation importers
    "import_scene_annotations",
    "compute_3d_annotation_fingerprint", "compute_annotation_fingerprint",
    "detect_annotation_mode_from_data", "detect_annotation_mode_from_file",
    "parse_calipergt_2d_annotations", "parse_coco_2d_annotations",
    "parse_coco_3d_annotations", "parse_coco_annotations",
    "parse_cvat_json_annotations", "parse_cvat_xml_annotations",
    "parse_kitti_annotations", "parse_kitti_tracklet_annotations",
    "build_empty_import_results", "build_subzip_for_task_folder",
    "extract_task_id_from_folder_name", "merge_import_results",
    "process_zip_annotations",
    # per-scene orchestration (upload + ZIP shared loop)
    "SceneImportRequest", "UPLOAD_PIPELINE", "ZIP_PIPELINE",
    "import_one_scene",
]
