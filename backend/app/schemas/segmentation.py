"""Per-point LiDAR segmentation label save/load/export API schemas."""
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SegmentationLabelsCreate(BaseModel):
    """Request to save segmentation labels for a frame.

    Accepts EITHER a full snapshot (``labels``, ``instance_ids``) — last-write-
    wins, kept for back-compat — OR a delta payload (``delta_indices`` +
    ``delta_labels`` + optional ``delta_instance_ids``). The delta path is
    required for safe concurrent editing: two annotators on the same task
    each send only the points THEY changed since their last save, and the
    server merges into the on-disk file under a per-frame lock so neither
    annotator clobbers the other's region. ``point_count`` is required in
    both modes so the server can initialize a fresh -1 array on first save.
    """
    frame_id: UUID
    point_count: int = Field(..., description="Total number of points")
    labels: Optional[List[int]] = Field(
        None, description="Full snapshot (legacy). Provide either this or delta_*."
    )
    instance_ids: Optional[List[int]] = Field(
        None, description="Full snapshot instance ids paired with `labels`."
    )
    delta_indices: Optional[List[int]] = Field(
        None, description="Indices of points the client changed since baseline."
    )
    delta_labels: Optional[List[int]] = Field(
        None, description="New label per index in `delta_indices` (-1 to clear)."
    )
    delta_instance_ids: Optional[List[int]] = Field(
        None, description="Optional new instance id per index in `delta_indices`."
    )

    @model_validator(mode="after")
    def _check_payload_shape(self):
        is_delta = self.delta_indices is not None or self.delta_labels is not None
        if is_delta:
            if self.delta_indices is None or self.delta_labels is None:
                raise ValueError("delta_indices and delta_labels must be provided together")
            if len(self.delta_indices) != len(self.delta_labels):
                raise ValueError(
                    f"delta_indices ({len(self.delta_indices)}) and "
                    f"delta_labels ({len(self.delta_labels)}) length mismatch"
                )
            if self.delta_instance_ids is not None and len(self.delta_instance_ids) != len(self.delta_indices):
                raise ValueError(
                    f"delta_instance_ids ({len(self.delta_instance_ids)}) and "
                    f"delta_indices ({len(self.delta_indices)}) length mismatch"
                )
        else:
            if self.labels is None:
                raise ValueError("Either `labels` (full snapshot) or `delta_*` must be provided")
        return self


class SegmentationLabelsResponse(BaseModel):
    """Response containing segmentation labels."""
    frame_id: UUID
    labels: List[int]
    point_count: int
    labeled_count: int
    class_distribution: dict
    instance_ids: Optional[List[int]] = None
    instance_count: int = 0


class SegmentationExportRequest(BaseModel):
    """Request to export segmentation labels."""
    frame_ids: List[UUID]
    format: str = Field(default="npy", description="Export format: 'npy' or 'bin'")
    include_unlabeled: bool = Field(default=True, description="Include unlabeled points in export")


class SegmentationStats(BaseModel):
    """Statistics for segmentation progress."""
    total_frames: int
    labeled_frames: int
    total_points: int
    labeled_points: int
    total_instances: int
    class_distribution: dict
