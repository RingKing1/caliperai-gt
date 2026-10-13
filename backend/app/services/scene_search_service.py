"""Structured scene search over imported 3D annotations.

This intentionally uses label statistics rather than embeddings. It answers
class-presence queries ("car scenes", "two-wheeler scenes") by aggregating
``annotations_3d`` through tasks to scenes.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


CLASS_GROUPS = {
    "vehicle": [
        "car",
        "truck",
        "bus",
        "trailer",
        "construction_vehicle",
    ],
    "two_wheeler": ["motorcycle", "bicycle"],
    "vru": ["pedestrian"],
    "static_obstacle": ["barrier", "traffic_cone"],
}

GROUP_ALIASES = {
    "vehicles": "vehicle",
    "vehicle": "vehicle",
    "car_like": "vehicle",
    "motor_vehicle": "vehicle",
    "motor_vehicles": "vehicle",
    "车辆": "vehicle",
    "机动车": "vehicle",
    "汽车场景": "vehicle",
    "two_wheeler": "two_wheeler",
    "two_wheelers": "two_wheeler",
    "two-wheelers": "two_wheeler",
    "two_wheel": "two_wheeler",
    "2_wheeler": "two_wheeler",
    "二轮车": "two_wheeler",
    "两轮车": "two_wheeler",
    "非机动车": "two_wheeler",
    "motorcycle": "two_wheeler",
    "motorcycles": "two_wheeler",
    "摩托车": "two_wheeler",
    "bicycle": "two_wheeler",
    "bicycles": "two_wheeler",
    "自行车": "two_wheeler",
    "vru": "vru",
    "pedestrian": "vru",
    "pedestrians": "vru",
    "行人": "vru",
    "人": "vru",
    "static": "static_obstacle",
    "static_obstacle": "static_obstacle",
    "obstacle": "static_obstacle",
    "obstacles": "static_obstacle",
    "障碍物": "static_obstacle",
    "静态障碍物": "static_obstacle",
}

CLASS_ALIASES = {
    "car": "car",
    "cars": "car",
    "汽车": "car",
    "轿车": "car",
    "小汽车": "car",
    "truck": "truck",
    "trucks": "truck",
    "卡车": "truck",
    "货车": "truck",
    "bus": "bus",
    "buses": "bus",
    "公交车": "bus",
    "巴士": "bus",
    "trailer": "trailer",
    "trailers": "trailer",
    "拖车": "trailer",
    "construction_vehicle": "construction_vehicle",
    "construction": "construction_vehicle",
    "工程车": "construction_vehicle",
    "motorcycle_class": "motorcycle",
    "pedestrian_class": "pedestrian",
    "barrier": "barrier",
    "护栏": "barrier",
    "traffic_cone": "traffic_cone",
    "cone": "traffic_cone",
    "cones": "traffic_cone",
    "锥桶": "traffic_cone",
    "路锥": "traffic_cone",
}


def normalize_class_name(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def resolve_group(value: str) -> Optional[str]:
    return GROUP_ALIASES.get(normalize_class_name(value))


def resolve_term(value: str) -> tuple[str, str]:
    """Resolve a user term to ``("class", name)`` or ``("group", name)``."""
    normalized = normalize_class_name(value)
    if normalized in CLASS_ALIASES:
        return "class", CLASS_ALIASES[normalized]
    group_name = GROUP_ALIASES.get(normalized)
    if group_name is not None:
        return "group", group_name
    return "class", normalized


@dataclass
class SceneSearchFilters:
    dataset_id: Optional[UUID] = None
    classes: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    name_contains: Optional[str] = None
    min_objects: int = 0
    min_class_ratio: float = 0.0
    min_group_ratio: float = 0.0
    min_group_frame_ratio: float = 0.0
    limit: int = 50
    offset: int = 0


async def aggregate_scene_annotation_stats(
    db: AsyncSession,
    dataset_id: Optional[UUID] = None,
    name_contains: Optional[str] = None,
) -> Dict[UUID, Dict[str, Any]]:
    """Return per-scene per-class box/track/frame counts."""
    where_clauses = ["s.is_deleted = FALSE"]
    params: Dict[str, Any] = {}
    if dataset_id is not None:
        where_clauses.append("s.dataset_id = :dataset_id")
        params["dataset_id"] = dataset_id
    if name_contains:
        where_clauses.append("s.name ILIKE :name_contains")
        params["name_contains"] = f"%{name_contains}%"

    sql = text(
        f"""
        SELECT
            s.id AS scene_id,
            s.name AS scene_name,
            s.dataset_id AS dataset_id,
            s.frame_count AS frame_count,
            a.class_id AS class_id,
            COUNT(*) AS box_count,
            COUNT(DISTINCT a.track_id) AS track_count,
            COUNT(DISTINCT a.frame_id) AS frame_count_with_class
        FROM annotations_3d a
        JOIN tasks t ON t.id = a.task_id
        JOIN scenes s ON s.id = t.scene_id
        WHERE {' AND '.join(where_clauses)}
        GROUP BY s.id, s.name, s.dataset_id, s.frame_count, a.class_id
        """
    )
    result = await db.execute(sql, params)

    scenes: Dict[UUID, Dict[str, Any]] = {}
    for row in result.mappings():
        scene_id = row["scene_id"]
        scene = scenes.setdefault(
            scene_id,
            {
                "scene_id": scene_id,
                "scene_name": row["scene_name"],
                "dataset_id": row["dataset_id"],
                "frame_count": int(row["frame_count"] or 0),
                "total_objects": 0,
                "class_counts": {},
                "class_track_counts": {},
                "class_frame_counts": {},
            },
        )
        class_id = normalize_class_name(row["class_id"])
        box_count = int(row["box_count"])
        scene["total_objects"] += box_count
        scene["class_counts"][class_id] = box_count
        scene["class_track_counts"][class_id] = int(row["track_count"])
        scene["class_frame_counts"][class_id] = int(row["frame_count_with_class"])
    return scenes


def build_group_stats(scene_stats: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    total_objects = scene_stats["total_objects"]
    group_stats = {}
    for group_name, members in CLASS_GROUPS.items():
        group_classes = [
            name for name in members if name in scene_stats["class_counts"]
        ]
        boxes = sum(scene_stats["class_counts"].get(name, 0) for name in members)
        tracks = sum(scene_stats["class_track_counts"].get(name, 0) for name in members)
        group_stats[group_name] = {
            "box_count": boxes,
            "track_count": tracks,
            "frame_count": 0,
            "ratio": boxes / total_objects if total_objects else 0.0,
            "frame_ratio": 0.0,
            "classes": group_classes,
        }
    return group_stats


def _populate_group_frame_counts(
    scenes: Dict[UUID, Dict[str, Any]],
) -> None:
    # Frame presence for a class group cannot be summed because one frame may
    # contain several member classes. The box-level aggregate does not carry
    # frame identity, so this remains conservative until a frame-level query is
    # needed; ratio filtering primarily uses object ratios.
    for scene in scenes.values():
        scene_frame_count = max(scene["frame_count"], 1)
        for group_name, members in CLASS_GROUPS.items():
            max_frames = max(
                (scene["class_frame_counts"].get(name, 0) for name in members),
                default=0,
            )
            scene["group_stats"][group_name]["frame_count"] = max_frames
            scene["group_stats"][group_name]["frame_ratio"] = (
                max_frames / scene_frame_count
            )


def _matches_filters(
    scene_stats: Dict[str, Any],
    filters: SceneSearchFilters,
) -> tuple[bool, float, List[str]]:
    total_objects = scene_stats["total_objects"]
    if total_objects < filters.min_objects:
        return False, 0.0, []

    matched_reasons = []
    score = 0.0

    for class_name in filters.classes:
        count = scene_stats["class_counts"].get(class_name, 0)
        ratio = count / total_objects if total_objects else 0.0
        if count <= 0 or ratio < filters.min_class_ratio:
            return False, 0.0, []
        matched_reasons.append(f"class:{class_name}")
        score += ratio

    for group_name in filters.groups:
        group = scene_stats["group_stats"][group_name]
        if (
            group["box_count"] <= 0
            or group["ratio"] < filters.min_group_ratio
            or group["frame_ratio"] < filters.min_group_frame_ratio
        ):
            return False, 0.0, []
        matched_reasons.append(f"group:{group_name}")
        score += group["ratio"]

    return True, score, matched_reasons


async def search_scenes(
    db: AsyncSession,
    filters: SceneSearchFilters,
) -> List[Dict[str, Any]]:
    scenes = await aggregate_scene_annotation_stats(
        db,
        dataset_id=filters.dataset_id,
        name_contains=filters.name_contains,
    )
    for scene in scenes.values():
        scene["group_stats"] = build_group_stats(scene)
    _populate_group_frame_counts(scenes)

    results = []
    for scene in scenes.values():
        matched, score, reasons = _matches_filters(scene, filters)
        if matched:
            primary_class = (
                max(scene["class_counts"], key=scene["class_counts"].get)
                if scene["class_counts"]
                else None
            )
            results.append(
                {
                    **scene,
                    "primary_class": primary_class,
                    "match_score": round(score, 6),
                    "matched_reasons": reasons,
                }
            )

    results.sort(
        key=lambda item: (
            item["match_score"],
            item["total_objects"],
            item["scene_name"],
        ),
        reverse=True,
    )
    return results[filters.offset : filters.offset + filters.limit]
