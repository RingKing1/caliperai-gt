"""Google Cloud Storage browsing/discovery/import API schemas."""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class GCSCredentialsRequest(BaseModel):
    """Request to set GCS credentials."""
    credentials_json: str = Field(..., description="Service account JSON as string")
    project_id: str | None = Field(None, description="GCS project ID (optional if in credentials)")


class GCSConnectionTest(BaseModel):
    """Response from connection test."""
    success: bool
    message: str
    project_id: str | None = None


class GCSBucketResponse(BaseModel):
    """GCS bucket info."""
    name: str
    location: str | None = None
    storage_class: str | None = None
    created: str | None = None


class GCSObjectResponse(BaseModel):
    """GCS object (file or folder)."""
    name: str
    path: str
    is_folder: bool = False
    size: int = 0
    updated: str | None = None
    content_type: str | None = None


class GCSSceneResponse(BaseModel):
    """Discovered scene in GCS."""
    scene_id: str
    path: str
    bucket: str
    prefix: str
    frame_count: int = 0
    sensors: list[str] = []
    has_calibration: bool = False
    has_annotations: bool = False
    has_metadata: bool = False
    metadata: dict[str, Any] = {}


class GCSListObjectsResponse(BaseModel):
    """Response from listing objects."""
    bucket: str
    prefix: str
    objects: list[GCSObjectResponse]
    folders: list[str]


class GCSDiscoverScenesResponse(BaseModel):
    """Response from scene discovery."""
    bucket: str
    prefix: str
    scenes: list[GCSSceneResponse]


class GCSImportRequest(BaseModel):
    """Request to import a scene from GCS."""
    bucket: str = Field(..., description="GCS bucket name")
    prefix: str = Field(..., description="Scene prefix path in bucket")
    dataset_id: UUID = Field(..., description="Target dataset ID")
    credentials_json: str | None = Field(None, description="Optional credentials override")
    derive_taxonomy: bool = Field(True, description="Derive taxonomy from annotations")
    overwrite_annotations: bool = Field(False, description="Overwrite existing annotations")


class GCSImportResponse(BaseModel):
    """Response from scene import."""
    success: bool
    message: str
    scene_id: str | None = None
    frames_imported: int = 0
    errors: list[str] = []
