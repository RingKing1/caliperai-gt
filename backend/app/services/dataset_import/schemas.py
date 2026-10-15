"""Request/response models for dataset import endpoints."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field
class SensorInfo(BaseModel):
    """Sensor information from metadata."""
    sensor_id: str
    type: Optional[str] = None
    format: str
    resolution: Optional[List[int]] = None
    fps: Optional[float] = None
    coordinate_system: Optional[str] = None


class DatasetMetadata(BaseModel):
    """Dataset-level metadata from metadata.json."""
    name: str
    version: Optional[str] = "1.0.0"
    sensors: Dict[str, Any] = Field(default_factory=dict)


class SceneMetadata(BaseModel):
    """Scene-level metadata from scene_metadata.json."""
    scene_id: str
    name: Optional[str] = None
    location: Optional[str] = None
    weather: Optional[str] = None
    time_of_day: Optional[str] = None
    recording_date: Optional[str] = None
    duration_seconds: Optional[float] = None
    frame_count: int
    fps: float = 10.0
    ego_vehicle: Optional[str] = None


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
    errors: List[str] = Field(default_factory=list)
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
    errors: List[str] = Field(default_factory=list)
    renamed_scenes: List[RenamedScene] = Field(default_factory=list)


class SceneConflict(BaseModel):
    original_name: str
    suggested_name: str


class SceneNameCheckRequest(BaseModel):
    dataset_id: UUID
    folder_names: List[str]
    preserve_folder_names: bool = True


class SceneNameCheckResponse(BaseModel):
    conflicts: List[SceneConflict]




class FolderItem(BaseModel):
    """A file or folder in a directory listing."""
    name: str
    path: str
    is_directory: bool
    size: Optional[int] = None


class BrowseFolderResponse(BaseModel):
    """Response from folder browsing endpoint."""
    current_path: str
    parent_path: Optional[str] = None
    items: List[FolderItem] = Field(default_factory=list)





class ImportJobResponse(BaseModel):
    """Status of a background import job (POST /import/jobs/* + polling)."""

    model_config = {"from_attributes": True}

    id: UUID
    dataset_id: UUID
    created_by: Optional[UUID] = None
    job_type: str
    source_filename: Optional[str] = None
    status: str
    phase: Optional[str] = None
    progress: int = 0
    total_scenes: int = 0
    processed_scenes: int = 0
    scenes_imported: int = 0
    frames_imported: int = 0
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
