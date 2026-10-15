"""Shared enumerations and role-permission mapping for ORM models."""
from enum import Enum


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TaskStage(str, Enum):
    """Task workflow stages."""
    ANNOTATION = "annotation"
    QA = "qa"
    CUSTOMER_QA = "customer_qa"
    ACCEPTED = "accepted"


class AnnotationType(str, Enum):
    """Types of annotations supported."""
    CUBOID = "cuboid"
    BOX2D = "box2d"
    POLYLINE = "polyline"
    POLYGON = "polygon"
    KEYPOINTS = "keypoints"
    SEGMENTATION_3D = "segmentation_3d"
    SEGMENTATION_2D = "segmentation_2d"


class AnnotationSource(str, Enum):
    """Source of annotation creation."""
    MANUAL = "manual"
    AUTO = "auto"
    AUTO_INTERPOLATED = "auto_interpolated"
    AIRFLOW_MODEL_V1 = "airflow_model_v1"
    AIRFLOW_MODEL_V2 = "airflow_model_v2"


class TaxonomyAnnotationMode(str, Enum):
    """Annotation mode that a taxonomy supports."""
    FUSION_3D = "fusion_3d"
    ONLY_2D = "2d_only"
    SEGMENTATION_3D = "segmentation_3d"


class UserRole(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    ANNOTATOR = "annotator"
    QA_REVIEWER = "qa_reviewer"
    CUSTOMER_QA = "customer_qa"


class Permission(str, Enum):
    """
    Fine-grained permissions for RBAC.
    Format: {resource}:{action}
    """
    USERS_CREATE = "users:create"
    USERS_READ = "users:read"
    USERS_READ_ALL = "users:read_all"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    USERS_ASSIGN_ROLE = "users:assign_role"

    CAMPAIGNS_CREATE = "campaigns:create"
    CAMPAIGNS_READ = "campaigns:read"
    CAMPAIGNS_READ_ALL = "campaigns:read_all"
    CAMPAIGNS_UPDATE = "campaigns:update"
    CAMPAIGNS_DELETE = "campaigns:delete"

    DATASETS_CREATE = "datasets:create"
    DATASETS_READ = "datasets:read"
    DATASETS_READ_ALL = "datasets:read_all"
    DATASETS_UPDATE = "datasets:update"
    DATASETS_DELETE = "datasets:delete"
    DATASETS_IMPORT = "datasets:import"

    SCENES_CREATE = "scenes:create"
    SCENES_READ = "scenes:read"
    SCENES_READ_ALL = "scenes:read_all"
    SCENES_UPDATE = "scenes:update"
    SCENES_DELETE = "scenes:delete"

    TAXONOMIES_CREATE = "taxonomies:create"
    TAXONOMIES_READ = "taxonomies:read"
    TAXONOMIES_UPDATE = "taxonomies:update"
    TAXONOMIES_DELETE = "taxonomies:delete"

    TASKS_CREATE = "tasks:create"
    TASKS_READ = "tasks:read"
    TASKS_READ_ALL = "tasks:read_all"
    TASKS_READ_ASSIGNED = "tasks:read_assigned"
    TASKS_UPDATE = "tasks:update"
    TASKS_DELETE = "tasks:delete"
    TASKS_ASSIGN = "tasks:assign"
    TASKS_START = "tasks:start"
    TASKS_SUBMIT = "tasks:submit"

    ANNOTATIONS_CREATE = "annotations:create"
    ANNOTATIONS_READ = "annotations:read"
    ANNOTATIONS_UPDATE = "annotations:update"
    ANNOTATIONS_DELETE = "annotations:delete"

    QA_REVIEW = "qa:review"
    QA_ACCEPT = "qa:accept"
    QA_REJECT = "qa:reject"
    QA_ISSUES_CREATE = "qa:issues_create"
    QA_ISSUES_READ = "qa:issues_read"

    CUSTOMER_QA_REVIEW = "customer_qa:review"
    CUSTOMER_QA_ACCEPT = "customer_qa:accept"
    CUSTOMER_QA_REJECT = "customer_qa:reject"

    DASHBOARD_VIEW_GLOBAL = "dashboard:view_global"
    DASHBOARD_VIEW_TEAM = "dashboard:view_team"
    DASHBOARD_VIEW_OWN = "dashboard:view_own"
    REPORTS_EXPORT = "reports:export"

    ORGANIZATIONS_CREATE = "organizations:create"
    ORGANIZATIONS_READ = "organizations:read"
    ORGANIZATIONS_UPDATE = "organizations:update"
    ORGANIZATIONS_DELETE = "organizations:delete"
    ORGANIZATIONS_MANAGE_MEMBERS = "organizations:manage_members"

    SYSTEM_CONFIG = "system:config"
    SYSTEM_AUDIT_LOGS = "system:audit_logs"


ROLE_PERMISSIONS: dict[str, set[str]] = {
    UserRole.ADMIN.value: {p.value for p in Permission},

    UserRole.PROJECT_MANAGER.value: {
        Permission.USERS_CREATE.value,
        Permission.USERS_READ.value,
        Permission.USERS_READ_ALL.value,
        Permission.USERS_UPDATE.value,
        Permission.USERS_DELETE.value,
        Permission.USERS_ASSIGN_ROLE.value,
        Permission.CAMPAIGNS_CREATE.value,
        Permission.CAMPAIGNS_READ.value,
        Permission.CAMPAIGNS_READ_ALL.value,
        Permission.CAMPAIGNS_UPDATE.value,
        Permission.CAMPAIGNS_DELETE.value,
        Permission.DATASETS_CREATE.value,
        Permission.DATASETS_READ.value,
        Permission.DATASETS_READ_ALL.value,
        Permission.DATASETS_UPDATE.value,
        Permission.DATASETS_DELETE.value,
        Permission.DATASETS_IMPORT.value,
        Permission.SCENES_CREATE.value,
        Permission.SCENES_READ.value,
        Permission.SCENES_READ_ALL.value,
        Permission.SCENES_UPDATE.value,
        Permission.SCENES_DELETE.value,
        Permission.TAXONOMIES_CREATE.value,
        Permission.TAXONOMIES_READ.value,
        Permission.TAXONOMIES_UPDATE.value,
        Permission.TAXONOMIES_DELETE.value,
        Permission.TASKS_CREATE.value,
        Permission.TASKS_READ.value,
        Permission.TASKS_READ_ALL.value,
        Permission.TASKS_READ_ASSIGNED.value,
        Permission.TASKS_UPDATE.value,
        Permission.TASKS_DELETE.value,
        Permission.TASKS_ASSIGN.value,
        Permission.TASKS_START.value,
        Permission.TASKS_SUBMIT.value,
        Permission.ANNOTATIONS_CREATE.value,
        Permission.ANNOTATIONS_READ.value,
        Permission.ANNOTATIONS_UPDATE.value,
        Permission.ANNOTATIONS_DELETE.value,
        Permission.QA_REVIEW.value,
        Permission.QA_ACCEPT.value,
        Permission.QA_REJECT.value,
        Permission.QA_ISSUES_CREATE.value,
        Permission.QA_ISSUES_READ.value,
        Permission.CUSTOMER_QA_REVIEW.value,
        Permission.CUSTOMER_QA_ACCEPT.value,
        Permission.CUSTOMER_QA_REJECT.value,
        Permission.DASHBOARD_VIEW_GLOBAL.value,
        Permission.DASHBOARD_VIEW_TEAM.value,
        Permission.DASHBOARD_VIEW_OWN.value,
        Permission.REPORTS_EXPORT.value,
        Permission.ORGANIZATIONS_READ.value,
        Permission.ORGANIZATIONS_UPDATE.value,
        Permission.ORGANIZATIONS_MANAGE_MEMBERS.value,
        Permission.SYSTEM_AUDIT_LOGS.value,
    },

    UserRole.ANNOTATOR.value: {
        Permission.CAMPAIGNS_READ.value,
        Permission.DATASETS_READ.value,
        Permission.SCENES_READ.value,
        Permission.TAXONOMIES_READ.value,
        Permission.TASKS_READ_ASSIGNED.value,
        Permission.TASKS_START.value,
        Permission.TASKS_SUBMIT.value,
        Permission.ANNOTATIONS_CREATE.value,
        Permission.ANNOTATIONS_READ.value,
        Permission.ANNOTATIONS_UPDATE.value,
        Permission.ANNOTATIONS_DELETE.value,
        Permission.QA_ISSUES_READ.value,
        Permission.DASHBOARD_VIEW_OWN.value,
    },

    UserRole.QA_REVIEWER.value: {
        Permission.CAMPAIGNS_READ.value,
        Permission.DATASETS_READ.value,
        Permission.SCENES_READ.value,
        Permission.TAXONOMIES_READ.value,
        Permission.TASKS_READ_ASSIGNED.value,
        Permission.TASKS_START.value,
        Permission.ANNOTATIONS_READ.value,
        Permission.QA_REVIEW.value,
        Permission.QA_ACCEPT.value,
        Permission.QA_REJECT.value,
        Permission.QA_ISSUES_CREATE.value,
        Permission.QA_ISSUES_READ.value,
        Permission.DASHBOARD_VIEW_OWN.value,
    },

    UserRole.CUSTOMER_QA.value: {
        Permission.CAMPAIGNS_READ.value,
        Permission.DATASETS_READ.value,
        Permission.SCENES_READ.value,
        Permission.TAXONOMIES_READ.value,
        Permission.TASKS_READ_ASSIGNED.value,
        Permission.ANNOTATIONS_READ.value,
        Permission.CUSTOMER_QA_REVIEW.value,
        Permission.CUSTOMER_QA_ACCEPT.value,
        Permission.CUSTOMER_QA_REJECT.value,
        Permission.QA_ISSUES_CREATE.value,
        Permission.QA_ISSUES_READ.value,
        Permission.DASHBOARD_VIEW_OWN.value,
    },
}


class OrganizationRole(str, Enum):
    """Roles within an organization."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


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
