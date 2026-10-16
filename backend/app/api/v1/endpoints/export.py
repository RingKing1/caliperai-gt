"""
Export API Endpoints

Provides export functionality for datasets, scenes, and tasks.
Supports exporting:
- Labels only (JSON format)
- Data + Labels (ZIP archive)
- Per-sensor COCO format annotations

Folder structure for exports:
    scene_export.zip/
    ├── data/
    │   ├── lidar/
    │   └── cameras/{camera_name}/
    ├── annotations/
    │   ├── lidar.json          # COCO-like format for 3D annotations
    │   ├── {camera_name}.json  # COCO format for each camera's 2D annotations
    │   └── ...
    └── metadata.json           # Scene metadata, calibration, taxonomy
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.core.database import get_db
from app.models.models import User
from app.services.export import (
    ExportNotFoundError,
    export_dataset_bundle,
    export_scene_bundle,
    export_task_bundle,
)

router = APIRouter()


@router.get("/tasks/{task_id}/export")
async def export_task(
    task_id: UUID,
    include_data: bool = Query(False, description="Include raw data files (images, point clouds)"),
    format: Literal["json", "coco"] = Query(
        "coco",
        description="Export format (coco = per-sensor COCO files, json = legacy single file)",
    ),
    taxonomy_id: UUID | None = Query(
        None,
        description=(
            "Filter export to a specific taxonomy. Segmentation taxonomies export only "
            ".label files; others export only their DB annotations."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a single task's annotations.

    - **include_data**: If True, includes raw data files in the ZIP.
    - **format**:
        - coco: Per-sensor COCO format files (annotations/lidar.json, annotations/camera_front.json, etc.)
        - json: Legacy single labels.json file
    - **taxonomy_id**: Optional UUID to filter the export to a single taxonomy.
        When a 3D segmentation taxonomy is specified, only semantic KITTI-format .label files are included.
        When another taxonomy is specified, only annotations associated with that taxonomy are included.
    """
    try:
        stream, media_type, filename = await export_task_bundle(
            db,
            task_id=task_id,
            include_data=include_data,
            format=format,
            taxonomy_id=taxonomy_id,
            username=current_user.username,
        )
    except ExportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/scenes/{scene_id}/export")
async def export_scene(
    scene_id: UUID,
    include_data: bool = Query(False, description="Include raw data files"),
    format: Literal["json", "coco"] = Query(
        "coco",
        description="Export format (coco = per-sensor COCO files, json = legacy single file)",
    ),
    taxonomy_id: UUID | None = Query(None, description="Filter export to a specific taxonomy."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export all annotations for a scene (across all tasks).

    - **include_data**: If True, includes raw data files in the ZIP.
    - **format**:
        - coco: Per-sensor COCO format files (annotations/lidar.json, annotations/camera_front.json, etc.)
        - json: Legacy single labels.json file

    ZIP structure for 'coco' format:
    ```
    scene_export.zip/
    ├── data/
    │   ├── lidar/
    │   └── cameras/{camera_name}/
    ├── annotations/
    │   ├── lidar.json
    │   ├── {camera_name}.json
    │   └── fusion.json (if applicable)
    └── metadata.json
    ```
    """
    try:
        stream, media_type, filename = await export_scene_bundle(
            db,
            scene_id=scene_id,
            include_data=include_data,
            format=format,
            taxonomy_id=taxonomy_id,
            username=current_user.username,
        )
    except ExportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/datasets/{dataset_id}/export")
async def export_dataset(
    dataset_id: UUID,
    include_data: bool = Query(False, description="Include raw data files"),
    accepted_only: bool = Query(False, description="Only export accepted/completed tasks"),
    format: Literal["json", "coco"] = Query(
        "coco",
        description="Export format (coco = per-sensor COCO files, json = legacy single file)",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export all annotations for a dataset (across all scenes and tasks).

    - **include_data**: If True, includes raw data files in the ZIP.
    - **accepted_only**: If True, only exports annotations from accepted/completed tasks.
    - **format**:
        - coco: Per-sensor COCO format files for each scene
        - json: Legacy single labels.json file

    ZIP structure for 'coco' format:
    ```
    dataset_export.zip/
    ├── {scene_name}/
    │   ├── data/
    │   │   ├── lidar/
    │   │   └── cameras/{camera_name}/
    │   └── annotations/
    │       ├── lidar.json
    │       ├── {camera_name}.json
    │       └── fusion.json
    └── metadata.json
    ```
    """
    try:
        stream, media_type, filename = await export_dataset_bundle(
            db,
            dataset_id=dataset_id,
            include_data=include_data,
            accepted_only=accepted_only,
            format=format,
            username=current_user.username,
        )
    except ExportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
