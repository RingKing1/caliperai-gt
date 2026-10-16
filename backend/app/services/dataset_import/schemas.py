"""Request/response models for dataset import endpoints."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SensorInfo(BaseModel):
    """Sensor information from metadata."""
    sensor_id: str
    type: str | None = None
    format: str
    resolution: list[int] | None = None
    fps: float | None = None
    coordinate_system: str | None = None


class DatasetMetadata(BaseModel):
    """Dataset-level metadata from metadata.json."""
    name: str
    version: str | None = "1.0.0"
    sensors: dict[str, Any] = Field(default_factory=dict)


class SceneMetadata(BaseModel):
    """Scene-level metadata from scene_metadata.json."""
    scene_id: str
    name: str | None = None
    location: str | None = None
    weather: str | None = None
    time_of_day: str | None = None
    recording_date: str | None = None
    duration_seconds: float | None = None
    frame_count: int
    fps: float = 10.0
    ego_vehicle: str | None = None


class ImportRequest(BaseModel):
    """Request to import a dataset from a local path."""
    dataset_id: UUID
    root_path: str = Field(..., description="Absolute path to dataset root folder")


class ImportProgress(BaseModel):
    """Progress information for import job."""
    status: str
    total_scenes: int = 0
    processed_scenes: int = 0
    total_frames: int = 0
    processed_frames: int = 0
    errors: list[str] = Field(default_factory=list)
    message: str = ""


class RenamedScene(BaseModel):
    original_name: str
    new_name: str
    scene_id: str


class ImportResponse(BaseModel):
    """Response from import endpoint."""
    success: bool
    message: str
    scenes_imported: int = 0
    frames_imported: int = 0
    errors: list[str] = Field(default_factory=list)
    renamed_scenes: list[RenamedScene] = Field(default_factory=list)


class SceneConflict(BaseModel):
    original_name: str
    suggested_name: str


class SceneNameCheckRequest(BaseModel):
    dataset_id: UUID
    folder_names: list[str]
    preserve_folder_names: bool = True


class SceneNameCheckResponse(BaseModel):
    conflicts: list[SceneConflict]




class FolderItem(BaseModel):
    """A file or folder in a directory listing."""
    name: str
    path: str
    is_directory: bool
    size: int | None = None


class BrowseFolderResponse(BaseModel):
    """Response from folder browsing endpoint."""
    current_path: str
    parent_path: str | None = None
    items: list[FolderItem] = Field(default_factory=list)





class ImportJobResponse(BaseModel):
    """Status of a background import job (POST /import/jobs/* + polling)."""

    model_config = {"from_attributes": True}

    id: UUID
    dataset_id: UUID
    created_by: UUID | None = None
    job_type: str
    source_filename: str | None = None
    status: str
    phase: str | None = None
    progress: int = 0
    total_scenes: int = 0
    processed_scenes: int = 0
    scenes_imported: int = 0
    frames_imported: int = 0
    message: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
