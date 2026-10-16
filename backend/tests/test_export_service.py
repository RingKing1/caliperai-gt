"""Unit tests for export domain services and export endpoints."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import export as export_endpoints
from app.services.export import (
    ExportNotFoundError,
    build_coco_categories,
    build_task_export_folder_name,
    get_category_id_map,
    merge_overlapping_annotations,
)
from app.services.export.export_service import (
    export_dataset_bundle,
    export_scene_bundle,
    export_task_bundle,
)


def test_merge_overlapping_annotations_prefers_recent():
    data = {
        "cuboids_3d": [
            {
                "id": "1",
                "track_id": "trk_1",
                "frame_index": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "val": "old",
            },
            {
                "id": "2",
                "track_id": "trk_1",
                "frame_index": 0,
                "created_at": "2026-01-02T00:00:00Z",
                "val": "new",
            },
            {
                "id": "3",
                "track_id": None,
                "frame_index": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "val": "untracked",
            },
        ],
        "annotations_4d": [
            {
                "id": "4",
                "track_id": "trk_4d",
                "created_at": "2026-01-01T00:00:00Z",
                "val": "old4d",
            },
            {
                "id": "5",
                "track_id": "trk_4d",
                "created_at": "2026-01-03T00:00:00Z",
                "val": "new4d",
            },
        ],
    }

    merged = merge_overlapping_annotations(data)

    cuboids = merged["cuboids_3d"]
    assert len(cuboids) == 2
    tracked = [c for c in cuboids if c.get("track_id") == "trk_1"]
    assert len(tracked) == 1
    assert tracked[0]["val"] == "new"

    untracked = [c for c in cuboids if c.get("track_id") is None]
    assert len(untracked) == 1

    ann4d = merged["annotations_4d"]
    assert len(ann4d) == 1
    assert ann4d[0]["val"] == "new4d"


def test_coco_categories_builder():
    taxonomy = {
        "classes": [
            {"id": "car", "name": "Automobile", "color": "#ff0000"},
            {"id": "pedestrian", "name": "Walker", "color": "#00ff00"},
        ]
    }
    cats = build_coco_categories(taxonomy)
    assert len(cats) == 2
    assert cats[0]["name"] == "car"
    assert cats[1]["name"] == "pedestrian"

    cat_map = get_category_id_map(taxonomy)
    assert cat_map["car"] == 1
    assert cat_map["pedestrian"] == 2


def test_build_task_export_folder_name():
    task = MagicMock()
    task.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    task.name = "Test Task"
    folder = build_task_export_folder_name(task)
    assert folder == "Test_Task__11111111"

    task.name = None
    folder_default = build_task_export_folder_name(task)
    assert folder_default == "task_11111111__11111111"


@pytest.mark.asyncio
async def test_export_task_bundle_not_found():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(ExportNotFoundError, match="Task not found"):
        await export_task_bundle(
            db,
            task_id=uuid.uuid4(),
            include_data=False,
            format="json",
            username="tester",
        )


@pytest.mark.asyncio
async def test_export_scene_bundle_not_found():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(ExportNotFoundError, match="Scene not found"):
        await export_scene_bundle(
            db,
            scene_id=uuid.uuid4(),
            include_data=False,
            format="json",
            username="tester",
        )


@pytest.mark.asyncio
async def test_export_dataset_bundle_not_found():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(ExportNotFoundError, match="Dataset not found"):
        await export_dataset_bundle(
            db,
            dataset_id=uuid.uuid4(),
            include_data=False,
            format="json",
            username="tester",
        )


@pytest.mark.asyncio
async def test_export_endpoints_raise_404_on_missing_entity():
    db = AsyncMock()
    db.get.return_value = None
    user = MagicMock(username="tester")

    with pytest.raises(HTTPException) as exc1:
        await export_endpoints.export_task(
            task_id=uuid.uuid4(),
            db=db,
            current_user=user,
        )
    assert exc1.value.status_code == 404

    with pytest.raises(HTTPException) as exc2:
        await export_endpoints.export_scene(
            scene_id=uuid.uuid4(),
            db=db,
            current_user=user,
        )
    assert exc2.value.status_code == 404

    with pytest.raises(HTTPException) as exc3:
        await export_endpoints.export_dataset(
            dataset_id=uuid.uuid4(),
            db=db,
            current_user=user,
        )
    assert exc3.value.status_code == 404
