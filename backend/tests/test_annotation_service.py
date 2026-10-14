"""Unit tests for the cross-modality AnnotationService write rules.

These cover the logic previously copy-pasted across the five annotation
endpoint modules (auto-transition + is_verified derivation + ORM mapping).
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.models import Task, TaskStatus
from app.schemas.schemas import (
    Annotation2DCreate,
    Annotation2DProjection,
    Annotation3DCreate,
    Annotation4DCreate,
    AnnotationCreate,
    AnnotationFusionCreate,
    AnnotationSource,
)
from app.services.annotation_service import (
    AnnotationService,
    resolve_is_verified,
)

TASK_ID = uuid4()
FRAME_ID = uuid4()
TRACK_ID = uuid4()


def test_resolve_is_verified_manual_sources_by_modality():
    assert resolve_is_verified("manual", "generic") is True
    assert resolve_is_verified("imported", "generic") is False
    assert resolve_is_verified("manual_2d", "2d") is True
    assert resolve_is_verified("auto_2d", "2d") is False
    assert resolve_is_verified("manual_3d", "3d") is True
    assert resolve_is_verified("manual", "3d") is True
    assert resolve_is_verified("auto_interpolated", "3d") is False
    assert resolve_is_verified("manual_fusion", "fusion") is True


def test_resolve_is_verified_explicit_override_wins():
    assert resolve_is_verified("manual_3d", "3d", explicit=False) is False
    assert resolve_is_verified("auto", "3d", explicit=True) is True


def test_build_generic_maps_manual_source():
    payload = AnnotationCreate(
        task_id=TASK_ID,
        frame_id=FRAME_ID,
        type="cuboid",
        class_id="car",
        data={"x": 1},
        source=AnnotationSource.MANUAL,
    )
    annotation = AnnotationService.build_generic(payload)
    assert annotation.source == "manual"
    assert annotation.is_verified is True
    assert annotation.type == "cuboid"


def test_build_3d_honors_keyframe_static_and_verified():
    payload = Annotation3DCreate(
        task_id=TASK_ID,
        frame_id=FRAME_ID,
        class_id="car",
        data={"center": {}},
        source="manual_3d",
        is_verified=True,
        is_keyframe=True,
        is_static=True,
    )
    annotation = AnnotationService.build_3d(payload)
    assert annotation.is_verified is True
    assert annotation.is_keyframe is True
    assert annotation.is_static is True


def test_apply_3d_overwrites_all_write_fields():
    existing = AnnotationService.build_3d(
        Annotation3DCreate(
            task_id=TASK_ID,
            frame_id=FRAME_ID,
            class_id="old",
            data={"v": 1},
            source="auto",
            is_verified=True,
        )
    )
    incoming = Annotation3DCreate(
        id=existing.id,
        task_id=TASK_ID,
        frame_id=FRAME_ID,
        class_id="new",
        data={"v": 2},
        source="manual_3d",
        is_verified=False,
        is_keyframe=True,
    )
    AnnotationService.apply_3d(existing, incoming)
    assert existing.class_id == "new"
    assert existing.data == {"v": 2}
    assert existing.source == "manual_3d"
    assert existing.is_verified is False
    assert existing.is_keyframe is True


def test_apply_2d_rederives_verified_state_from_source():
    # Previously a manual/verified row stays verified even when overwritten
    # as auto; the unified rule re-derives from the incoming source.
    existing = AnnotationService.build_2d(
        Annotation2DCreate(
            task_id=TASK_ID,
            frame_id=FRAME_ID,
            camera_id="cam0",
            type="bbox",
            class_id="car",
            data={},
            source="manual_2d",
        )
    )
    assert existing.is_verified is True
    incoming = Annotation2DCreate(
        id=existing.id,
        task_id=TASK_ID,
        frame_id=FRAME_ID,
        camera_id="cam0",
        type="bbox",
        class_id="car",
        data={"x": 1},
        source="auto_2d",
    )
    AnnotationService.apply_2d(existing, incoming)
    assert existing.source == "auto_2d"
    assert existing.is_verified is False

    incoming_manual = Annotation2DCreate(
        id=existing.id,
        task_id=TASK_ID,
        frame_id=FRAME_ID,
        camera_id="cam0",
        type="bbox",
        class_id="car",
        data={"x": 2},
        source="manual_2d",
    )
    AnnotationService.apply_2d(existing, incoming_manual)
    assert existing.is_verified is True


def test_build_4d_normalizes_frame_keys_and_ids():
    annotation = AnnotationService.build_4d(
        Annotation4DCreate(
            task_id=TASK_ID,
            track_id=TRACK_ID,
            class_id="car",
            world_data={},
            frame_data={"frame-1": {"center": {}}},
            frame_ids=[uuid4()],
            source="manual_4d",
        )
    )
    assert all(isinstance(key, str) for key in annotation.frame_data)
    assert all(isinstance(value, str) for value in annotation.frame_ids)


def test_build_fusion_derives_verified_and_normalizes_2d_projections():
    annotation = AnnotationService.build_fusion(
        AnnotationFusionCreate(
            task_id=TASK_ID,
            frame_id=FRAME_ID,
            class_id="car",
            data_3d={"center": {}},
            data_2d={"cam0": Annotation2DProjection()},
            source="manual_fusion",
        )
    )
    assert annotation.is_verified is True
    assert isinstance(annotation.data_2d["cam0"], dict)
    assert annotation.data_2d["cam0"]["visibility"] == 1.0


@pytest.mark.asyncio
async def test_maybe_start_work_skips_non_pending_tasks():
    service = AnnotationService(MagicMock())
    task = Task(status=TaskStatus.IN_PROGRESS.value)
    assert await service.maybe_start_work(task, uuid4()) is False
