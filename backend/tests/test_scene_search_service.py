"""Unit tests for structured scene search filtering (no DB required)."""
from __future__ import annotations

from app.services.scene_search_service import (
    CLASS_GROUPS,
    SceneSearchFilters,
    _matches_filters,
    build_group_stats,
    normalize_class_name,
    resolve_term,
)


def _make_scene(class_counts: dict[str, int], frame_count: int = 100):
    total = sum(class_counts.values())
    return {
        "scene_id": None,
        "scene_name": "scene",
        "dataset_id": None,
        "frame_count": frame_count,
        "total_objects": total,
        "class_counts": dict(class_counts),
        "class_track_counts": {name: count for name, count in class_counts.items()},
        "class_frame_counts": {
            name: min(frame_count, count) for name, count in class_counts.items()
        },
    }


class TestResolveTerm:
    def test_concrete_class_english(self):
        assert resolve_term("Car") == ("class", "car")
        assert resolve_term("traffic-cone") == ("class", "traffic_cone")

    def test_concrete_class_chinese(self):
        assert resolve_term("汽车") == ("class", "car")
        assert resolve_term("卡车") == ("class", "truck")

    def test_group_aliases_chinese(self):
        assert resolve_term("二轮车") == ("group", "two_wheeler")
        assert resolve_term("车辆") == ("group", "vehicle")
        assert resolve_term("行人") == ("group", "vru")

    def test_member_class_collapses_to_group(self):
        assert resolve_term("motorcycle") == ("group", "two_wheeler")
        assert resolve_term("bicycle") == ("group", "two_wheeler")

    def test_unknown_term_falls_back_to_class(self):
        assert resolve_term("animal") == ("class", "animal")

    def test_normalize_class_name(self):
        assert normalize_class_name("  Fire Truck ") == "fire_truck"


class TestGroupStats:
    def test_group_aggregation_and_ratio(self):
        scene = _make_scene({"car": 70, "motorcycle": 20, "pedestrian": 10})
        groups = build_group_stats(scene)
        assert groups["vehicle"]["box_count"] == 70
        assert groups["two_wheeler"]["box_count"] == 20
        assert groups["vru"]["box_count"] == 10
        assert round(groups["two_wheeler"]["ratio"], 4) == 0.2
        assert groups["two_wheeler"]["classes"] == ["motorcycle"]

    def test_group_membership_covers_defined_classes(self):
        assert set(CLASS_GROUPS["two_wheeler"]) == {"motorcycle", "bicycle"}


class TestMatchesFilters:
    def test_group_filter_matches(self):
        scene = _make_scene({"car": 80, "bicycle": 20})
        scene["group_stats"] = build_group_stats(scene)
        filters = SceneSearchFilters(groups=["two_wheeler"], min_group_ratio=0.15)
        matched, score, reasons = _matches_filters(scene, filters)
        assert matched
        assert score >= 0.15
        assert "group:two_wheeler" in reasons

    def test_group_filter_rejects_low_ratio(self):
        scene = _make_scene({"car": 96, "motorcycle": 4})
        scene["group_stats"] = build_group_stats(scene)
        filters = SceneSearchFilters(groups=["two_wheeler"], min_group_ratio=0.1)
        matched, _, _ = _matches_filters(scene, filters)
        assert not matched

    def test_class_filter_matches(self):
        scene = _make_scene({"car": 90, "truck": 10})
        scene["group_stats"] = build_group_stats(scene)
        filters = SceneSearchFilters(classes=["truck"])
        matched, _, reasons = _matches_filters(scene, filters)
        assert matched
        assert "class:truck" in reasons

    def test_class_filter_missing_class_rejects(self):
        scene = _make_scene({"car": 100})
        scene["group_stats"] = build_group_stats(scene)
        filters = SceneSearchFilters(classes=["bus"])
        matched, _, _ = _matches_filters(scene, filters)
        assert not matched

    def test_min_objects_gate(self):
        scene = _make_scene({"car": 3})
        scene["group_stats"] = build_group_stats(scene)
        filters = SceneSearchFilters(min_objects=10)
        matched, _, _ = _matches_filters(scene, filters)
        assert not matched

    def test_group_frame_ratio_filter(self):
        scene = _make_scene({"car": 90, "motorcycle": 10}, frame_count=100)
        scene["group_stats"] = build_group_stats(scene)
        for group in scene["group_stats"].values():
            group["frame_count"] = 0
            group["frame_ratio"] = 0.0
        filters = SceneSearchFilters(
            groups=["two_wheeler"], min_group_frame_ratio=0.5
        )
        matched, _, _ = _matches_filters(scene, filters)
        assert not matched
