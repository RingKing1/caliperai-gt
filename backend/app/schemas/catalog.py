"""Catalog API schemas: taxonomies, campaigns, datasets and configs."""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional
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
    default: Optional[Any] = None
    options: Optional[List[str]] = None
    required: bool = False
    description: Optional[str] = None
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
    default: Optional[Any] = None
    options: Optional[List[str]] = None
    required: bool = False
    description: Optional[str] = None
    mutable: bool = True
    applies_to: List[str] = Field(
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
    color: Optional[str] = None


class SkeletonDefinition(BaseSchema):
    """Definition for a skeleton structure."""
    keypoints: List[KeypointDefinition]
    bones: List[List[str]]


class ClassDefinition(BaseSchema):
    """Definition for an annotation class."""
    id: str
    name: str
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    type: List[AnnotationType]
    attributes: Dict[str, AttributeDefinition] = Field(default_factory=dict)
    skeleton: Optional[str] = None
    description: Optional[str] = None
    default_dimensions: Optional[List[float]] = None
    single_click_placement: Optional[bool] = None


class AnnotationRules(BaseSchema):
    """Rules for annotations."""
    min_points_polyline: int = 2
    min_points_polygon: int = 3
    allow_overlapping_boxes: bool = False
    require_track_id: bool = True


class TaxonomyConfig(BaseSchema):
    """Complete taxonomy configuration for a dataset."""
    classes: List[ClassDefinition]
    skeletons: Dict[str, SkeletonDefinition] = Field(default_factory=dict)
    annotation_rules: AnnotationRules = Field(default_factory=AnnotationRules)
    shared_attributes: List[SharedAttributeDefinition] = Field(
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
    quality_thresholds: Dict[str, float] = Field(default_factory=dict)
    deadline: Optional[str] = None
    priority: str = "normal"
    tags: List[str] = Field(default_factory=list)


class CampaignBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config: CampaignConfig = Field(default_factory=CampaignConfig)
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[datetime] = None


class CampaignCreate(CampaignBase):
    organization_id: UUID = Field(
        ..., description="Organization this campaign belongs to"
    )


class CampaignUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[CampaignConfig] = None
    custom_metadata: Optional[Dict[str, Any]] = None
    deadline: Optional[datetime] = None


class CampaignResponse(CampaignBase, TimestampSchema):
    id: UUID
    organization_id: UUID
    stats: CampaignStats = Field(default_factory=CampaignStats)


class CampaignListResponse(BaseSchema):
    items: List[CampaignResponse]
    total: int
    page: int
    page_size: int



class TaxonomyBase(BaseSchema):
    """Base schema for Taxonomy entity."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    version: str = Field(default="1.0.0", max_length=50)
    annotation_mode: TaxonomyAnnotationMode = Field(
        default=TaxonomyAnnotationMode.FUSION_3D,
        description=(
            "Annotation mode: fusion_3d for 3D/4D/Fusion, 2d_only for "
            "pure 2D annotations"
        )
    )
    classes: List[ClassDefinition] = Field(default_factory=list)
    skeletons: Dict[str, SkeletonDefinition] = Field(default_factory=dict)
    annotation_rules: AnnotationRules = Field(default_factory=AnnotationRules)
    shared_attributes: List[SharedAttributeDefinition] = Field(
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
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    version: Optional[str] = Field(None, max_length=50)
    annotation_mode: Optional[TaxonomyAnnotationMode] = None
    classes: Optional[List[ClassDefinition]] = None
    skeletons: Optional[Dict[str, SkeletonDefinition]] = None
    annotation_rules: Optional[AnnotationRules] = None
    shared_attributes: Optional[List[SharedAttributeDefinition]] = None


class TaxonomyResponse(TaxonomyBase, TimestampSchema):
    """Schema for taxonomy response."""
    id: UUID
    organization_id: UUID


class TaxonomyListResponse(BaseSchema):
    """Paginated list of taxonomies."""
    items: List[TaxonomyResponse]
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
    lidar: Optional[Dict[str, Any]] = None
    cameras: List[Dict[str, Any]] = Field(default_factory=list)


class DatasetBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    taxonomy: TaxonomyConfig
    sensor_config: SensorConfig = Field(default_factory=SensorConfig)
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[datetime] = None


class DatasetCreate(DatasetBase):
    campaign_id: UUID


class DatasetUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    taxonomy: Optional[TaxonomyConfig] = None
    sensor_config: Optional[SensorConfig] = None
    custom_metadata: Optional[Dict[str, Any]] = None
    deadline: Optional[datetime] = None


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
    taxonomies: List['TaxonomyResponse'] = Field(default_factory=list)
    scenes: List['SceneResponse'] = Field(default_factory=list)
    stats: DatasetStats = Field(default_factory=DatasetStats)
