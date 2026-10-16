"""Catalog domain: taxonomies, campaigns, datasets and their association."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import TaxonomyAnnotationMode

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.models import Scene
    from app.models.org import Organization


dataset_taxonomy_association = Table(
    "dataset_taxonomy",
    Base.metadata,
    Column(
        "dataset_id",
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "taxonomy_id",
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("mode", String(20), nullable=True),
    Column("is_primary", Boolean, default=False),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now()
    ),
)



class Taxonomy(Base, TimestampMixin, SoftDeleteMixin):
    """
    Reusable taxonomy/labeling requirement that can be associated with
    multiple datasets.
    Contains class definitions, attributes, skeletons, and annotation rules.

    annotation_mode determines what type of annotations this taxonomy supports:
    - fusion_3d: 3D cuboids, 4D annotations, fusion (3D+2D projections)
    - 2d_only: Pure 2D annotations (lanes, traffic signs, drivable areas)

    Taxonomies are organization-specific and cannot be shared between organizations.
    """
    __tablename__ = "taxonomies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)

    annotation_mode: Mapped[str] = mapped_column(
        String(20),
        default=TaxonomyAnnotationMode.FUSION_3D.value,
        nullable=False,
    )

    classes: Mapped[dict] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    """
    Classes schema:
    [
        {
            "id": "car",
            "name": "Car",
            "color": "#FF0000",
            "type": ["cuboid", "box2d"],
            "attributes": {
                "occluded": {"type": "boolean", "default": false},
                "truncated": {"type": "boolean", "default": false}
            }
        }
    ]
    """

    skeletons: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    annotation_rules: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Rules schema:
    {
        "min_points_polyline": 2,
        "min_points_polygon": 3,
        "allow_overlapping_boxes": false,
        "require_track_id": true
    }
    """

    shared_attributes: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    """
    Shared attributes schema:
    [
        {
            "name": "occluded",
            "type": "boolean",
            "default": false,
            "applies_to": ["car", "truck", "bus"]  # or ["__all__"] for all classes
        }
    ]
    """

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="taxonomies",
    )
    datasets: Mapped[list["Dataset"]] = relationship(
        "Dataset",
        secondary=dataset_taxonomy_association,
        back_populates="taxonomies",
    )

    __table_args__ = (
        Index("ix_taxonomies_name", "name"),
        Index("ix_taxonomies_created_at", "created_at"),
        Index("ix_taxonomies_annotation_mode", "annotation_mode"),
        Index("ix_taxonomies_organization_id", "organization_id"),
    )



class Campaign(Base, TimestampMixin, SoftDeleteMixin):
    """
    Root business container for annotation projects.
    Example: "Highway Autonomy 2025", "Urban Scene Detection Q4"
    """
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Config schema:
    {
        "quality_thresholds": {
            "min_accuracy": 0.95,
            "max_rejection_rate": 0.1
        },
        "deadline": "2025-12-31",
        "priority": "high",
        "tags": ["autonomous", "highway"]
    }
    """

    custom_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Metadata schema (flexible, user-defined):
    {
        "client": "ACME Corp",
        "project_code": "PRJ-2025-001",
        "region": "North America",
        "custom_field": "custom_value"
    }
    """

    stats: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Stats schema:
    {
        "total_datasets": 10,
        "total_scenes": 500,
        "total_tasks": 2500,
        "completed_tasks": 1200,
        "total_annotations": 150000,
        "annotator_hours": 450.5
    }
    """

    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="campaigns",
    )
    datasets: Mapped[list["Dataset"]] = relationship(
        "Dataset",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_campaigns_name", "name"),
        Index("ix_campaigns_created_at", "created_at"),
        Index("ix_campaigns_organization_id", "organization_id"),
    )



class Dataset(Base, TimestampMixin, SoftDeleteMixin):
    """
    Dataset containing taxonomy configuration and sensor data.
    The taxonomy defines classes, attributes, and skeleton structures.
    """
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    taxonomy: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    Taxonomy schema:
    {
        "classes": [
            {
                "id": "car",
                "name": "Car",
                "color": "#FF0000",
                "type": ["cuboid", "box2d"],
                "attributes": {
                    "occluded": {"type": "boolean", "default": false},
                    "truncated": {"type": "boolean", "default": false},
                    "vehicle_type": {
                        "type": "enum",
                        "options": ["sedan", "suv", "truck", "van"],
                        "default": "sedan"
                    }
                }
            },
            {
                "id": "pedestrian",
                "name": "Pedestrian",
                "color": "#00FF00",
                "type": ["cuboid", "box2d", "keypoints"],
                "skeleton": "human_pose"
            }
        ],
        "skeletons": {
            "human_pose": {
                "keypoints": [
                    {"id": "nose", "name": "Nose"},
                    {"id": "left_eye", "name": "Left Eye"},
                    {"id": "right_eye", "name": "Right Eye"},
                    {"id": "left_ear", "name": "Left Ear"},
                    {"id": "right_ear", "name": "Right Ear"},
                    {"id": "left_shoulder", "name": "Left Shoulder"},
                    {"id": "right_shoulder", "name": "Right Shoulder"},
                    {"id": "left_elbow", "name": "Left Elbow"},
                    {"id": "right_elbow", "name": "Right Elbow"},
                    {"id": "left_wrist", "name": "Left Wrist"},
                    {"id": "right_wrist", "name": "Right Wrist"},
                    {"id": "left_hip", "name": "Left Hip"},
                    {"id": "right_hip", "name": "Right Hip"},
                    {"id": "left_knee", "name": "Left Knee"},
                    {"id": "right_knee", "name": "Right Knee"},
                    {"id": "left_ankle", "name": "Left Ankle"},
                    {"id": "right_ankle", "name": "Right Ankle"}
                ],
                "bones": [
                    ["nose", "left_eye"],
                    ["nose", "right_eye"],
                    ["left_eye", "left_ear"],
                    ["right_eye", "right_ear"],
                    ["left_shoulder", "right_shoulder"],
                    ["left_shoulder", "left_elbow"],
                    ["right_shoulder", "right_elbow"],
                    ["left_elbow", "left_wrist"],
                    ["right_elbow", "right_wrist"],
                    ["left_shoulder", "left_hip"],
                    ["right_shoulder", "right_hip"],
                    ["left_hip", "right_hip"],
                    ["left_hip", "left_knee"],
                    ["right_hip", "right_knee"],
                    ["left_knee", "left_ankle"],
                    ["right_knee", "right_ankle"]
                ]
            }
        },
        "annotation_rules": {
            "min_points_polyline": 2,
            "min_points_polygon": 3,
            "allow_overlapping_boxes": false
        }
    }
    """

    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sensor_config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Sensor config schema:
    {
        "lidar": {
            "sensor_id": "velodyne_64",
            "format": "pcd",
            "coordinate_system": "ego_vehicle"
        },
        "cameras": [
            {
                "sensor_id": "front_camera",
                "resolution": [1920, 1080],
                "format": "jpg"
            },
            {
                "sensor_id": "rear_camera",
                "resolution": [1920, 1080],
                "format": "jpg"
            }
        ]
    }
    """

    custom_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Metadata schema (flexible, user-defined):
    {
        "data_source": "Fleet Vehicle A",
        "collection_date": "2025-01-15",
        "weather_conditions": "Clear",
        "custom_field": "custom_value"
    }
    """

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="datasets")
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )
    taxonomies: Mapped[list["Taxonomy"]] = relationship(
        "Taxonomy",
        secondary=dataset_taxonomy_association,
        back_populates="datasets",
    )

    __table_args__ = (
        Index("ix_datasets_campaign_id", "campaign_id"),
        Index("ix_datasets_name", "name"),
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
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenes_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    staged_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
