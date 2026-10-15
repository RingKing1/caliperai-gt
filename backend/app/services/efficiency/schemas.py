"""Request/response models for the efficiency domain.

Moved verbatim from ``app/api/v1/endpoints/efficiency.py`` so the service
package owns the contracts. Class names are unchanged, keeping the OpenAPI
component schemas identical.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ClientInfo(BaseModel):
    """Client browser/device information."""
    browser: Optional[str] = None
    os: Optional[str] = None
    screen_resolution: Optional[str] = None
    timezone: Optional[str] = None


class SessionStartRequest(BaseModel):
    """Request to start a new session."""
    task_id: UUID
    client_info: Optional[ClientInfo] = None


class SessionStartResponse(BaseModel):
    """Response after starting a session."""
    session_id: UUID
    started_at: datetime
    message: str


class HeartbeatRequest(BaseModel):
    """Heartbeat to keep session alive."""
    session_id: UUID
    is_active: bool = True
    current_frame: Optional[int] = None
    

class HeartbeatResponse(BaseModel):
    """Response to heartbeat."""
    session_id: UUID
    active_duration_seconds: int
    idle_duration_seconds: int
    is_idle: bool


class SessionEndRequest(BaseModel):
    """Request to end a session."""
    session_id: UUID
    

class SessionEndResponse(BaseModel):
    """Response after ending a session."""
    session_id: UUID
    total_active_seconds: int
    total_idle_seconds: int
    action_count: int



class LoginSessionStartRequest(BaseModel):
    """Request to start a global login session."""
    organization_id: Optional[UUID] = None
    client_info: Optional[ClientInfo] = None


class LoginSessionStartResponse(BaseModel):
    """Response after starting a login session."""
    session_id: UUID
    started_at: datetime
    message: str


class LoginSessionHeartbeatRequest(BaseModel):
    """Heartbeat for global login session."""
    session_id: UUID
    is_window_focused: bool = True
    is_mouse_in_window: bool = True
    is_active: bool = True


class LoginSessionHeartbeatResponse(BaseModel):
    """Response to login session heartbeat."""
    session_id: UUID
    active_duration_seconds: int
    idle_duration_seconds: int
    total_session_seconds: int
    today_active_seconds: int = 0


class LoginSessionEndRequest(BaseModel):
    """Request to end a login session."""
    session_id: UUID


class LoginSessionEndResponse(BaseModel):
    """Response after ending a login session."""
    session_id: UUID
    total_active_seconds: int
    total_idle_seconds: int
    total_session_seconds: int


class ActivityEventRequest(BaseModel):
    """Request to log an activity event."""
    session_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    event_type: str
    metadata: Optional[dict] = Field(default_factory=dict)


class ActivityEventResponse(BaseModel):
    """Response after logging activity."""
    event_id: UUID
    timestamp: datetime


class BatchActivityRequest(BaseModel):
    """Batch multiple activity events."""
    session_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    events: List[ActivityEventRequest]


class UserGoalCreate(BaseModel):
    """Create a new goal."""
    goal_type: str
    target_value: float
    period_start: datetime
    period_end: datetime


class UserGoalResponse(BaseModel):
    """User goal with progress."""
    id: UUID
    goal_type: str
    target_value: float
    current_value: float
    period_start: datetime
    period_end: datetime
    is_achieved: bool
    achieved_at: Optional[datetime]
    progress_percentage: float
    is_self_assigned: bool


class AchievementResponse(BaseModel):
    """Achievement earned by user."""
    id: UUID
    achievement_type: str
    earned_at: datetime
    metadata: dict
    is_seen: bool
    title: str
    description: str
    icon: str


class LiveUserStatus(BaseModel):
    """Real-time status of a user."""
    user_id: UUID
    display_name: str
    current_task_id: Optional[UUID] = None
    current_task_name: Optional[str] = None
    is_active: bool
    last_activity: Optional[datetime] = None
    session_duration_seconds: int = 0
    labels_today: int = 0


class AnnotationBreakdown(BaseModel):
    """Breakdown of annotations by type."""
    cuboids_3d: int = 0
    boxes_2d: int = 0
    fusion: int = 0
    total: int = 0


class WorkflowMetrics(BaseModel):
    """Task workflow metrics."""
    tasks_assigned: int = 0
    tasks_in_progress: int = 0
    tasks_submitted: int = 0
    tasks_accepted: int = 0
    tasks_rejected: int = 0
    revision_count: int = 0


class QualityMetrics(BaseModel):
    """Quality metrics for a user."""
    first_time_acceptance_rate: float = 0.0
    rejection_rate: float = 0.0
    revision_turnaround_hours: float = 0.0
    quality_score: float = 0.0


class TeamMemberStats(BaseModel):
    """Team member statistics for efficiency dashboard."""
    user_id: UUID
    display_name: str
    email: Optional[str] = None
    role: Optional[str] = None
    
    is_online: bool = False
    is_active: bool = False
    current_task_id: Optional[UUID] = None
    current_task_name: Optional[str] = None
    last_activity: Optional[datetime] = None
    session_duration_seconds: int = 0
    
    annotations: AnnotationBreakdown = AnnotationBreakdown()
    
    workflow: WorkflowMetrics = WorkflowMetrics()
    
    quality: QualityMetrics = QualityMetrics()
    
    active_time_seconds: int = 0
    labels_per_hour: float = 0.0
    avg_time_per_label_seconds: float = 0.0
    
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class LeaderboardEntry(BaseModel):
    """Entry in leaderboard."""
    rank: int
    user_id: UUID
    display_name: str
    labels_count: int
    acceptance_rate: float
    avg_time_per_label_seconds: float
    streak_days: int


class TeamChallengeResponse(BaseModel):
    """Team challenge details."""
    id: UUID
    title: str
    description: Optional[str]
    goal_type: str
    target_value: float
    current_value: float
    progress_percentage: float
    start_date: datetime
    end_date: datetime
    is_active: bool
    is_completed: bool
    participant_count: int
    top_contributors: List[LeaderboardEntry]


class CreateChallengeRequest(BaseModel):
    """Request to create a team challenge."""
    title: str
    description: Optional[str] = None
    goal_type: str
    target_value: float
    start_date: datetime
    end_date: datetime
    organization_id: Optional[UUID] = None


class PerformanceAlertResponse(BaseModel):
    """Performance alert for managers."""
    id: UUID
    user_id: UUID
    display_name: str
    alert_type: str
    severity: str
    title: str
    message: str
    metrics: dict
    is_acknowledged: bool
    created_at: datetime


class EfficiencyStats(BaseModel):
    """Personal efficiency statistics."""
    today_labels: int
    today_active_time_seconds: int
    today_sessions: int
    week_labels: int
    week_active_time_seconds: int
    labels_per_hour: float
    acceptance_rate: Optional[float] = None
    current_streak_days: int
    rank_in_team: Optional[int] = None
    vs_team_avg_percentage: float

