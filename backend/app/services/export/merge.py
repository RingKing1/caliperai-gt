"""Annotation merging strategies for overlapping tasks."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def merge_overlapping_annotations(
    all_annotations: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """Merge annotations from overlapping tasks using Track ID merge strategy.

    For annotations with the same track_id and frame_index:
    - Keep the annotation with the most recent created_at timestamp ("Prefer Recent")

    For annotations without track_id:
    - Keep all (no merging possible without track identification)

    Special handling for annotations_4d which have frame_range instead of frame_index.
    """
    merged: dict[str, list[dict[str, Any]]] = {}

    for ann_type, ann_items in all_annotations.items():
        if ann_type == "annotations_4d":
            merged[ann_type] = _merge_4d_annotations(ann_items)
        else:
            merged[ann_type] = _merge_frame_indexed_annotations(ann_items)

    return merged


def _merge_frame_indexed_annotations(
    annotations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge annotations that have frame_index field.

    Groups by (track_id, frame_index) and keeps the most recent annotation.
    Annotations without track_id are kept as-is.
    """
    if not annotations:
        return []

    tracked: list[dict[str, Any]] = []
    untracked: list[dict[str, Any]] = []

    for ann in annotations:
        if ann.get("track_id"):
            tracked.append(ann)
        else:
            untracked.append(ann)

    merged_tracked: dict[tuple, dict[str, Any]] = {}

    for ann in tracked:
        if "camera_id" in ann:
            key = (ann["track_id"], ann.get("frame_index"), ann.get("camera_id"))
        else:
            key = (ann["track_id"], ann.get("frame_index"))

        if key not in merged_tracked:
            merged_tracked[key] = ann
        else:
            existing_created = merged_tracked[key].get("created_at")
            new_created = ann.get("created_at")

            if not existing_created and new_created:
                merged_tracked[key] = ann
            elif existing_created and new_created and new_created > existing_created:
                merged_tracked[key] = ann

    return list(merged_tracked.values()) + untracked


def _merge_4d_annotations(
    annotations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge 4D annotations that have frame_range instead of frame_index.

    4D annotations represent tracks across a frame range.
    For same track_id with overlapping frame ranges, prefer the more recent one.
    """
    if not annotations:
        return []

    tracked: list[dict[str, Any]] = []
    untracked: list[dict[str, Any]] = []

    for ann in annotations:
        if ann.get("track_id"):
            tracked.append(ann)
        else:
            untracked.append(ann)

    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ann in tracked:
        by_track[ann["track_id"]].append(ann)

    merged_tracked: list[dict[str, Any]] = []

    for _track_id, track_anns in by_track.items():
        if len(track_anns) == 1:
            merged_tracked.append(track_anns[0])
            continue

        sorted_anns = sorted(
            track_anns, key=lambda a: a.get("frame_range", {}).get("start", 0)
        )

        result_anns: list[dict[str, Any]] = []

        for ann in sorted_anns:
            frame_range = ann.get("frame_range", {})
            ann_start = frame_range.get("start", 0)
            ann_end = frame_range.get("end", 0)
            ann_created = ann.get("created_at")

            overlap_idx = None
            for i, existing in enumerate(result_anns):
                existing_range = existing.get("frame_range", {})
                existing_start = existing_range.get("start", 0)
                existing_end = existing_range.get("end", 0)

                if ann_start <= existing_end and ann_end >= existing_start:
                    overlap_idx = i
                    break

            if overlap_idx is None:
                result_anns.append(ann)
            else:
                existing = result_anns[overlap_idx]
                existing_created = existing.get("created_at")

                if not existing_created and ann_created:
                    result_anns[overlap_idx] = ann
                elif existing_created and ann_created and ann_created > existing_created:
                    result_anns[overlap_idx] = ann

        merged_tracked.extend(result_anns)

    return merged_tracked + untracked
