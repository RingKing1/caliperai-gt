"""PM dashboard / annotator analytics response schemas."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class AnnotatorStats(BaseModel):
    """Statistics for a single annotator."""
    id: str
    alias: str
    tasks_completed: int
    tasks_in_progress: int
    tasks_assigned: int
    total_time_seconds: int
    avg_time_per_task_seconds: float
    revision_rate: float
    frames_annotated: int


class TaskBreakdown(BaseModel):
    """Task count breakdown by status."""
    pending: int
    assigned: int
    in_progress: int
    submitted: int
    accepted: int
    rejected: int
    total: int


class AnnotationDailyStats(BaseModel):
    """Daily annotation statistics."""
    date: str
    created_count: int
    submitted_count: int
    accepted_count: int


class UserDailyStats(BaseModel):
    """Daily statistics for a specific user."""
    date: str
    labels_created: int
    labels_submitted: int
    labels_accepted: int
    labels_rejected: int
    man_hours: float


class MyDashboardStats(BaseModel):
    """Personal dashboard statistics for an annotator."""
    daily_stats: List[UserDailyStats]
    total_labels_created: int
    total_labels_submitted: int
    acceptance_rate: float
    total_man_hours: float


class StageBreakdown(BaseModel):
    """Task count breakdown by stage."""
    annotation: int
    qa: int
    customer_qa: int
    accepted: int


class MostTimeConsumingTask(BaseModel):
    """Details of the most time-consuming task."""
    task_id: str
    task_name: str
    scene_name: str
    dataset_name: str
    total_time_seconds: int
    total_time_formatted: str
    frame_count: int
    annotator_alias: Optional[str] = None


class RecentActivity(BaseModel):
    """Recent task activity."""
    task_id: str
    task_name: str
    action: str
    annotator_alias: Optional[str] = None
    timestamp: datetime


class EfficiencyMetrics(BaseModel):
    """Efficiency metrics for the project."""
    avg_time_per_task_seconds: float
    avg_time_per_frame_seconds: float
    avg_revisions_per_task: float
    first_time_accept_rate: float
    tasks_completed_last_7_days: int
    tasks_completed_last_30_days: int
    velocity_trend: str


class PMDashboardStats(BaseModel):
    """Complete PM Dashboard statistics."""
    task_breakdown: TaskBreakdown
    stage_breakdown: StageBreakdown
    completion_rate: float

    efficiency: EfficiencyMetrics

    top_annotators: List[AnnotatorStats]

    most_time_consuming_task: Optional[MostTimeConsumingTask] = None
    recent_activity: List[RecentActivity]

    overdue_tasks: int
    tasks_due_this_week: int

    generated_at: datetime
