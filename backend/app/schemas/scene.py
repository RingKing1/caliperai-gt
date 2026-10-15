"""Scene and frame API schemas including calibration and storage metadata."""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import BaseSchema, TimestampSchema

if TYPE_CHECKING:
    # Forward ref only (scene -> task); resolved by model_rebuild() in the
    # schemas facade once every domain module is imported.
    from app.schemas.task import TaskResponse


class RotationMatrix(BaseSchema):
    """3x3 rotation matrix."""
    matrix: List[List[float]] = Field(..., min_length=3, max_length=3)

    @field_validator("matrix")
    @classmethod
    def validate_rotation_matrix(cls, v):
        if len(v) != 3 or any(len(row) != 3 for row in v):
            raise ValueError("Rotation matrix must be 3x3")
        return v


class ExtrinsicCalibration(BaseSchema):
    """Extrinsic calibration (rotation + translation)."""
    rotation: List[List[float]]
    translation: List[float]

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
    distortion: Optional[List[float]] = None


class CameraCalibration(BaseSchema):
    """Complete camera calibration."""
    extrinsic: ExtrinsicCalibration
    intrinsic: IntrinsicCalibration


class SceneCalibration(BaseSchema):
    """All calibration data for a scene."""
    lidar_to_cameras: Dict[str, CameraCalibration]
    ego_to_lidar: Optional[ExtrinsicCalibration] = None


FlexibleCalibration = Union[Dict[str, Any], SceneCalibration]



class SceneMetadata(BaseSchema):
    """Metadata for a scene."""
    location: Optional[str] = None
    weather: Optional[str] = None
    time_of_day: Optional[str] = None
    recording_date: Optional[str] = None
    duration_seconds: Optional[float] = None
    ego_vehicle: Optional[str] = None


class StoragePaths(BaseSchema):
    """Storage paths for scene data."""
    lidar_base: str
    cameras: Dict[str, str] = Field(default_factory=dict)
    ego_poses: Optional[str] = None


class SceneBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    scene_metadata: SceneMetadata = Field(default_factory=SceneMetadata)
    frame_count: int = Field(..., gt=0)
    fps: float = Field(default=10.0, gt=0)
    calibration: SceneCalibration
    storage_paths: StoragePaths
    deadline: Optional[datetime] = None


class SceneCreate(SceneBase):
    dataset_id: UUID


class SceneUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    scene_metadata: Optional[SceneMetadata] = None
    calibration: Optional[SceneCalibration] = None
    deadline: Optional[datetime] = None
    selected_taxonomy_id: Optional[UUID] = None


class SceneResponse(TimestampSchema):
    """Response schema with flexible calibration to handle both old and new formats."""
    id: UUID
    dataset_id: UUID
    name: str
    description: Optional[str] = None
    scene_metadata: Dict[str, Any] = Field(default_factory=dict)
    frame_count: int
    fps: float
    calibration: Optional[Dict[str, Any]] = None
    storage_paths: Dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[datetime] = None
    selected_taxonomy_id: Optional[UUID] = None
    tasks: List['TaskResponse'] = Field(default_factory=list)


class SceneSearchResponse(BaseSchema):
    """Structured scene search response."""

    query: Optional[str] = None
    classes: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    class_groups: dict[str, list[str]]
    results: list[dict]



class EgoPose(BaseSchema):
    """Ego vehicle pose at a frame."""
    position: List[float] = Field(..., min_length=3, max_length=3)
    rotation: List[float] = Field(..., min_length=4, max_length=4)
    velocity: Optional[List[float]] = None


class FrameFilePaths(BaseSchema):
    """File paths for frame data."""
    lidar: str | None = None
    cameras: Dict[str, str] = Field(default_factory=dict)


class FrameBase(BaseSchema):
    frame_index: int = Field(..., ge=0)
    timestamp: float = Field(..., ge=0)
    ego_pose: Optional[EgoPose] = None
    file_paths: FrameFilePaths


class FrameCreate(FrameBase):
    scene_id: UUID


class FrameResponse(FrameBase, TimestampSchema):
    id: UUID
    scene_id: UUID
