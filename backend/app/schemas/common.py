"""Shared API-schema base classes and cross-domain enums."""
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TaskStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AnnotationType(StrEnum):
    CUBOID = "cuboid"
    BOX2D = "box2d"
    POLYLINE = "polyline"
    POLYGON = "polygon"
    KEYPOINTS = "keypoints"
    SEGMENTATION_3D = "segmentation_3d"
    SEGMENTATION_2D = "segmentation_2d"


class AnnotationSource(StrEnum):
    MANUAL = "manual"
    AUTO_INTERPOLATED = "auto_interpolated"
    AIRFLOW_MODEL_V1 = "airflow_model_v1"
    AIRFLOW_MODEL_V2 = "airflow_model_v2"
    IMPORTED = "imported"


class UserRole(StrEnum):
    """User roles for RBAC."""
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    ANNOTATOR = "annotator"
    QA_REVIEWER = "qa_reviewer"
    CUSTOMER_QA = "customer_qa"


class TaxonomyAnnotationMode(StrEnum):
    """Annotation mode that a taxonomy supports."""
    FUSION_3D = "fusion_3d"
    ONLY_2D = "2d_only"
    SEGMENTATION_3D = "segmentation_3d"



class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
    )


class TimestampSchema(BaseSchema):
    """Schema with timestamp fields."""
    created_at: datetime
    updated_at: datetime
