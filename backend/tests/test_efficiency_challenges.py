"""Unit tests for pure helpers in the efficiency challenges sub-domain."""
from app.services.efficiency.challenges import CHALLENGE_LABEL_TYPES, _progress_percentage


def test_progress_percentage_basic_caps_and_zero_target():
    assert _progress_percentage(50, 200) == 25.0
    assert _progress_percentage(300, 200) == 100
    assert _progress_percentage(10, 0) == 0


def test_label_goal_types_contents():
    assert {"total_labels", "daily_labels", "weekly_labels", "labels"} == CHALLENGE_LABEL_TYPES
