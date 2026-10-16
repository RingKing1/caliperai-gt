"""Scene and frame ORM models."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.catalog import Dataset, Taxonomy
    from app.models.models import Annotation, Task


class Scene(Base, TimestampMixin, SoftDeleteMixin):
    """
    A continuous time-series of sensor data.
    Contains calibration matrices for 3D-to-2D projection.
    """
    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    scene_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Metadata schema:
    {
        "location": "San Francisco Highway 101",
        "weather": "sunny",
        "time_of_day": "afternoon",
        "recording_date": "2025-03-15",
        "duration_seconds": 120.5,
        "ego_vehicle": "av_001"
    }
    """

    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)

    fps: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)

    calibration: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    Calibration schema (per sensor pair):
    {
        "lidar_to_cameras": {
            "front_camera": {
                "extrinsic": {
                    "rotation": [
                        [r11, r12, r13],
                        [r21, r22, r23],
                        [r31, r32, r33]
                    ],
                    "translation": [tx, ty, tz]
                },
                "intrinsic": {
                    "fx": 1000.0,
                    "fy": 1000.0,
                    "cx": 960.0,
                    "cy": 540.0,
                    "distortion": [k1, k2, p1, p2, k3]
                }
            },
            "rear_camera": {...}
        },
        "ego_to_lidar": {
            "rotation": [...],
            "translation": [...]
        }
    }
    """

    storage_paths: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Storage paths schema:
    {
        "lidar_base": "s3://bucket/scenes/{scene_id}/lidar/",
        "cameras": {
            "front_camera": "s3://bucket/scenes/{scene_id}/cameras/front/",
            "rear_camera": "s3://bucket/scenes/{scene_id}/cameras/rear/"
        },
        "ego_poses": "s3://bucket/scenes/{scene_id}/ego_poses.json"
    }
    """

    selected_taxonomy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
    )

    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="scenes")
    selected_taxonomy: Mapped[Optional["Taxonomy"]] = relationship(
        "Taxonomy",
        foreign_keys=[selected_taxonomy_id],
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="scene",
        cascade="all, delete-orphan",
    )
    frames: Mapped[list["Frame"]] = relationship(
        "Frame",
        back_populates="scene",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_scenes_dataset_id", "dataset_id"),
        Index("ix_scenes_name", "name"),
    )



class Frame(Base, TimestampMixin):
    """
    Individual frame within a scene.
    Links to actual sensor data files.
    """
    __tablename__ = "frames"

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
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)

    timestamp: Mapped[float] = mapped_column(Float, nullable=False)

    ego_pose: Mapped[dict] = mapped_column(
        JSONB,
        nullable=True,
    )
    """
    Ego pose schema:
    {
        "position": [x, y, z],
        "rotation": [qw, qx, qy, qz],  # Quaternion
        "velocity": [vx, vy, vz]
    }
    """

    file_paths: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    """
    File paths schema:
    {
        "lidar": "frame_0001.pcd",
        "cameras": {
            "front_camera": "frame_0001.jpg",
            "rear_camera": "frame_0001.jpg"
        }
    }
    """

    scene: Mapped["Scene"] = relationship("Scene", back_populates="frames")
    annotations: Mapped[list["Annotation"]] = relationship(
        "Annotation",
        back_populates="frame",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("scene_id", "frame_index", name="uq_frame_scene_index"),
        Index("ix_frames_scene_id", "scene_id"),
        Index("ix_frames_frame_index", "frame_index"),
    )
