"""SAM2 image/video segmentation wire schemas.

Shared by the backend proxy API and the standalone SAM2 GPU microservice
(``microservices/sam2/service.py``). The microservice imports these models and
keeps only its contract deltas (``multimask_output``, ``mask_index``, required
``embedding_key``) as thin subclasses.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class PointPromptSchema(BaseModel):
    """A point prompt for segmentation."""
    x: float = Field(..., description="X coordinate in image space")
    y: float = Field(..., description="Y coordinate in image space")
    label: int = Field(..., ge=0, le=1, description="1 for foreground (positive), 0 for background (negative)")


class BoxPromptSchema(BaseModel):
    """A box prompt for segmentation."""
    x1: float = Field(..., description="Top-left X")
    y1: float = Field(..., description="Top-left Y")
    x2: float = Field(..., description="Bottom-right X")
    y2: float = Field(..., description="Bottom-right Y")


class SegmentRequest(BaseModel):
    """Request for SAM2 segmentation."""
    image_url: Optional[str] = Field(None, description="URL to fetch image from (e.g., MinIO)")
    image_base64: Optional[str] = Field(None, description="Base64-encoded image data")
    points: List[PointPromptSchema] = Field(default_factory=list, description="Point prompts")
    box: Optional[BoxPromptSchema] = Field(None, description="Optional box prompt")
    embedding_key: Optional[str] = Field(None, description="Cached embedding key for faster inference")
    simplify_tolerance: float = Field(default=0.01, ge=0.001, le=0.1, description="Polygon simplification tolerance (0.001=fine/many points, 0.1=coarse/few points)")


class PolygonPoint(BaseModel):
    """A point in a polygon."""
    x: float
    y: float


class SegmentResult(BaseModel):
    """A segmentation result."""
    polygon: List[PolygonPoint] = Field(..., description="Polygon points defining the mask boundary")
    score: float = Field(..., description="Confidence score (0-1)")
    area: int = Field(..., description="Pixel area of the mask")


class SegmentResponse(BaseModel):
    """Response from SAM2 segmentation."""
    masks: List[SegmentResult] = Field(..., description="Segmentation results")
    embedding_key: Optional[str] = Field(None, description="Embedding cache key for follow-up requests")
    inference_time_ms: float = Field(..., description="Inference time in milliseconds")


class EmbeddingRequest(BaseModel):
    """Request to precompute image embedding."""
    image_url: Optional[str] = Field(None, description="URL to fetch image from")
    image_base64: Optional[str] = Field(None, description="Base64-encoded image data")


class EmbeddingResponse(BaseModel):
    """Response with embedding cache key."""
    embedding_key: str = Field(..., description="Key to use for fast segmentation")
    compute_time_ms: float = Field(..., description="Embedding computation time in milliseconds")


class PolygonPointInitSchema(BaseModel):
    """A point in a polygon."""
    x: float
    y: float


class ObjectInitSchema(BaseModel):
    """Initial object annotation for tracking."""
    object_id: int = Field(..., description="Unique object ID for this track")
    box: BoxPromptSchema = Field(..., description="Initial bounding box")
    frame_index: int = Field(default=0, description="Frame index where object is initialized")
    polygon: Optional[List[PolygonPointInitSchema]] = Field(default=None, description="Optional polygon points for precise mask initialization (preserves shape details like mirrors)")


class VideoFrameSchema(BaseModel):
    """A single video frame."""
    frame_index: int
    image_base64: Optional[str] = None
    image_url: Optional[str] = None


class VideoPropagateRequest(BaseModel):
    """Request to propagate object annotations across video frames."""
    frames: List[VideoFrameSchema] = Field(..., description="List of video frames in order")
    objects: List[ObjectInitSchema] = Field(..., description="Objects to track with initial boxes")
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Stop tracking if confidence drops below this")


class PropagatedBoxSchema(BaseModel):
    """Propagated bounding box and polygon for an object in a frame."""
    object_id: int
    frame_index: int
    box: BoxPromptSchema
    confidence: float
    status: str = Field(default="tracked", description="tracked, lost, or keyframe")
    polygon: Optional[List[PolygonPointInitSchema]] = Field(default=None, description="Propagated polygon (preserves shape details)")


class VideoPropagateResponse(BaseModel):
    """Response with propagated annotations."""
    boxes: List[PropagatedBoxSchema]
    total_frames: int
    tracked_frames: int
    lost_at_frame: Optional[int] = None
    processing_time_ms: float

