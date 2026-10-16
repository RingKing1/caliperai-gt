"""Catalog API schemas: taxonomies, campaigns, datasets and configs."""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import (
    AnnotationType,
    BaseSchema,
    TaxonomyAnnotationMode,
    TimestampSchema,
)

if TYPE_CHECKING:
    # Forward ref only (catalog <-> scene); resolved by model_rebuild() in
    # the schemas facade once every domain module is imported.
    from app.schemas.scene import SceneResponse


class AttributeDefinition(BaseSchema):
    """Definition for a class attribute."""
    type: Literal["boolean", "string", "number", "enum"]
    default: Any | None = None
    options: list[str] | None = None
    required: bool = False
    description: str | None = None
    mutable: bool = True


class SharedAttributeDefinition(BaseSchema):
    """
    Definition for a shared attribute that applies to multiple classes.
    These are defined at the taxonomy level and can be assigned to specific classes
    or all classes.
    """
    name: str = Field(
        ..., min_length=1, max_length=100, description="Attribute name/id"
    )
    type: Literal["boolean", "string", "number", "enum"]
    default: Any | None = None
    options: list[str] | None = None
    required: bool = False
    description: str | None = None
    mutable: bool = True
    applies_to: list[str] = Field(
        default_factory=list,
        description=(
            "List of class IDs this attribute applies to. Empty list or "
            "['__all__'] means all classes."
        )
    )


class KeypointDefinition(BaseSchema):
    """Definition for a skeleton keypoint."""
    id: str
    name: str
    color: str | None = None


class SkeletonDefinition(BaseSchema):
    """Definition for a skeleton structure."""
    keypoints: list[KeypointDefinition]
    bones: list[list[str]]


class ClassDefinition(BaseSchema):
    """Definition for an annotation class."""
    id: str
    name: str
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    type: list[AnnotationType]
    attributes: dict[str, AttributeDefinition] = Field(default_factory=dict)
    skeleton: str | None = None
    description: str | None = None
    default_dimensions: list[float] | None = None
    single_click_placement: bool | None = None


class AnnotationRules(BaseSchema):
    """Rules for annotations."""
    min_points_polyline: int = 2
    min_points_polygon: int = 3
    allow_overlapping_boxes: bool = False
    require_track_id: bool = True


class TaxonomyConfig(BaseSchema):
    """Complete taxonomy configuration for a dataset."""
    classes: list[ClassDefinition]
    skeletons: dict[str, SkeletonDefinition] = Field(default_factory=dict)
    annotation_rules: AnnotationRules = Field(default_factory=AnnotationRules)
    shared_attributes: list[SharedAttributeDefinition] = Field(
        default_factory=list,
        description="Shared attributes that can apply to multiple classes"
    )



class CampaignStats(BaseSchema):
    """Aggregated statistics for a campaign."""
    total_datasets: int = 0
    total_scenes: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    total_annotations: int = 0
    annotator_hours: float = 0.0


class CampaignConfig(BaseSchema):
    """Configuration for a campaign."""
    quality_thresholds: dict[str, float] = Field(default_factory=dict)
    deadline: str | None = None
    priority: str = "normal"
    tags: list[str] = Field(default_factory=list)


class CampaignBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    config: CampaignConfig = Field(default_factory=CampaignConfig)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)
    deadline: datetime | None = None


class CampaignCreate(CampaignBase):
    organization_id: UUID = Field(
        ..., description="Organization this campaign belongs to"
    )


class CampaignUpdate(BaseSchema):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    config: CampaignConfig | None = None
    custom_metadata: dict[str, Any] | None = None
    deadline: datetime | None = None


class CampaignResponse(CampaignBase, TimestampSchema):
    id: UUID
    organization_id: UUID
    stats: CampaignStats = Field(default_factory=CampaignStats)


class CampaignListResponse(BaseSchema):
    items: list[CampaignResponse]
    total: int
    page: int
    page_size: int



class TaxonomyBase(BaseSchema):
    """Base schema for Taxonomy entity."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    version: str = Field(default="1.0.0", max_length=50)
    annotation_mode: TaxonomyAnnotationMode = Field(
        default=TaxonomyAnnotationMode.FUSION_3D,
        description=(
            "Annotation mode: fusion_3d for 3D/4D/Fusion, 2d_only for "
            "pure 2D annotations"
        )
    )
    classes: list[ClassDefinition] = Field(default_factory=list)
    skeletons: dict[str, SkeletonDefinition] = Field(default_factory=dict)
    annotation_rules: AnnotationRules = Field(default_factory=AnnotationRules)
    shared_attributes: list[SharedAttributeDefinition] = Field(
        default_factory=list,
        description="Shared attributes that can apply to multiple classes"
    )


class TaxonomyCreate(TaxonomyBase):
    """Schema for creating a new taxonomy."""
    organization_id: UUID = Field(
        ...,
        description="Organization this taxonomy belongs to."
    )


class TaxonomyUpdate(BaseSchema):
    """Schema for updating a taxonomy."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    version: str | None = Field(None, max_length=50)
    annotation_mode: TaxonomyAnnotationMode | None = None
    classes: list[ClassDefinition] | None = None
    skeletons: dict[str, SkeletonDefinition] | None = None
    annotation_rules: AnnotationRules | None = None
    shared_attributes: list[SharedAttributeDefinition] | None = None


class TaxonomyResponse(TaxonomyBase, TimestampSchema):
    """Schema for taxonomy response."""
    id: UUID
    organization_id: UUID


class TaxonomyListResponse(BaseSchema):
    """Paginated list of taxonomies."""
    items: list[TaxonomyResponse]
    total: int
    page: int
    page_size: int


class TaxonomySummary(BaseSchema):
    """Brief taxonomy info for embedding in other responses."""
    id: UUID
    name: str
    version: str
    annotation_mode: TaxonomyAnnotationMode = TaxonomyAnnotationMode.FUSION_3D
    class_count: int = 0



class SensorConfig(BaseSchema):
    """Sensor configuration for a dataset."""
    lidar: dict[str, Any] | None = None
    cameras: list[dict[str, Any]] = Field(default_factory=list)


class DatasetBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    taxonomy: TaxonomyConfig
    sensor_config: SensorConfig = Field(default_factory=SensorConfig)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)
    deadline: datetime | None = None


class DatasetCreate(DatasetBase):
    campaign_id: UUID


class DatasetUpdate(BaseSchema):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    taxonomy: TaxonomyConfig | None = None
    sensor_config: SensorConfig | None = None
    custom_metadata: dict[str, Any] | None = None
    deadline: datetime | None = None


class DatasetResponse(DatasetBase, TimestampSchema):
    id: UUID
    campaign_id: UUID


class DatasetStats(BaseSchema):
    """Statistics for a dataset."""
    scene_count: int = 0
    total_frames: int = 0
    total_tasks: int = 0
    pending_tasks: int = 0
    in_progress_tasks: int = 0
    completed_tasks: int = 0


class DatasetDetailResponse(DatasetBase, TimestampSchema):
    """Complete dataset response with all related data for optimized loading."""
    id: UUID
    campaign_id: UUID
    taxonomies: list['TaxonomyResponse'] = Field(default_factory=list)
    scenes: list['SceneResponse'] = Field(default_factory=list)
    stats: DatasetStats = Field(default_factory=DatasetStats)
