"""Unit tests for the pure rules in :mod:`app.services.scene_service`."""
import pytest

from app.services.scene_service import (
    SceneValidationError,
    parse_label_filters,
    split_filter_values,
)


def test_split_filter_values_handles_none_commas_and_blanks():
    assert split_filter_values(None) == []
    assert split_filter_values(["car, truck", " bus ", "", "pedestrian"]) == [
        "car",
        "truck",
        "bus",
        "pedestrian",
    ]


def test_parse_label_filters_normalizes_and_dedupes_classes():
    classes, groups = parse_label_filters(None, [" Car ", "car", "truck"], [])
    assert classes == ["car", "truck"]
    assert groups == []


def test_parse_label_filters_resolves_group_aliases():
    classes, groups = parse_label_filters(None, [], ["motorcycle", "two_wheeler"])
    assert classes == []
    assert groups == ["two_wheeler"]


def test_parse_label_filters_free_text_resolves_class_or_group():
    classes, groups = parse_label_filters("car, vehicle", [], [])
    assert classes == ["car"]
    assert groups == ["vehicle"]


def test_parse_label_filters_rejects_class_name_in_groups():
    with pytest.raises(SceneValidationError) as exc_info:
        parse_label_filters(None, [], ["car"])
    detail = exc_info.value.detail
    assert detail["error"] == "unknown_class_group"
    assert detail["invalid_groups"] == ["car"]
    assert "vehicle" in detail["valid_groups"]


def test_parse_label_filters_empty():
    assert parse_label_filters(None, [], []) == ([], [])
