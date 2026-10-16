"""Scene and frame API schemas including calibration and storage metadata."""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import BaseSchema, TimestampSchema

if TYPE_CHECKING:
    # Forward ref only (scene -> task); resolved by model_rebuild() in the
    # schemas facade once every domain module is imported.
    from app.schemas.task import TaskResponse


class RotationMatrix(BaseSchema):
    """3x3 rotation matrix."""
    matrix: list[list[float]] = Field(..., min_length=3, max_length=3)

    @field_validator("matrix")
    @classmethod
    def validate_rotation_matrix(cls, v):
        if len(v) != 3 or any(len(row) != 3 for row in v):
            raise ValueError("Rotation matrix must be 3x3")
        return v


class ExtrinsicCalibration(BaseSchema):
    """Extrinsic calibration (rotation + translation)."""
    rotation: list[list[float]]
    translation: list[float]

    @field_validator("translation")
    @classmethod
    def validate_translation(cls, v):
        if len(v) != 3:
            raise ValueError("Translation must have 3 components")
        return v


class IntrinsicCalibration(BaseSchema):
    """Intrinsic camera calibration."""
    fx: float = Field(..., gt=0)
    fy: float = Field(..., gt=0)
    cx: float = Field(..., gt=0)
    cy: float = Field(..., gt=0)
    distortion: list[float] | None = None
    # Sensor resolution [width, height]; used by the frontend to size camera
    # projection canvases (falls back to cx*2/cy*2 when absent).
    resolution: tuple[int, int] | None = None
    # None = let the frontend's fisheye auto-detection decide.
    camera_model: Literal["pinhole", "kannala_brandt"] | None = None


class CameraCalibration(BaseSchema):
    """Complete camera calibration."""
    extrinsic: ExtrinsicCalibration
    intrinsic: IntrinsicCalibration


class SceneCalibration(BaseSchema):
    """All calibration data for a scene."""
    lidar_to_cameras: dict[str, CameraCalibration]
    ego_to_lidar: ExtrinsicCalibration | None = None


FlexibleCalibration = dict[str, Any] | SceneCalibration



class SceneMetadata(BaseSchema):
    """Metadata for a scene."""
    location: str | None = None
    weather: str | None = None
    time_of_day: str | None = None
    recording_date: str | None = None
    duration_seconds: float | None = None
    ego_vehicle: str | None = None


class StoragePaths(BaseSchema):
    """Storage paths for scene data."""
    lidar_base: str
    cameras: dict[str, str] = Field(default_factory=dict)
    ego_poses: str | None = None


class SceneBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    scene_metadata: SceneMetadata = Field(default_factory=SceneMetadata)
    frame_count: int = Field(..., gt=0)
    fps: float = Field(default=10.0, gt=0)
    calibration: SceneCalibration
    storage_paths: StoragePaths
    deadline: datetime | None = None


class SceneCreate(SceneBase):
    dataset_id: UUID


class SceneUpdate(BaseSchema):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    scene_metadata: SceneMetadata | None = None
    calibration: SceneCalibration | None = None
    deadline: datetime | None = None
    selected_taxonomy_id: UUID | None = None


class SceneResponse(TimestampSchema):
    """Response schema with flexible calibration to handle both old and new formats."""
    id: UUID
    dataset_id: UUID
    name: str
    description: str | None = None
    scene_metadata: dict[str, Any] = Field(default_factory=dict)
    frame_count: int
    fps: float
    calibration: dict[str, Any] | None = None
    storage_paths: dict[str, Any] = Field(default_factory=dict)
    deadline: datetime | None = None
    selected_taxonomy_id: UUID | None = None
    tasks: list['TaskResponse'] = Field(default_factory=list)


class SceneSearchResponse(BaseSchema):
    """Structured scene search response."""

    query: str | None = None
    classes: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    class_groups: dict[str, list[str]]
    results: list[dict]



class EgoPose(BaseSchema):
    """Ego vehicle pose at a frame."""
    position: list[float] = Field(..., min_length=3, max_length=3)
    rotation: list[float] = Field(..., min_length=4, max_length=4)
    velocity: list[float] | None = None


class FrameFilePaths(BaseSchema):
    """File paths for frame data."""
    lidar: str | None = None
    cameras: dict[str, str] = Field(default_factory=dict)


class FrameBase(BaseSchema):
    frame_index: int = Field(..., ge=0)
    timestamp: float = Field(..., ge=0)
    ego_pose: EgoPose | None = None
    file_paths: FrameFilePaths


class FrameCreate(FrameBase):
    scene_id: UUID


class FrameResponse(FrameBase, TimestampSchema):
    id: UUID
    scene_id: UUID
