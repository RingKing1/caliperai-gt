"""Task lifecycle, workflow and editor-context API schemas."""
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.catalog import DatasetResponse, TaxonomyResponse
from app.schemas.common import (
    AnnotationType,
    BaseSchema,
    TaskStatus,
    TimestampSchema,
)
from app.schemas.scene import SceneResponse


class FrameRange(BaseSchema):
    """Frame range for a task."""
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end < self.start:
            raise ValueError("End frame must be >= start frame")
        return self


class TaskConfig(BaseSchema):
    """Task-specific configuration."""
    required_annotation_types: List[AnnotationType] = Field(default_factory=list)
    required_classes: List[str] = Field(default_factory=list)
    auto_annotation_enabled: bool = True
    quality_checks: List[str] = Field(default_factory=list)


class TaskBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    frame_range: FrameRange
    context_buffer_before: int = Field(default=5, ge=0)
    context_buffer_after: int = Field(default=5, ge=0)
    priority: int = Field(default=5, ge=1, le=10)
    deadline: Optional[datetime] = None
    config: TaskConfig = Field(default_factory=TaskConfig)
    stage: str = Field(default='annotation', description='Task workflow stage')


class TaskCreate(TaskBase):
    scene_id: UUID
    taxonomy_id: Optional[UUID] = Field(
        None, description='Taxonomy this task belongs to'
    )
    assignee_id: Optional[UUID] = Field(
        None,
        description=(
            'Optional assignee ID - task will start as assigned if provided'
        ),
    )


class TaskUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=10)
    deadline: Optional[datetime] = None
    config: Optional[TaskConfig] = None
    stage: Optional[str] = Field(None, description='Task workflow stage')
    revision_count: Optional[int] = Field(
        None, ge=0, description='Reset revision counter'
    )
    total_time_seconds: Optional[int] = Field(
        None, ge=0, description='Accumulated annotation time in seconds'
    )


class TaskAssignment(BaseSchema):
    """Task assignment request."""
    assignee_id: UUID


class TaskStatusUpdate(BaseSchema):
    """Task status update request."""
    status: TaskStatus
    review_notes: Optional[str] = None



class SubTaskRequest(BaseSchema):
    name: str
    frame_start: int
    frame_end: int


class SplitTaskRequest(BaseSchema):
    sub_tasks: list[SubTaskRequest] = Field(...)


class WorkflowTransitionRequest(BaseSchema):
    """Request to transition task status."""
    new_status: str = Field(..., description="New status to transition to")
    notes: Optional[str] = Field(None, description="Notes for the transition")


class WorkflowAssignRequest(BaseSchema):
    """Request to assign task to an annotator."""
    assignee_id: UUID


class WorkflowReviewerAssignRequest(BaseSchema):
    """Request to assign task to a QA reviewer."""
    reviewer_id: UUID


class WorkflowCustomerReviewerAssignRequest(BaseSchema):
    """Request to assign task to a customer reviewer."""
    customer_reviewer_id: UUID


class WorkflowQACompleteRequest(BaseSchema):
    """Request to complete QA review."""
    accepted: bool = Field(..., description="Whether the task passed QA")
    notes: Optional[str] = Field(None, description="Review notes")


class WorkflowSkipCustomerQARequest(BaseSchema):
    """Request to set skip_customer_qa flag."""
    skip: bool = Field(..., description="Whether to skip Customer QA")


class TaskStageHistoryResponse(BaseSchema):
    """Response for task stage history entry."""
    id: UUID
    task_id: UUID
    from_stage: str
    from_status: str
    to_stage: str
    to_status: str
    changed_by_id: Optional[UUID] = None
    reason: Optional[str] = None
    created_at: datetime


class TaskResponse(TaskBase, TimestampSchema):
    id: UUID
    scene_id: UUID
    taxonomy_id: Optional[UUID] = None
    taxonomy_name: Optional[str] = None
    taxonomy_annotation_mode: Optional[str] = None
    status: TaskStatus
    stage: str
    assignee_id: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    reviewer_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    customer_reviewer_id: Optional[UUID] = None
    customer_reviewed_at: Optional[datetime] = None
    customer_review_notes: Optional[str] = None
    skip_customer_qa: bool = False
    revision_count: int = 0
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    total_time_seconds: int = 0

    @model_validator(mode="before")
    @classmethod
    def convert_frame_range(cls, data):
        """Convert PostgreSQL range to FrameRange dict."""
        if hasattr(data, '__dict__'):
            data_dict = {}
            for key in [
                'id', 'scene_id', 'taxonomy_id', 'name', 'description',
                'status', 'stage', 'context_buffer_before', 'context_buffer_after',
                'priority', 'deadline', 'config', 'assignee_id',
                'assigned_at', 'reviewer_id', 'reviewed_at', 'review_notes',
                'customer_reviewer_id', 'customer_reviewed_at',
                'customer_review_notes', 'skip_customer_qa', 'revision_count',
                'started_at', 'submitted_at', 'total_time_seconds',
                'created_at', 'updated_at',
            ]:
                if hasattr(data, key):
                    data_dict[key] = getattr(data, key)

            if hasattr(data, 'frame_range') and data.frame_range is not None:
                fr = data.frame_range
                if hasattr(fr, 'lower') and hasattr(fr, 'upper'):
                    data_dict['frame_range'] = {'start': fr.lower, 'end': fr.upper - 1}
                else:
                    data_dict['frame_range'] = fr

            try:
                tax = getattr(data, 'taxonomy', None)
                if tax is not None:
                    data_dict['taxonomy_name'] = tax.name
                    data_dict['taxonomy_annotation_mode'] = tax.annotation_mode
            except Exception:
                pass

            return data_dict
        return data



class TaskEditorContextResponse(BaseSchema):
    """Aggregated bootstrap payload for the annotation editor.

    Replaces the frontend task -> scene -> dataset -> taxonomies request
    waterfall with a single round trip.
    """
    task: TaskResponse
    scene: SceneResponse
    dataset: DatasetResponse
    taxonomies: List[TaxonomyResponse] = Field(default_factory=list)
    primary_taxonomies: Dict[str, Optional[TaxonomyResponse]] = Field(
        default_factory=dict,
        description="Primary taxonomy per annotation mode (fusion_3d / 2d_only).",
    )
    selected_taxonomy: Optional[TaxonomyResponse] = None


# Workflow endpoint request/response models (moved from endpoints/workflow.py).
class StatusTransitionRequest(BaseModel):
    """Request to transition task status."""
    status: str
    reason: Optional[str] = None


class AssignmentRequest(BaseModel):
    """Request to assign a task."""
    user_id: str


class ReviewCompleteRequest(BaseModel):
    """Request to complete a review."""
    accepted: bool
    reason: Optional[str] = None


class TaskWorkflowInfo(BaseModel):
    """Current workflow state of a task."""
    task_id: str
    stage: str
    status: str
    assignee_id: Optional[str] = None
    reviewer_id: Optional[str] = None
    customer_reviewer_id: Optional[str] = None
    skip_customer_qa: bool
    revision_count: int
    available_transitions: List[str]


class StageHistoryItem(BaseModel):
    """Single history entry."""
    id: str
    from_stage: str
    from_status: str
    to_stage: str
    to_status: str
    changed_by_id: Optional[str] = None
    reason: Optional[str] = None
    created_at: str


class AssignmentHistoryItem(BaseModel):
    """Single assignment history entry."""
    id: str
    action: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    role: str
    stage: str
    changed_by_id: Optional[str] = None
    changed_by_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: str


class BulkAssignRequest(BaseModel):
    """Request for bulk task assignment."""
    task_ids: List[str]
    user_id: str


class BulkSubmitRequest(BaseModel):
    """Request for bulk task submission."""
    task_ids: List[str]


class BulkOperationResult(BaseModel):
    """Result of a bulk operation."""
    success_count: int
    failed_count: int
    tasks: List[TaskWorkflowInfo]


class SetStageRequest(BaseModel):
    """Request to forcefully set stage (admin override)."""
    stage: str
    reset_revision_count: bool = False

