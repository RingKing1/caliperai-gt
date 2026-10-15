"""Google Cloud Storage browsing/discovery/import API schemas."""
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GCSCredentialsRequest(BaseModel):
    """Request to set GCS credentials."""
    credentials_json: str = Field(..., description="Service account JSON as string")
    project_id: Optional[str] = Field(None, description="GCS project ID (optional if in credentials)")


class GCSConnectionTest(BaseModel):
    """Response from connection test."""
    success: bool
    message: str
    project_id: Optional[str] = None


class GCSBucketResponse(BaseModel):
    """GCS bucket info."""
    name: str
    location: Optional[str] = None
    storage_class: Optional[str] = None
    created: Optional[str] = None


class GCSObjectResponse(BaseModel):
    """GCS object (file or folder)."""
    name: str
    path: str
    is_folder: bool = False
    size: int = 0
    updated: Optional[str] = None
    content_type: Optional[str] = None


class GCSSceneResponse(BaseModel):
    """Discovered scene in GCS."""
    scene_id: str
    path: str
    bucket: str
    prefix: str
    frame_count: int = 0
    sensors: List[str] = []
    has_calibration: bool = False
    has_annotations: bool = False
    has_metadata: bool = False
    metadata: Dict[str, Any] = {}


class GCSListObjectsResponse(BaseModel):
    """Response from listing objects."""
    bucket: str
    prefix: str
    objects: List[GCSObjectResponse]
    folders: List[str]


class GCSDiscoverScenesResponse(BaseModel):
    """Response from scene discovery."""
    bucket: str
    prefix: str
    scenes: List[GCSSceneResponse]


class GCSImportRequest(BaseModel):
    """Request to import a scene from GCS."""
    bucket: str = Field(..., description="GCS bucket name")
    prefix: str = Field(..., description="Scene prefix path in bucket")
    dataset_id: UUID = Field(..., description="Target dataset ID")
    credentials_json: Optional[str] = Field(None, description="Optional credentials override")
    derive_taxonomy: bool = Field(True, description="Derive taxonomy from annotations")
    overwrite_annotations: bool = Field(False, description="Overwrite existing annotations")


class GCSImportResponse(BaseModel):
    """Response from scene import."""
    success: bool
    message: str
    scene_id: Optional[str] = None
    frames_imported: int = 0
    errors: List[str] = []
