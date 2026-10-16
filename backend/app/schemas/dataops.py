"""DataOps API schemas: annotation history, stage snapshots and stats."""
from typing import Any

from pydantic import BaseModel


class AnnotationHistoryResponse(BaseModel):
    """Response for a single annotation history entry."""
    id: str
    annotation_id: str
    task_id: str
    frame_id: str
    change_type: str
    annotation_data: dict[str, Any]
    previous_data: dict[str, Any] | None = None
    task_stage: str
    task_status: str
    changed_by_id: str | None = None
    version: int
    created_at: str


class AnnotationHistoryListResponse(BaseModel):
    """Paginated list of annotation history."""
    items: list[AnnotationHistoryResponse]
    total: int
    limit: int
    offset: int


class SnapshotSummaryResponse(BaseModel):
    """Summary of a stage snapshot (without full annotation data)."""
    id: str
    task_id: str
    from_stage: str
    to_stage: str
    from_status: str
    to_status: str
    snapshot_name: str
    total_annotations: int
    annotations_by_class: dict[str, int]
    annotations_by_type: dict[str, int]
    triggered_by_id: str | None = None
    notes: str | None = None
    created_at: str


class SnapshotDetailResponse(SnapshotSummaryResponse):
    """Full snapshot including annotation data."""
    annotations_by_frame: dict[str, int]
    annotations_snapshot: dict[str, Any]


class SnapshotListResponse(BaseModel):
    """Paginated list of snapshots."""
    items: list[SnapshotSummaryResponse]
    total: int
    limit: int
    offset: int


class TaskDataOpsStats(BaseModel):
    """DataOps statistics for a task."""
    total_changes: int
    changes_by_type: dict[str, int]
    created_count: int
    updated_count: int
    deleted_count: int
    snapshot_count: int
    latest_snapshot: dict[str, Any] | None = None


class DatasetDataOpsStats(BaseModel):
    """DataOps statistics for a dataset."""
    total_changes: int
    changes_by_type: dict[str, int]
    total_snapshots: int
    tasks_with_history: int
    total_tasks: int


class SnapshotCompareResponse(BaseModel):
    """Comparison between two snapshots."""
    snapshot_1: dict[str, Any]
    snapshot_2: dict[str, Any]
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    modified: list[dict[str, Any]]
    summary: dict[str, int]
