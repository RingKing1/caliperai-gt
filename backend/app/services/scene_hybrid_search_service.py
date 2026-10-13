"""Hybrid scene search: label filters first, CLIP vector ranking second.

Layer 1 (structured) narrows scenes down by exact, explainable label
statistics (class presence, two-wheeler ratio, static/dynamic mix, ...).
Layer 2 (semantic) then ranks only those candidates with Chinese-CLIP for
queries labels cannot express ("堵车", "雨夜路口", "施工路段").

When no semantic query is supplied this reduces to the structured layer,
so a single endpoint covers both modes.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scene_search_service import (
    SceneSearchFilters,
    _matches_filters,
    _populate_group_frame_counts,
    aggregate_scene_annotation_stats,
    build_group_stats,
)
from app.services.scene_semantic_search_service import search_scenes_semantic


def _label_profile(scene: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, explainable label statistics for one scene."""
    groups: Dict[str, Any] = {}
    for group_name, stats in scene.get("group_stats", {}).items():
        groups[group_name] = {
            "box_count": stats["box_count"],
            "ratio": round(float(stats["ratio"]), 4),
            "frame_ratio": round(float(stats["frame_ratio"]), 4),
            "track_count": stats["track_count"],
        }
    return {
        "total_objects": scene["total_objects"],
        "primary_class": scene.get("primary_class"),
        "class_counts": scene["class_counts"],
        "class_ratios": {
            name: round(count / scene["total_objects"], 4)
            for name, count in scene["class_counts"].items()
        }
        if scene["total_objects"]
        else {},
        "groups": groups,
    }


async def search_scenes_hybrid(
    db: AsyncSession,
    filters: SceneSearchFilters,
    semantic_query: Optional[str] = None,
    cameras: Optional[List[str]] = None,
    min_similarity: float = 0.0,
    top_k_frames: Optional[int] = None,
    candidate_pool: Optional[int] = None,
    preview_frames: int = 5,
) -> Dict[str, Any]:
    # --- Layer 1: structured label filter over ALL scenes ---------------
    scenes = await aggregate_scene_annotation_stats(
        db,
        dataset_id=filters.dataset_id,
        name_contains=filters.name_contains,
    )
    for scene in scenes.values():
        scene["group_stats"] = build_group_stats(scene)
    _populate_group_frame_counts(scenes)

    candidates: Dict[UUID, Dict[str, Any]] = {}
    for scene in scenes.values():
        matched, label_score, reasons = _matches_filters(scene, filters)
        if matched:
            scene["primary_class"] = (
                max(scene["class_counts"], key=scene["class_counts"].get)
                if scene["class_counts"]
                else None
            )
            scene["label_match_score"] = round(label_score, 6)
            scene["matched_reasons"] = reasons
            candidates[scene["scene_id"]] = scene

    base_response: Dict[str, Any] = {
        "mode": "hybrid" if semantic_query else "structured",
        "semantic_query": semantic_query,
        "classes": filters.classes,
        "groups": filters.groups,
        "total": 0,
        "results": [],
    }

    if not candidates:
        return base_response

    # No semantic query -> return structured candidates ordered by labels.
    if not semantic_query:
        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                item["label_match_score"],
                item["total_objects"],
                item["scene_name"],
            ),
            reverse=True,
        )
        page = ordered[filters.offset : filters.offset + filters.limit]
        base_response["total"] = len(ordered)
        base_response["results"] = [
            {
                "scene_id": scene["scene_id"],
                "scene_name": scene["scene_name"],
                "dataset_id": scene["dataset_id"],
                "frame_count": scene["frame_count"],
                "label_match_score": scene["label_match_score"],
                "matched_reasons": scene["matched_reasons"],
                "label_profile": _label_profile(scene),
            }
            for scene in page
        ]
        return base_response

    # --- Layer 2: CLIP ranking restricted to the label-filtered set ------
    candidate_ids = list(candidates.keys())
    semantic = await search_scenes_semantic(
        db,
        query_text=semantic_query,
        dataset_id=filters.dataset_id,
        cameras=cameras,
        min_similarity=min_similarity,
        top_k_frames=top_k_frames,
        candidate_pool=candidate_pool,
        preview_frames=preview_frames,
        limit=max(len(candidate_ids), filters.limit),
        scene_ids=candidate_ids,
    )

    merged = []
    for row in semantic["results"]:
        scene = candidates.get(row["scene_id"])
        if scene is None:
            continue
        merged.append(
            {
                "scene_id": row["scene_id"],
                "scene_name": row["scene_name"],
                "dataset_id": row["dataset_id"],
                "frame_count": row["frame_count"],
                "semantic_score": row["score"],
                "max_similarity": row["max_similarity"],
                "matched_frames": row["matched_frames"],
                "preview_frames": row["preview_frames"],
                "label_match_score": scene["label_match_score"],
                "matched_reasons": scene["matched_reasons"],
                "label_profile": _label_profile(scene),
            }
        )

    merged = merged[filters.offset : filters.offset + filters.limit]
    base_response["model"] = semantic["model"]
    base_response["min_similarity"] = min_similarity
    base_response["total"] = len(merged)
    base_response["results"] = merged
    return base_response
