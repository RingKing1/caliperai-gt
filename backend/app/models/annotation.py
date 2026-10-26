"""Annotation ORM models across all modalities plus change history."""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.enums import AnnotationSource

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.catalog import Taxonomy
    from app.models.scene import Frame
    from app.models.task import Task
    from app.models.user import User


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

    track_id: Mapped[uuid.UUID | None] = mapped_column(
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

    taxonomy_id: Mapped[uuid.UUID | None] = mapped_column(
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
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
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
            "type IN ('cuboid', 'box2d', 'polyline', 'polygon', "
            "'keypoints', 'segmentation_3d', 'segmentation_2d')",
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

    blob_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

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

    track_id: Mapped[uuid.UUID | None] = mapped_column(
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
    migrated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    fusion_annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_keyframe: Mapped[bool] = mapped_column(Boolean, default=False)

    is_static: Mapped[bool] = mapped_column(Boolean, default=False)

    taxonomy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    task: Mapped["Task"] = relationship("Task")
    frame: Mapped["Frame"] = relationship("Frame")
    taxonomy: Mapped[Optional["Taxonomy"]] = relationship(
        "Taxonomy", foreign_keys=[taxonomy_id]
    )

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

    track_id: Mapped[uuid.UUID | None] = mapped_column(
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

    source_3d_annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
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

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)

    start_frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_interpolated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task")
    annotations: Mapped[list["Annotation2D"]] = relationship(
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

    track_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    class_id: Mapped[str] = mapped_column(String(100), nullable=False)

    taxonomy_id: Mapped[uuid.UUID | None] = mapped_column(
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
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
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
            "type IN ('box', 'box2d', 'rotated_box', 'ellipse', 'polygon', "
            "'polyline', 'points', 'keypoints', 'segmentation_2d', 'mask', "
            "'semantic_segment')",
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
    migrated_at: Mapped[datetime | None] = mapped_column(
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


class AnnotationChangeType(StrEnum):
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

    previous_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    task_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    task_status: Mapped[str] = mapped_column(String(50), nullable=False)

    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
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


class Track3DRefinement(Base, TimestampMixin):
    """Explicit human-review flag for a 3D cuboid track.

    Sparse by design: a row exists only once someone toggles the state.
    No row means "AI-only". Kept separate from annotations_3d so marking a
    track refined never rewrites the 668k annotation rows.
    """

    __tablename__ = "tracks_3d"

    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_refined: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    refined_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    refined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_tracks_3d_task_id", "task_id"),
    )
