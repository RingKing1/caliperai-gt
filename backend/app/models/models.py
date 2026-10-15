"""
SQLAlchemy models for the Sensor Fusion Annotation Platform.

Database Hierarchy:
Campaign → Dataset → Scene → Task → Annotation

Each level inherits context from its parent and provides specific functionality.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY as PGARRAY,
)
from sqlalchemy.dialects.postgresql import (
    BYTEA,
    INT4RANGE,
    JSONB,
    UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin as SoftDeleteMixin
from app.models.base import TimestampMixin as TimestampMixin
from app.models.catalog import Campaign as Campaign
from app.models.catalog import Dataset as Dataset
from app.models.catalog import Taxonomy as Taxonomy
from app.models.catalog import (
    dataset_taxonomy_association as dataset_taxonomy_association,
)
from app.models.efficiency import Achievement as Achievement
from app.models.efficiency import ActivityEvent as ActivityEvent
from app.models.efficiency import ChallengeParticipant as ChallengeParticipant
from app.models.efficiency import DailyUserStats as DailyUserStats
from app.models.efficiency import PerformanceAlert as PerformanceAlert
from app.models.efficiency import TeamChallenge as TeamChallenge
from app.models.efficiency import TimeSession as TimeSession
from app.models.efficiency import UserGoal as UserGoal
from app.models.efficiency import UserLoginSession as UserLoginSession
from app.models.enums import (
    ROLE_PERMISSIONS as ROLE_PERMISSIONS,
)
from app.models.enums import AchievementType as AchievementType
from app.models.enums import ActivityEventType as ActivityEventType
from app.models.enums import AlertSeverity as AlertSeverity
from app.models.enums import AlertType as AlertType
from app.models.enums import (
    AnnotationSource as AnnotationSource,
)
from app.models.enums import (
    AnnotationType as AnnotationType,
)
from app.models.enums import GoalType as GoalType
from app.models.enums import (
    OrganizationRole as OrganizationRole,
)
from app.models.enums import (
    Permission as Permission,
)
from app.models.enums import (
    TaskStage as TaskStage,
)
from app.models.enums import (
    TaskStatus as TaskStatus,
)
from app.models.enums import (
    TaxonomyAnnotationMode as TaxonomyAnnotationMode,
)
from app.models.enums import (
    UserRole as UserRole,
)
from app.models.org import Organization as Organization
from app.models.org import OrganizationMember as OrganizationMember

# Re-exported for the module facade (zero import-path change for callers).
from app.models.scene import Frame as Frame
from app.models.scene import Scene as Scene
from app.models.user import User as User
from app.models.user import UserSSOIdentity as UserSSOIdentity


class Task(Base, TimestampMixin, SoftDeleteMixin):
    """
    Atomic unit of work assigned to annotators.
    Supports frame ranges with context buffers.
    """
    __tablename__ = "tasks"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    status: Mapped[str] = mapped_column(
        String(50),
        default=TaskStatus.PENDING.value,
        nullable=False,
    )
    
    stage: Mapped[str] = mapped_column(
        String(50),
        default=TaskStage.ANNOTATION.value,
        nullable=False,
    )
    
    frame_range: Mapped[Any] = mapped_column(INT4RANGE, nullable=False)
    
    context_buffer_before: Mapped[int] = mapped_column(Integer, default=5)
    context_buffer_after: Mapped[int] = mapped_column(Integer, default=5)
    
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    customer_reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    customer_review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    skip_customer_qa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    priority: Mapped[int] = mapped_column(Integer, default=5)
    deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Config schema:
    {
        "required_annotation_types": ["cuboid", "box2d"],
        "required_classes": ["car", "pedestrian", "cyclist"],
        "auto_annotation_enabled": true,
        "quality_checks": ["no_overlapping", "complete_tracking"]
    }
    """
    
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    
    scene: Mapped["Scene"] = relationship("Scene", back_populates="tasks")
    assignee: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="assigned_tasks",
        foreign_keys=[assignee_id],
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="reviewed_tasks",
        foreign_keys=[reviewer_id],
    )
    customer_reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[customer_reviewer_id],
    )
    annotations: Mapped[List["Annotation"]] = relationship(
        "Annotation",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    stage_history: Mapped[List["TaskStageHistory"]] = relationship(
        "TaskStageHistory",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStageHistory.created_at",
    )
    stage_snapshots: Mapped[List["StageSnapshot"]] = relationship(
        "StageSnapshot",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="StageSnapshot.created_at.desc()",
    )
    annotation_history: Mapped[List["AnnotationHistory"]] = relationship(
        "AnnotationHistory",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    assignment_history: Mapped[List["TaskAssignmentHistory"]] = relationship(
        "TaskAssignmentHistory",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskAssignmentHistory.created_at",
    )
    
    time_sessions: Mapped[List["TimeSession"]] = relationship(
        "TimeSession",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[List["ActivityEvent"]] = relationship(
        "ActivityEvent",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    performance_alerts: Mapped[List["PerformanceAlert"]] = relationship(
        "PerformanceAlert",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    
    taxonomy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    taxonomy: Mapped[Optional["Taxonomy"]] = relationship("Taxonomy", foreign_keys=[taxonomy_id])

    __table_args__ = (
        Index("ix_tasks_scene_id", "scene_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_stage", "stage"),
        Index("ix_tasks_assignee_id", "assignee_id"),
        Index("ix_tasks_priority", "priority"),
        CheckConstraint(
            "status IN ('pending', 'assigned', 'in_progress', 'submitted', 'accepted', 'rejected')",
            name="ck_task_status",
        ),
    )



class Annotation(Base, TimestampMixin):
    """
    Polymorphic annotation table supporting multiple annotation types.
    Uses JSONB for flexible data storage with Pydantic validation.
    """
    __tablename__ = "annotations"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("frames.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    track_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    Data schemas by type:
    
    CUBOID:
    {
        "center": {"x": 10.5, "y": 5.2, "z": 1.0},
        "dimensions": {"length": 4.5, "width": 2.0, "height": 1.5},
        "rotation": {"yaw": 0.5, "pitch": 0.0, "roll": 0.0},
        "confidence": 0.95
    }
    
    BOX2D:
    {
        "camera_id": "front_camera",
        "bbox": {"x": 100, "y": 200, "width": 150, "height": 100}
    }
    
    POLYLINE:
    {
        "camera_id": "front_camera",
        "points": [[100, 200], [150, 250], [200, 300]],
        "is_closed": false,
        "bezier": false
    }
    
    POLYGON:
    {
        "camera_id": "front_camera",
        "points": [[100, 200], [150, 250], [200, 300], [100, 300]]
    }
    
    KEYPOINTS:
    {
        "camera_id": "front_camera",
        "skeleton_id": "human_pose",
        "keypoints": {
            "nose": {"x": 500, "y": 200, "visibility": 2},
            "left_eye": {"x": 490, "y": 190, "visibility": 2},
            ...
        }
    }
    
    SEGMENTATION_3D:
    {
        "blob_url": "s3://bucket/seg/task_123/frame_001.bin",
        "compression": "zlib",
        "point_count": 150000,
        "class_mapping": {"0": "car", "1": "pedestrian"}
    }
    
    SEGMENTATION_2D:
    {
        "camera_id": "front_camera",
        "mask_url": "s3://bucket/seg2d/task_123/frame_001.png",
        "polygons": [[[x1,y1], [x2,y2], ...]]
    }
    """
    
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Example attributes:
    {
        "occluded": false,
        "truncated": true,
        "vehicle_type": "sedan",
        "activity": "walking"
    }
    """
    
    taxonomy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    source: Mapped[str] = mapped_column(
        String(50),
        default=AnnotationSource.MANUAL.value,
        nullable=False,
    )
    
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    task: Mapped["Task"] = relationship("Task", back_populates="annotations")
    frame: Mapped["Frame"] = relationship("Frame", back_populates="annotations")
    taxonomy: Mapped[Optional["Taxonomy"]] = relationship(
        "Taxonomy",
        foreign_keys=[taxonomy_id],
    )
    
    __table_args__ = (
        Index("ix_annotations_task_id", "task_id"),
        Index("ix_annotations_frame_id", "frame_id"),
        Index("ix_annotations_track_id", "track_id"),
        Index("ix_annotations_type", "type"),
        Index("ix_annotations_class_id", "class_id"),
        Index("ix_annotations_source", "source"),
        Index("ix_annotations_data", "data", postgresql_using="gin"),
        Index("ix_annotations_attributes", "attributes", postgresql_using="gin"),
        CheckConstraint(
            "type IN ('cuboid', 'box2d', 'polyline', 'polygon', 'keypoints', 'segmentation_3d', 'segmentation_2d')",
            name="ck_annotation_type",
        ),
    )



class SegmentationBlob(Base, TimestampMixin):
    """
    Stores 3D semantic segmentation as compressed binary data.
    Maps point_index -> class_id without one row per point.
    """
    __tablename__ = "segmentation_blobs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    annotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    
    blob_data: Mapped[bytes] = mapped_column(BYTEA, nullable=True)
    
    blob_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    compression: Mapped[str] = mapped_column(String(20), default="zlib")
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    
    __table_args__ = (
        Index("ix_segmentation_blobs_annotation_id", "annotation_id"),
    )



class Annotation3D(Base, TimestampMixin):
    """
    3D LiDAR cuboid annotations - annotations created in 3D mode.
    
    Stored separately from Fusion annotations to allow independent workflows.
    Can be migrated to Fusion mode where 2D boxes are added.
    """
    __tablename__ = "annotations_3d"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("frames.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    track_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    type: Mapped[str] = mapped_column(
        String(30),
        default="cuboid",
        nullable=False,
    )
    
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    CUBOID data format:
    {
        "center": {"x": 10.5, "y": 5.2, "z": 1.0},
        "dimensions": {"length": 4.5, "width": 2.0, "height": 1.5},
        "rotation": {"yaw": 0.5, "pitch": 0.0, "roll": 0.0},
        "confidence": 0.95
    }
    """
    
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    
    source: Mapped[str] = mapped_column(
        String(50),
        default="manual_3d",
        nullable=False,
    )
    
    is_migrated_to_fusion: Mapped[bool] = mapped_column(Boolean, default=False)
    migrated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    fusion_annotation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    is_keyframe: Mapped[bool] = mapped_column(Boolean, default=False)
    
    is_static: Mapped[bool] = mapped_column(Boolean, default=False)
    
    taxonomy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    task: Mapped["Task"] = relationship("Task")
    frame: Mapped["Frame"] = relationship("Frame")
    taxonomy: Mapped[Optional["Taxonomy"]] = relationship("Taxonomy", foreign_keys=[taxonomy_id])
    
    __table_args__ = (
        Index("ix_annotations_3d_task_id", "task_id"),
        Index("ix_annotations_3d_frame_id", "frame_id"),
        Index("ix_annotations_3d_track_id", "track_id"),
        Index("ix_annotations_3d_class_id", "class_id"),
        Index("ix_annotations_3d_is_migrated", "is_migrated_to_fusion"),
        Index("ix_annotations_3d_data", "data", postgresql_using="gin"),
        Index("ix_annotations_3d_is_keyframe", "is_keyframe"),
    )



class AnnotationFusion(Base, TimestampMixin):
    """
    Fusion annotations - 3D cuboid + projected/adjusted 2D boxes per camera.
    
    Created by migrating from 3D mode or directly in Fusion mode.
    Links 3D LiDAR data with 2D camera bounding boxes.
    """
    __tablename__ = "annotations_fusion"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("frames.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    track_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    type: Mapped[str] = mapped_column(
        String(30),
        default="cuboid_fusion",
        nullable=False,
    )
    
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    data_3d: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    Same as Annotation3D data format:
    {
        "center": {"x": 10.5, "y": 5.2, "z": 1.0},
        "dimensions": {"length": 4.5, "width": 2.0, "height": 1.5},
        "rotation": {"yaw": 0.5, "pitch": 0.0, "roll": 0.0}
    }
    """
    
    data_2d: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    2D boxes per camera:
    {
        "front_camera": {
            "bbox": {"x": 100, "y": 200, "width": 150, "height": 100},
            "is_projected": true,  # Auto-projected from 3D
            "is_adjusted": false,  # Manually adjusted
            "visibility": "full"  # full, partial, occluded
        },
        "left_camera": {
            "bbox": {"x": 50, "y": 180, "width": 80, "height": 60},
            "is_projected": true,
            "is_adjusted": true,
            "visibility": "partial"
        }
    }
    """
    
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    
    source: Mapped[str] = mapped_column(
        String(50),
        default="manual_fusion",
        nullable=False,
    )
    
    source_3d_annotation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    task: Mapped["Task"] = relationship("Task")
    frame: Mapped["Frame"] = relationship("Frame")
    
    __table_args__ = (
        Index("ix_annotations_fusion_task_id", "task_id"),
        Index("ix_annotations_fusion_frame_id", "frame_id"),
        Index("ix_annotations_fusion_track_id", "track_id"),
        Index("ix_annotations_fusion_class_id", "class_id"),
        Index("ix_annotations_fusion_source_3d", "source_3d_annotation_id"),
        Index("ix_annotations_fusion_data_3d", "data_3d", postgresql_using="gin"),
        Index("ix_annotations_fusion_data_2d", "data_2d", postgresql_using="gin"),
    )



class Track2D(Base, TimestampMixin):
    """
    Tracks for 2D object tracking across video frames.
    
    A track represents a single object instance that persists across multiple frames.
    Each track has a unique ID and links to multiple Annotation2D objects.
    """
    __tablename__ = "tracks_2d"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    camera_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    start_frame_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_frame_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    is_interpolated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task")
    annotations: Mapped[List["Annotation2D"]] = relationship(
        "Annotation2D",
        primaryjoin="Track2D.id == foreign(Annotation2D.track_id)",
        viewonly=True,
    )
    
    __table_args__ = (
        Index("ix_tracks_2d_task_id", "task_id"),
        Index("ix_tracks_2d_camera_id", "camera_id"),
        Index("ix_tracks_2d_class_id", "class_id"),
    )



class Annotation2D(Base, TimestampMixin):
    """
    2D-only annotations - bounding boxes, polygons, etc. on camera images.
    
    For pure 2D annotation tasks without 3D LiDAR component.
    """
    __tablename__ = "annotations_2d"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("frames.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    camera_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    track_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    taxonomy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    BOX2D:
    {
        "bbox": {"x": 100, "y": 200, "width": 150, "height": 100}
    }
    
    POLYGON:
    {
        "points": [[100, 200], [150, 250], [200, 300], [100, 300]]
    }
    
    POLYLINE:
    {
        "points": [[100, 200], [150, 250], [200, 300]],
        "is_closed": false
    }
    
    KEYPOINTS:
    {
        "skeleton_id": "human_pose",
        "keypoints": {
            "nose": {"x": 500, "y": 200, "visibility": 2},
            "left_eye": {"x": 490, "y": 190, "visibility": 2}
        }
    }
    """
    
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    
    source: Mapped[str] = mapped_column(
        String(50),
        default="manual_2d",
        nullable=False,
    )
    
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    task: Mapped["Task"] = relationship("Task")
    frame: Mapped["Frame"] = relationship("Frame")
    track: Mapped[Optional["Track2D"]] = relationship(
        "Track2D",
        foreign_keys=[track_id],
        primaryjoin="Annotation2D.track_id == Track2D.id",
    )
    
    __table_args__ = (
        Index("ix_annotations_2d_task_id", "task_id"),
        Index("ix_annotations_2d_frame_id", "frame_id"),
        Index("ix_annotations_2d_camera_id", "camera_id"),
        Index("ix_annotations_2d_track_id", "track_id"),
        Index("ix_annotations_2d_type", "type"),
        Index("ix_annotations_2d_class_id", "class_id"),
        Index("ix_annotations_2d_data", "data", postgresql_using="gin"),
        CheckConstraint(
            "type IN ('box', 'box2d', 'rotated_box', 'ellipse', 'polygon', 'polyline', 'points', 'keypoints', 'segmentation_2d', 'mask', 'semantic_segment')",
            name="ck_annotation_2d_type",
        ),
    )



class Annotation4D(Base, TimestampMixin):
    """
    Stores 4D annotations that span multiple frames.
    
    4D annotations work with stacked point clouds where objects are annotated
    in world coordinates and then transformed to each frame's LiDAR space.
    
    Key concepts:
    - world_data: The cuboid in world coordinates (consistent across all frames)
    - frame_data: JSONB mapping frame_id -> LiDAR space coordinates for each frame
    - When migrating to 3D, each frame gets its own Annotation with lidar coords
    """
    __tablename__ = "annotations_4d"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    
    type: Mapped[str] = mapped_column(
        String(30),
        default="cuboid",
        nullable=False,
    )
    
    class_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    world_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    CUBOID world_data format:
    {
        "center": {"x": 10.5, "y": 5.2, "z": 1.0},  # World coords
        "dimensions": {"length": 4.5, "width": 2.0, "height": 1.5},
        "rotation": {"yaw": 0.5, "pitch": 0.0, "roll": 0.0},  # World yaw
        "origin_frame_id": "uuid",  # The frame used as world origin
        "origin_ego_pose": {...}  # Ego pose of origin frame
    }
    """
    
    frame_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    frame_data format:
    {
        "<frame_id>": {
            "center": {"x": 5.2, "y": 3.1, "z": 0.8},  # LiDAR coords
            "rotation": {"yaw": 1.2, "pitch": 0.0, "roll": 0.0},  # LiDAR yaw
            "is_keyframe": true/false
        },
        ...
    }
    """
    
    frame_ids: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    
    is_static: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    
    is_migrated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    migrated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    source: Mapped[str] = mapped_column(
        String(50),
        default="manual_4d",
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task")
    
    __table_args__ = (
        Index("ix_annotations_4d_task_id", "task_id"),
        Index("ix_annotations_4d_track_id", "track_id"),
        Index("ix_annotations_4d_class_id", "class_id"),
        Index("ix_annotations_4d_is_migrated", "is_migrated"),
        Index("ix_annotations_4d_world_data", "world_data", postgresql_using="gin"),
        Index("ix_annotations_4d_frame_data", "frame_data", postgresql_using="gin"),
    )



class AuditLog(Base):
    """
    Tracks all changes for compliance and debugging.
    """
    __tablename__ = "audit_logs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    
    old_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_user_id", "user_id"),
    )



class QAReviewStatus(str, Enum):
    """QA review session status."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"


class QAReviewMode(str, Enum):
    """QA review mode."""
    VIEW_ONLY = "view_only"
    EDIT = "edit"
    SUGGEST = "suggest"


class ReviewVerdict(str, Enum):
    """Review verdict for an annotation."""
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"
    PENDING = "pending"


class SuggestionSeverity(str, Enum):
    """Severity level for QA suggestions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class QAReview(Base, TimestampMixin):
    """
    QA review session for a task.
    Tracks the overall QA review process.
    """
    __tablename__ = "qa_reviews"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=QAReviewStatus.IN_PROGRESS.value,
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(20),
        default=QAReviewMode.VIEW_ONLY.value,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_stage: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    """The task stage this review was created for ('qa' or 'customer_qa').
    Used to separate QA reviews from Customer QA reviews."""
    summary: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    """
    Summary schema:
    {
        "approved": 45,
        "rejected": 3,
        "flagged": 2,
        "pending": 10,
        "total_annotations": 60,
        "suggestions_addressed": 15,
        "suggestions_dismissed": 5
    }
    """
    
    task: Mapped["Task"] = relationship("Task", backref="qa_reviews")
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewer_id])
    annotation_reviews: Mapped[List["AnnotationReview"]] = relationship(
        "AnnotationReview",
        back_populates="qa_review",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_qa_reviews_task_id", "task_id"),
        Index("ix_qa_reviews_reviewer_id", "reviewer_id"),
        Index("ix_qa_reviews_status", "status"),
    )


class AnnotationReview(Base, TimestampMixin):
    """
    Review verdict for a specific annotation.
    Links to QA review session.
    """
    __tablename__ = "annotation_reviews"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    qa_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("qa_reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    annotation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    annotation_table: Mapped[str] = mapped_column(
        String(50),
        default="annotations",
        nullable=False,
    )
    frame_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    class_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    verdict: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    issue_types: Mapped[Optional[List[str]]] = mapped_column(
        PGARRAY(String(50)),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    location_x: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    location_y: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    location_z: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    annotator_resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    qa_review: Mapped["QAReview"] = relationship(
        "QAReview",
        back_populates="annotation_reviews",
    )
    
    __table_args__ = (
        Index("ix_annotation_reviews_qa_review_id", "qa_review_id"),
        Index("ix_annotation_reviews_annotation_id", "annotation_id"),
        UniqueConstraint("qa_review_id", "annotation_id", name="uq_annotation_reviews_qa_annotation"),
    )


class AnnotationComment(Base, TimestampMixin):
    """
    Threaded comments on annotations.
    Supports nested replies.
    """
    __tablename__ = "annotation_comments"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    annotation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    annotation_table: Mapped[str] = mapped_column(
        String(50),
        default="annotations",
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("annotation_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    resolver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[resolved_by])
    parent: Mapped[Optional["AnnotationComment"]] = relationship(
        "AnnotationComment",
        remote_side=[id],
        backref="replies",
    )
    
    __table_args__ = (
        Index("ix_annotation_comments_annotation_id", "annotation_id"),
        Index("ix_annotation_comments_user_id", "user_id"),
        Index("ix_annotation_comments_parent_id", "parent_id"),
    )


class QASuggestion(Base):
    """
    AI-generated suggestions for QA review.
    Detects anomalies and potential issues.
    """
    __tablename__ = "qa_suggestions"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    annotation_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    annotation_table: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    frame_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    suggestion_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    """
    Suggestion types:
    - size_anomaly: Dimensions change >30% between frames
    - position_jump: Object moves >3m between consecutive frames
    - orientation_flip: Yaw changes >90° suddenly
    - track_discontinuity: Same object, different track IDs
    - low_confidence: Confidence score <0.6
    - class_mismatch: Track has multiple classes
    - missing_attributes: Required attributes not set
    - auto_interpolated: Review suggested for auto-generated frames
    - imported_unchecked: Imported annotation never reviewed
    """
    severity: Mapped[str] = mapped_column(
        String(20),
        default=SuggestionSeverity.MEDIUM.value,
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    details: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    """
    Details schema varies by type:
    - size_anomaly: { prev_dimensions: {...}, curr_dimensions: {...}, delta_percent: 38 }
    - position_jump: { prev_position: {...}, curr_position: {...}, distance: 5.2 }
    - etc.
    """
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    dismissed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task")
    dismisser: Mapped[Optional["User"]] = relationship("User", foreign_keys=[dismissed_by])
    
    __table_args__ = (
        Index("ix_qa_suggestions_task_id", "task_id"),
        Index("ix_qa_suggestions_annotation_id", "annotation_id"),
        Index("ix_qa_suggestions_severity", "severity"),
        Index("ix_qa_suggestions_is_dismissed", "is_dismissed"),
    )



class TaskAssignmentHistory(Base):
    """
    Audit trail for task assignment changes.
    Tracks every assign, unassign, and stage-change clearing.
    """
    __tablename__ = "task_assignment_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    role: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )

    stage: Mapped[str] = mapped_column(String(50), nullable=False)

    changed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="assignment_history")
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    changed_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[changed_by_id])

    __table_args__ = (
        Index("ix_task_assignment_history_task_id", "task_id"),
        Index("ix_task_assignment_history_created_at", "created_at"),
    )



class TaskStageHistory(Base):
    """
    Audit trail for task stage and status transitions.
    Tracks all changes with who made them and why.
    """
    __tablename__ = "task_stage_history"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    from_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    
    to_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    
    changed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task", back_populates="stage_history")
    changed_by: Mapped[Optional["User"]] = relationship("User")
    
    __table_args__ = (
        Index("ix_task_stage_history_task_id", "task_id"),
        Index("ix_task_stage_history_created_at", "created_at"),
    )



class AnnotationChangeType(str, Enum):
    """Types of annotation changes."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


class AnnotationHistory(Base):
    """
    Version history for annotations.
    Tracks every create, update, and delete operation for full audit trail.
    """
    __tablename__ = "annotation_history"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    annotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    
    annotation_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    previous_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    task_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    task_status: Mapped[str] = mapped_column(String(50), nullable=False)
    
    changed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task", back_populates="annotation_history")
    changed_by: Mapped[Optional["User"]] = relationship("User")
    
    __table_args__ = (
        Index("ix_annotation_history_created_at", "created_at"),
        Index("ix_annotation_history_change_type", "change_type"),
    )


class StageSnapshot(Base):
    """
    Snapshot of all annotations at a stage transition.
    Captures the complete annotation state when a task moves between stages.
    """
    __tablename__ = "stage_snapshots"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    from_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    
    snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False)
    
    total_annotations: Mapped[int] = mapped_column(Integer, default=0)
    annotations_by_class: Mapped[dict] = mapped_column(JSONB, default=dict)
    annotations_by_type: Mapped[dict] = mapped_column(JSONB, default=dict)
    annotations_by_frame: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    annotations_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    triggered_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task", back_populates="stage_snapshots")
    triggered_by: Mapped[Optional["User"]] = relationship("User")
    
    __table_args__ = (
        Index("ix_stage_snapshots_task_id", "task_id"),
        Index("ix_stage_snapshots_created_at", "created_at"),
        Index("ix_stage_snapshots_to_stage", "to_stage"),
    )



class ChatSession(Base):
    """
    Chat session for AI assistant conversations.
    Each user can have multiple sessions over time.
    """
    __tablename__ = "chat_sessions"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=True,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )
    
    __table_args__ = (
        Index("ix_chat_sessions_user_id", "user_id"),
        Index("ix_chat_sessions_created_at", "created_at"),
    )


class ChatMessageRole(str, Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessageFeedback(str, Enum):
    """User feedback on assistant responses."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"


class ChatMessage(Base):
    """
    Individual chat message within a session.
    Stores both user messages and assistant responses.
    """
    __tablename__ = "chat_messages"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    context: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        default=dict,
        nullable=True,
    )
    
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    feedback: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    session: Mapped["ChatSession"] = relationship(
        "ChatSession",
        back_populates="messages",
    )
    
    __table_args__ = (
        Index("ix_chat_messages_session_id", "session_id"),
        Index("ix_chat_messages_created_at", "created_at"),
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_chat_messages_valid_role",
        ),
        CheckConstraint(
            "feedback IS NULL OR feedback IN ('helpful', 'not_helpful')",
            name="ck_chat_messages_valid_feedback",
        ),
    )


class KnowledgeChunk(Base):
    """
    Knowledge base chunks for RAG (Retrieval Augmented Generation).
    Stores embedded document chunks for semantic search.
    """
    __tablename__ = "knowledge_chunks"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    embedding: Mapped[Optional[List[float]]] = mapped_column(
        PGARRAY(Float, dimensions=1),
        nullable=True,
    )
    
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=True,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    __table_args__ = (
        Index("ix_knowledge_chunks_source", "source"),
    )


class ImportJob(Base, TimestampMixin):
    """Background dataset import job (long ZIP/folder uploads).

    The receiving gunicorn worker stages the upload, inserts a pending row
    and runs the import in an ``asyncio`` task; any worker can serve polls
    because the state lives in the database.
    """

    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    phase: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenes_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    staged_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
