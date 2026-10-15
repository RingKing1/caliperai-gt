"""Enums for the efficiency sub-domain models."""
from enum import Enum


class ActivityEventType(str, Enum):
    """Types of user activity events for tracking engagement."""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SESSION_PAUSE = "session_pause"
    SESSION_RESUME = "session_resume"
    ANNOTATION_CREATE = "annotation_create"
    ANNOTATION_UPDATE = "annotation_update"
    ANNOTATION_DELETE = "annotation_delete"
    FRAME_CHANGE = "frame_change"
    CAMERA_SWITCH = "camera_switch"
    TOOL_CHANGE = "tool_change"
    TASK_OPEN = "task_open"
    TASK_CLOSE = "task_close"
    TASK_SUBMIT = "task_submit"
    ZOOM_CHANGE = "zoom_change"
    VIEW_MODE_CHANGE = "view_mode_change"


class AchievementType(str, Enum):
    """Types of achievements users can earn."""
    SPEED_DEMON = "speed_demon"
    LIGHTNING_FAST = "lightning_fast"
    QUALITY_CHAMPION = "quality_champion"
    PERFECTIONIST = "perfectionist"
    ZERO_DEFECT = "zero_defect"
    CONSISTENCY_STAR = "consistency_star"
    MARATHON_RUNNER = "marathon_runner"
    DEDICATED = "dedicated"
    CENTURY_CLUB = "century_club"
    THOUSAND_LABELS = "thousand_labels"
    MILESTONE_5K = "milestone_5k"
    ON_THE_RISE = "on_the_rise"
    COMEBACK_KID = "comeback_kid"


class AlertSeverity(str, Enum):
    """Severity levels for performance alerts."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of performance alerts."""
    VELOCITY_DROP = "velocity_drop"
    HIGH_REJECTION_RATE = "high_rejection_rate"
    TASK_OVERDUE = "task_overdue"
    LONG_IDLE = "long_idle"
    GOAL_AT_RISK = "goal_at_risk"
    TASK_STUCK = "task_stuck"


class GoalType(str, Enum):
    """Types of user goals."""
    DAILY_LABELS = "daily_labels"
    WEEKLY_LABELS = "weekly_labels"
    DAILY_HOURS = "daily_hours"
    WEEKLY_TASKS = "weekly_tasks"
    ACCEPTANCE_RATE = "acceptance_rate"
