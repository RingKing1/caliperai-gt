"""DataOps API schemas: annotation history, stage snapshots and stats."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AnnotationHistoryResponse(BaseModel):
    """Response for a single annotation history entry."""
    id: str
    annotation_id: str
    task_id: str
    frame_id: str
    change_type: str
    annotation_data: Dict[str, Any]
    previous_data: Optional[Dict[str, Any]] = None
    task_stage: str
    task_status: str
    changed_by_id: Optional[str] = None
    version: int
    created_at: str


class AnnotationHistoryListResponse(BaseModel):
    """Paginated list of annotation history."""
    items: List[AnnotationHistoryResponse]
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
    annotations_by_class: Dict[str, int]
    annotations_by_type: Dict[str, int]
    triggered_by_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class SnapshotDetailResponse(SnapshotSummaryResponse):
    """Full snapshot including annotation data."""
    annotations_by_frame: Dict[str, int]
    annotations_snapshot: Dict[str, Any]


class SnapshotListResponse(BaseModel):
    """Paginated list of snapshots."""
    items: List[SnapshotSummaryResponse]
    total: int
    limit: int
    offset: int


class TaskDataOpsStats(BaseModel):
    """DataOps statistics for a task."""
    total_changes: int
    changes_by_type: Dict[str, int]
    created_count: int
    updated_count: int
    deleted_count: int
    snapshot_count: int
    latest_snapshot: Optional[Dict[str, Any]] = None


class DatasetDataOpsStats(BaseModel):
    """DataOps statistics for a dataset."""
    total_changes: int
    changes_by_type: Dict[str, int]
    total_snapshots: int
    tasks_with_history: int
    total_tasks: int


class SnapshotCompareResponse(BaseModel):
    """Comparison between two snapshots."""
    snapshot_1: Dict[str, Any]
    snapshot_2: Dict[str, Any]
    added: List[Dict[str, Any]]
    removed: List[Dict[str, Any]]
    modified: List[Dict[str, Any]]
    summary: Dict[str, int]
