"""Unit tests for the pure rules in :mod:`app.services.dataset_service`."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.dataset_service import (
    CampaignNotFoundError,
    DatasetNotFoundError,
    TaxonomyNotFoundError,
    compute_dataset_stats,
    make_scene_taxonomy_task,
)


def _scene(frame_count, task_statuses):
    tasks = [MagicMock(status=s) for s in task_statuses]
    return MagicMock(frame_count=frame_count, tasks=tasks, id="scene-1", name="S1")


def test_compute_dataset_stats_counts_frames_and_task_states():
    scenes = [
        _scene(10, ["pending", "in_progress"]),
        _scene(5, ["completed", "completed", "weird"]),
    ]
    stats = compute_dataset_stats(scenes)
    assert stats == {
        "scene_count": 2,
        "total_frames": 15,
        "total_tasks": 5,
        "pending_tasks": 1,
        "in_progress_tasks": 1,
        "completed_tasks": 2,
    }


def test_compute_dataset_stats_empty():
    assert compute_dataset_stats([]) == {
        "scene_count": 0,
        "total_frames": 0,
        "total_tasks": 0,
        "pending_tasks": 0,
        "in_progress_tasks": 0,
        "completed_tasks": 0,
    }


def test_make_scene_taxonomy_task_fields():
    scene = SimpleNamespace(id="scene-1", name="Scene A", frame_count=100)
    task = make_scene_taxonomy_task(scene, "tax-1", "Cars")
    assert task.scene_id == "scene-1"
    assert task.taxonomy_id == "tax-1"
    assert task.name == "Scene A - Cars"
    assert task.status == "pending"
    assert task.stage == "annotation"
    assert (task.frame_range.lower, task.frame_range.upper) == (0, 100)


def test_domain_error_messages():
    assert str(DatasetNotFoundError("d1")) == "Dataset d1 not found"
    assert str(CampaignNotFoundError("c1")) == "Campaign c1 not found"
    assert str(TaxonomyNotFoundError("t1")) == "Taxonomy t1 not found"
