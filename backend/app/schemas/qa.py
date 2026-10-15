"""Quality assurance review, annotation review, comment and suggestion schemas."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.common import BaseSchema, TimestampSchema


class QAReviewMode(str, Enum):
    VIEW_ONLY = "view_only"
    EDIT = "edit"
    SUGGEST = "suggest"


class QAReviewStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"


class ReviewVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"
    PENDING = "pending"


class SuggestionSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SuggestionType(str, Enum):
    SIZE_ANOMALY = "size_anomaly"
    POSITION_JUMP = "position_jump"
    ORIENTATION_FLIP = "orientation_flip"
    TRACK_DISCONTINUITY = "track_discontinuity"
    LOW_CONFIDENCE = "low_confidence"
    CLASS_MISMATCH = "class_mismatch"
    MISSING_ATTRIBUTES = "missing_attributes"
    AUTO_INTERPOLATED = "auto_interpolated"
    IMPORTED_UNCHECKED = "imported_unchecked"
    OCCLUSION_ISSUE = "occlusion_issue"
    GROUND_PLANE_MISALIGNMENT = "ground_plane_misalignment"
    TRACK_DIMENSION_INCONSISTENCY = "track_dimension_inconsistency"
    VELOCITY_OUTLIER = "velocity_outlier"
    HEADING_MOTION_MISMATCH = "heading_motion_mismatch"
    OVERLAPPING_CUBOIDS = "overlapping_cuboids"
    SHORT_TRACK = "short_track"
    ASPECT_RATIO_ANOMALY = "aspect_ratio_anomaly"
    STATIONARY_WITH_MOTION_CLASS = "stationary_with_motion_class"
    TRACK_GAP = "track_gap"
    TRACK_BOUNDARY_ISSUE = "track_boundary_issue"
    FALSE_NEGATIVE = "false_negative"


class QAReviewCreate(BaseSchema):
    """Start a new QA review session."""
    task_id: UUID
    mode: QAReviewMode = QAReviewMode.VIEW_ONLY
    review_stage: Optional[str] = None


class QAReviewUpdate(BaseSchema):
    """Update a QA review session."""
    status: Optional[QAReviewStatus] = None
    mode: Optional[QAReviewMode] = None


class QAReviewComplete(BaseSchema):
    """Complete a QA review session."""
    final_verdict: str = "completed"
    notes: Optional[str] = None


class QAReviewSummary(BaseSchema):
    """Summary statistics for a QA review."""
    approved: int = 0
    rejected: int = 0
    flagged: int = 0
    pending: int = 0
    total_annotations: int = 0
    suggestions_addressed: int = 0
    suggestions_dismissed: int = 0


class QAReviewResponse(TimestampSchema):
    """Response for a QA review session."""
    id: UUID
    task_id: UUID
    reviewer_id: Optional[UUID] = None
    reviewer_name: Optional[str] = None
    status: str
    mode: str
    review_stage: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    summary: Optional[QAReviewSummary] = None


class AnnotationReviewCreate(BaseSchema):
    """Review a specific annotation."""
    annotation_id: str
    annotation_table: str = "annotations"
    verdict: ReviewVerdict
    issue_types: Optional[List[str]] = None
    notes: Optional[str] = None
    frame_id: Optional[str] = None
    class_id: Optional[str] = None
    location_x: Optional[float] = None
    location_y: Optional[float] = None
    location_z: Optional[float] = None


class AnnotationReviewUpdate(BaseSchema):
    """Update an annotation review."""
    verdict: Optional[ReviewVerdict] = None
    issue_types: Optional[List[str]] = None
    notes: Optional[str] = None


class AnnotationReviewResponse(TimestampSchema):
    """Response for an annotation review."""
    id: UUID
    qa_review_id: UUID
    annotation_id: str
    annotation_table: str
    verdict: Optional[str] = None
    issue_types: Optional[List[str]] = None
    notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    frame_id: Optional[str] = None
    class_id: Optional[str] = None
    location_x: Optional[float] = None
    location_y: Optional[float] = None
    location_z: Optional[float] = None
    annotator_resolved: bool = False


class BulkAnnotationReviewCreate(BaseSchema):
    """Bulk review multiple annotations."""
    reviews: List[AnnotationReviewCreate]


class BulkAnnotationReviewResponse(BaseSchema):
    """Response for bulk annotation review."""
    success_count: int
    error_count: int
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class AnnotationCommentCreate(BaseSchema):
    """Create a comment on an annotation."""
    annotation_id: str
    annotation_table: str = "annotations"
    content: str
    parent_id: Optional[UUID] = None


class AnnotationCommentUpdate(BaseSchema):
    """Update a comment."""
    content: Optional[str] = None


class AnnotationCommentResponse(TimestampSchema):
    """Response for an annotation comment."""
    id: UUID
    annotation_id: str
    annotation_table: str
    user_id: Optional[UUID] = None
    user_name: Optional[str] = None
    parent_id: Optional[UUID] = None
    content: str
    is_resolved: bool
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    replies: List["AnnotationCommentResponse"] = Field(default_factory=list)


class ResolveCommentRequest(BaseSchema):
    """Resolve a comment thread."""
    is_resolved: bool = True


class QASuggestionCreate(BaseSchema):
    """Create a QA suggestion (typically auto-generated)."""
    task_id: UUID
    annotation_id: Optional[str] = None
    annotation_table: Optional[str] = None
    frame_id: Optional[str] = None
    suggestion_type: SuggestionType
    severity: SuggestionSeverity = SuggestionSeverity.MEDIUM
    message: str
    details: Optional[Dict[str, Any]] = None


class QASuggestionResponse(BaseSchema):
    """Response for a QA suggestion."""
    id: UUID
    task_id: UUID
    annotation_id: Optional[str] = None
    annotation_table: Optional[str] = None
    frame_id: Optional[str] = None
    suggestion_type: str
    severity: str
    message: str
    details: Optional[Dict[str, Any]] = None
    is_dismissed: bool
    dismissed_by: Optional[UUID] = None
    dismissed_at: Optional[datetime] = None
    created_at: datetime


class DismissSuggestionRequest(BaseSchema):
    """Dismiss a QA suggestion."""
    reason: Optional[str] = None


class GenerateSuggestionsRequest(BaseSchema):
    """Request to generate AI suggestions for a task."""
    task_id: UUID
    regenerate: bool = False
    check_types: Optional[List[SuggestionType]] = None


class GenerateSuggestionsResponse(BaseSchema):
    """Response for suggestion generation."""
    task_id: UUID
    suggestions_count: int
    by_severity: Dict[str, int]
    by_type: Dict[str, int]


class CreateManualSuggestionRequest(BaseSchema):
    """Create a manual QA suggestion (e.g., false negative flag)."""
    task_id: UUID
    frame_id: UUID
    suggestion_type: SuggestionType = SuggestionType.FALSE_NEGATIVE
    severity: Optional[str] = "high"
    message: str
    details: Optional[Dict[str, Any]] = None
    location: Optional[Dict[str, float]] = None
    suggested_class: Optional[str] = None


class QATaskStats(BaseSchema):
    """QA statistics for a task."""
    task_id: UUID
    total_annotations: int
    reviewed_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    flagged_count: int
    suggestions_count: int
    suggestions_dismissed: int
    comment_count: int
    unresolved_comments: int
    review_progress_percent: float
    has_active_review: bool
    active_review_id: Optional[UUID] = None


AnnotationCommentResponse.model_rebuild()
