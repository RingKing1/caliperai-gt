"""
SQLAlchemy models for the Sensor Fusion Annotation Platform.

Database Hierarchy:
Campaign → Dataset → Scene → Task → Annotation

Model classes live in domain modules under app/models/ (base, enums, org, user,
catalog, scene, task, annotation, qa, efficiency, chat). This module is a facade
re-exporting every public name, so existing imports keep working unchanged:
    from app.models.models import Task, User, ...
"""

from app.core.database import Base
from app.models.annotation import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationChangeType,
    AnnotationFusion,
    AnnotationHistory,
    SegmentationBlob,
    Track2D,
    Track3DRefinement,
)
from app.models.base import (
    SoftDeleteMixin,
    TimestampMixin,
)
from app.models.catalog import (
    Campaign,
    Dataset,
    ImportJob,
    Taxonomy,
    dataset_taxonomy_association,
)
from app.models.chat import (
    ChatMessage,
    ChatSession,
    KnowledgeChunk,
)
from app.models.efficiency import (
    Achievement,
    ActivityEvent,
    ChallengeParticipant,
    DailyUserStats,
    PerformanceAlert,
    TeamChallenge,
    TimeSession,
    UserGoal,
    UserLoginSession,
)
from app.models.enums import (
    ROLE_PERMISSIONS,
    AchievementType,
    ActivityEventType,
    AlertSeverity,
    AlertType,
    AnnotationSource,
    AnnotationType,
    ChatMessageFeedback,
    ChatMessageRole,
    GoalType,
    OrganizationRole,
    Permission,
    QAReviewMode,
    QAReviewStatus,
    ReviewVerdict,
    SuggestionSeverity,
    TaskStage,
    TaskStatus,
    TaxonomyAnnotationMode,
    UserRole,
)
from app.models.org import (
    Organization,
    OrganizationMember,
)
from app.models.qa import (
    AnnotationComment,
    AnnotationReview,
    QAReview,
    QASuggestion,
)
from app.models.scene import (
    Frame,
    Scene,
)
from app.models.task import (
    StageSnapshot,
    Task,
    TaskAssignmentHistory,
    TaskStageHistory,
)
from app.models.user import (
    AuditLog,
    User,
    UserSSOIdentity,
)

__all__ = [
    "Base",
    "Annotation",
    "Annotation2D",
    "Annotation3D",
    "Annotation4D",
    "AnnotationChangeType",
    "AnnotationFusion",
    "AnnotationHistory",
    "SegmentationBlob",
    "Track2D",
    "Track3DRefinement",
    "SoftDeleteMixin",
    "TimestampMixin",
    "Campaign",
    "Dataset",
    "ImportJob",
    "Taxonomy",
    "dataset_taxonomy_association",
    "ChatMessage",
    "ChatSession",
    "KnowledgeChunk",
    "Achievement",
    "ActivityEvent",
    "ChallengeParticipant",
    "DailyUserStats",
    "PerformanceAlert",
    "TeamChallenge",
    "TimeSession",
    "UserGoal",
    "UserLoginSession",
    "ROLE_PERMISSIONS",
    "AchievementType",
    "ActivityEventType",
    "AlertSeverity",
    "AlertType",
    "AnnotationSource",
    "AnnotationType",
    "ChatMessageFeedback",
    "ChatMessageRole",
    "GoalType",
    "OrganizationRole",
    "Permission",
    "QAReviewMode",
    "QAReviewStatus",
    "ReviewVerdict",
    "SuggestionSeverity",
    "TaskStage",
    "TaskStatus",
    "TaxonomyAnnotationMode",
    "UserRole",
    "Organization",
    "OrganizationMember",
    "AnnotationComment",
    "AnnotationReview",
    "QAReview",
    "QASuggestion",
    "Frame",
    "Scene",
    "StageSnapshot",
    "Task",
    "TaskAssignmentHistory",
    "TaskStageHistory",
    "AuditLog",
    "User",
    "UserSSOIdentity",
]
