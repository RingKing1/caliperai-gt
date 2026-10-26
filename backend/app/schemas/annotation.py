"""Annotation API schemas across all modalities, filters and migrations."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import (
    AnnotationSource,
    AnnotationType,
    BaseSchema,
    TaskStatus,
    TimestampSchema,
)


class Point2D(BaseSchema):
    """2D point."""
    """2D point."""
    x: float
    y: float


class Point3D(BaseSchema):
    """3D point."""
    x: float
    y: float
    z: float


class BBox2D(BaseSchema):
    """2D bounding box."""
    x: float
    y: float
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)


class Dimensions3D(BaseSchema):
    """3D dimensions for cuboid."""
    length: float = Field(..., gt=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)


class Rotation3D(BaseSchema):
    """3D rotation (yaw, pitch, roll in radians)."""
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0


class CuboidData(BaseSchema):
    """3D cuboid annotation data (9 DoF)."""
    center: Point3D
    dimensions: Dimensions3D
    rotation: Rotation3D
    confidence: float = Field(default=1.0, ge=0, le=1)


class Box2DData(BaseSchema):
    """2D bounding box annotation data."""
    camera_id: str
    bbox: BBox2D


class PolylineData(BaseSchema):
    """Polyline annotation data."""
    camera_id: str
    points: list[list[float]]
    is_closed: bool = False
    bezier: bool = False

    @field_validator("points")
    @classmethod
    def validate_points(cls, v):
        if len(v) < 2:
            raise ValueError("Polyline must have at least 2 points")
        for point in v:
            if len(point) != 2:
                raise ValueError("Each point must have [x, y] coordinates")
        return v


class PolygonData(BaseSchema):
    """Polygon annotation data."""
    camera_id: str
    points: list[list[float]]

    @field_validator("points")
    @classmethod
    def validate_points(cls, v):
        if len(v) < 3:
            raise ValueError("Polygon must have at least 3 points")
        return v


class Keypoint(BaseSchema):
    """Single keypoint with visibility."""
    x: float
    y: float
    visibility: int = Field(default=2, ge=0, le=2)


class KeypointsData(BaseSchema):
    """Keypoints annotation data."""
    camera_id: str
    skeleton_id: str
    keypoints: dict[str, Keypoint]


class Segmentation3DData(BaseSchema):
    """3D semantic segmentation annotation data."""
    blob_url: str | None = None
    compression: str = "zlib"
    point_count: int = Field(..., gt=0)
    class_mapping: dict[str, str] = Field(default_factory=dict)


class Segmentation2DData(BaseSchema):
    """2D semantic segmentation annotation data."""
    camera_id: str
    mask_url: str | None = None
    polygons: list[list[list[float]]] | None = None


AnnotationData = (
    CuboidData
    | Box2DData
    | PolylineData
    | PolygonData
    | KeypointsData
    | Segmentation3DData
    | Segmentation2DData
)



class AnnotationBase(BaseSchema):
    track_id: UUID | None = None
    type: AnnotationType
    class_id: str
    data: dict[str, Any]
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: AnnotationSource = AnnotationSource.MANUAL
    taxonomy_id: UUID | None = None


class AnnotationCreate(AnnotationBase):
    task_id: UUID
    frame_id: UUID


class AnnotationUpdate(BaseSchema):
    track_id: UUID | None = None
    class_id: str | None = None
    data: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None


class AnnotationVerify(BaseSchema):
    """Verify an auto-annotation."""
    is_verified: bool = True
    modifications: dict[str, Any] | None = None


class AnnotationResponse(AnnotationBase, TimestampSchema):
    id: UUID
    task_id: UUID
    frame_id: UUID
    is_verified: bool
    verified_by: UUID | None = None
    verified_at: datetime | None = None



class BulkAnnotationCreate(BaseSchema):
    """Bulk create annotations."""
    annotations: list[AnnotationCreate]


class BulkAnnotationUpdate(BaseSchema):
    """Bulk update annotations."""
    updates: list[dict[str, Any]]


class BulkOperationResponse(BaseSchema):
    """Response for bulk operations."""
    success_count: int
    error_count: int
    errors: list[dict[str, Any]] = Field(default_factory=list)



class PaginationParams(BaseSchema):
    """Pagination parameters."""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class TaskFilters(BaseSchema):
    """Filter parameters for tasks."""
    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    scene_id: UUID | None = None
    priority_min: int | None = None
    priority_max: int | None = None


class AnnotationFilters(BaseSchema):
    """Filter parameters for annotations."""
    type: AnnotationType | None = None
    class_id: str | None = None
    source: AnnotationSource | None = None
    is_verified: bool | None = None
    track_id: UUID | None = None



class Point3D(BaseSchema):
    """3D point coordinates."""
    x: float
    y: float
    z: float


class Rotation3D(BaseSchema):
    """3D rotation (Euler angles)."""
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0


class Dimensions3D(BaseSchema):
    """3D dimensions."""
    length: float
    width: float
    height: float


class CuboidWorldData(BaseSchema):
    """Cuboid in world coordinates."""
    center: Point3D
    dimensions: Dimensions3D
    rotation: Rotation3D
    origin_frame_id: UUID | None = None
    origin_ego_pose: dict[str, Any] | None = None


class FrameCuboidData(BaseSchema):
    """Per-frame cuboid data in LiDAR coordinates."""
    center: Point3D
    rotation: Rotation3D
    is_keyframe: bool = False


class Annotation4DBase(BaseSchema):
    """Base schema for 4D annotations."""
    track_id: UUID
    type: str = "cuboid"
    class_id: str
    world_data: dict[str, Any]
    frame_data: dict[str, Any] = Field(default_factory=dict)
    frame_ids: list[UUID] = Field(default_factory=list)
    is_static: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual_4d"


class Annotation4DCreate(Annotation4DBase):
    """Create a new 4D annotation."""
    id: UUID | None = None
    task_id: UUID


class Annotation4DUpdate(BaseSchema):
    """Update a 4D annotation."""
    world_data: dict[str, Any] | None = None
    frame_data: dict[str, Any] | None = None
    frame_ids: list[UUID] | None = None
    attributes: dict[str, Any] | None = None
    class_id: str | None = None


class Annotation4DUpdateBulkItem(BaseSchema):
    """Single item for bulk update of 4D annotations."""
    id: UUID
    world_data: dict[str, Any] | None = None
    frame_data: dict[str, Any] | None = None
    frame_ids: list[UUID] | None = None
    attributes: dict[str, Any] | None = None
    class_id: str | None = None


class BulkAnnotation4DUpdate(BaseSchema):
    """Bulk update 4D annotations."""
    annotations: list[Annotation4DUpdateBulkItem]


class BulkAnnotation4DDelete(BaseSchema):
    """Bulk delete 4D annotations."""
    annotation_ids: list[UUID]


class Annotation4DResponse(Annotation4DBase, TimestampSchema):
    """Response for a 4D annotation."""
    id: UUID
    task_id: UUID
    is_migrated: bool
    migrated_at: datetime | None = None


class Annotation4DMigrateRequest(BaseSchema):
    """Request to migrate 4D annotations to regular 3D annotations."""
    annotation_4d_ids: list[UUID] | None = None


class Annotation4DMigrateResponse(BaseSchema):
    """Response for 4D to 3D migration."""
    migrated_count: int
    created_annotations: list[UUID]
    errors: list[dict[str, Any]] = Field(default_factory=list)



class Annotation3DBase(BaseSchema):
    """Base schema for 3D LiDAR annotations."""
    track_id: UUID | None = None
    type: str = "cuboid"
    class_id: str
    taxonomy_id: UUID | None = None
    data: dict[str, Any]
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual_3d"
    is_keyframe: bool = False
    is_static: bool = False
    is_verified: bool = False


class Annotation3DCreate(Annotation3DBase):
    """Create a 3D annotation."""
    id: UUID | None = None
    task_id: UUID
    frame_id: UUID


class Annotation3DUpdate(BaseSchema):
    """Update a 3D annotation."""
    track_id: UUID | None = None
    class_id: str | None = None
    taxonomy_id: UUID | None = None
    data: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    is_keyframe: bool | None = None
    is_static: bool | None = None
    is_verified: bool | None = None


class Annotation3DUpdateBulkItem(BaseSchema):
    """Single item for bulk update."""
    id: UUID
    track_id: UUID | None = None
    class_id: str | None = None
    taxonomy_id: UUID | None = None
    data: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    is_keyframe: bool | None = None
    is_static: bool | None = None
    is_verified: bool | None = None


class BulkAnnotation3DUpdate(BaseSchema):
    """Bulk update 3D annotations."""
    annotations: list[Annotation3DUpdateBulkItem]


class BulkAnnotation3DDelete(BaseSchema):
    """Bulk delete 3D annotations."""
    annotation_ids: list[UUID]


class TrackWideUpdate3D(BaseSchema):
    """Update all annotations in a track with specified fields."""
    class_id: str | None = None
    attributes: dict[str, Any] | None = None
    dimensions: dict[str, float] | None = None
    is_static: bool | None = None


class Annotation3DResponse(Annotation3DBase, TimestampSchema):
    """Response for a 3D annotation."""
    id: UUID
    task_id: UUID
    frame_id: UUID
    taxonomy_id: UUID | None = None
    is_migrated_to_fusion: bool
    migrated_at: datetime | None = None
    fusion_annotation_id: UUID | None = None
    is_verified: bool
    is_keyframe: bool = False
    is_static: bool = False


class Annotation2DProjection(BaseSchema):
    """2D projection data for a camera."""
    bbox: BBox2D | None = None
    visibility: float = Field(default=1.0, ge=0, le=1)
    occlusion: float = Field(default=0.0, ge=0, le=1)
    truncation: float = Field(default=0.0, ge=0, le=1)
    verified: bool = False


class AnnotationFusionBase(BaseSchema):
    """Base schema for Fusion annotations (3D + 2D combined)."""
    track_id: UUID | None = None
    type: str = "cuboid_fusion"
    class_id: str
    data_3d: dict[str, Any]
    data_2d: dict[str, Annotation2DProjection] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual_fusion"


class AnnotationFusionCreate(AnnotationFusionBase):
    """Create a Fusion annotation."""
    id: UUID | None = None
    task_id: UUID
    frame_id: UUID
    source_3d_annotation_id: UUID | None = None


class AnnotationFusionUpdate(BaseSchema):
    """Update a Fusion annotation."""
    track_id: UUID | None = None
    class_id: str | None = None
    data_3d: dict[str, Any] | None = None
    data_2d: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None


class AnnotationFusionResponse(AnnotationFusionBase, TimestampSchema):
    """Response for a Fusion annotation."""
    id: UUID
    task_id: UUID
    frame_id: UUID
    source_3d_annotation_id: UUID | None = None
    is_verified: bool


class Annotation2DBase(BaseSchema):
    """Base schema for 2D camera annotations."""
    camera_id: str
    track_id: UUID | None = None
    type: str
    class_id: str
    taxonomy_id: UUID | None = None
    data: dict[str, Any]
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual_2d"


class Annotation2DCreate(Annotation2DBase):
    """Create a 2D annotation."""
    id: UUID | None = None
    task_id: UUID
    frame_id: UUID


class Annotation2DUpdate(BaseSchema):
    """Update a 2D annotation."""
    track_id: UUID | None = None
    class_id: str | None = None
    data: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None


class Annotation2DUpdateBulkItem(BaseSchema):
    """Single item for bulk update."""
    id: UUID
    track_id: UUID | None = None
    class_id: str | None = None
    data: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None


class BulkAnnotation2DUpdate(BaseSchema):
    """Bulk update 2D annotations."""
    annotations: list[Annotation2DUpdateBulkItem]


class BulkAnnotation2DDelete(BaseSchema):
    """Bulk delete 2D annotations."""
    annotation_ids: list[UUID]


class TrackWideUpdate2D(BaseSchema):
    """Update all 2D annotations in a track with specified fields."""
    class_id: str | None = None
    attributes: dict[str, Any] | None = None


class Annotation2DResponse(Annotation2DBase, TimestampSchema):
    """Response for a 2D annotation."""
    id: UUID
    task_id: UUID
    frame_id: UUID
    is_verified: bool


class Track2DBase(BaseSchema):
    """Base schema for 2D tracks."""
    camera_id: str
    class_id: str
    name: str | None = None
    color: str | None = None
    start_frame_index: int | None = None
    end_frame_index: int | None = None
    is_interpolated: bool = False
    is_complete: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class Track2DCreate(Track2DBase):
    """Create a 2D track."""
    id: UUID | None = None
    task_id: UUID


class Track2DUpdate(BaseSchema):
    """Update a 2D track."""
    name: str | None = None
    color: str | None = None
    class_id: str | None = None
    start_frame_index: int | None = None
    end_frame_index: int | None = None
    is_interpolated: bool | None = None
    is_complete: bool | None = None
    attributes: dict[str, Any] | None = None


class Track2DResponse(Track2DBase, TimestampSchema):
    """Response for a 2D track."""
    id: UUID
    task_id: UUID


class BulkTrack2DCreate(BaseSchema):
    """Bulk create 2D tracks."""
    tracks: list[Track2DCreate]


class Migrate4DTo3DRequest(BaseSchema):
    """Request to migrate 4D annotations to 3D annotations."""
    annotation_4d_ids: list[UUID] | None = None
    preserve_uuids: bool = True


class Migrate4DTo3DResponse(BaseSchema):
    """Response for 4D to 3D migration."""
    migrated_count: int
    created_annotation_ids: list[UUID]
    track_id_mapping: dict[str, str] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class Migrate3DToFusionRequest(BaseSchema):
    """Request to migrate 3D annotations to Fusion annotations."""
    annotation_3d_ids: list[UUID] | None = None
    preserve_uuids: bool = True


class Migrate3DToFusionResponse(BaseSchema):
    """Response for 3D to Fusion migration."""
    migrated_count: int
    created_annotation_ids: list[UUID]
    errors: list[dict[str, Any]] = Field(default_factory=list)


class BulkAnnotation3DCreate(BaseSchema):
    """Bulk create 3D annotations."""
    annotations: list[Annotation3DCreate]


class BulkAnnotationFusionCreate(BaseSchema):
    """Bulk create Fusion annotations."""
    annotations: list[AnnotationFusionCreate]


class BulkAnnotation2DCreate(BaseSchema):
    """Bulk create 2D annotations."""
    annotations: list[Annotation2DCreate]


# ---------------------------------------------------------------------------
# Track-level refinement (tracks_3d)
# ---------------------------------------------------------------------------


class Track3DRefinementUpdate(BaseSchema):
    """Toggle the human-review flag of a single 3D track."""

    is_refined: bool


class Track3DRefinementResponse(BaseSchema):
    """Refinement state of one 3D track."""

    track_id: UUID
    task_id: UUID
    is_refined: bool
    refined_by: UUID | None = None
    refined_at: datetime | None = None
