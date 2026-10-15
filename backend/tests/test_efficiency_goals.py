"""Unit tests for pure helpers in the efficiency goals sub-domain."""
from app.services.efficiency.goals import (
    LABEL_GOAL_TYPES,
    _progress_percentage,
)


def test_progress_percentage_basic():
    assert _progress_percentage(5, 10) == 50.0


def test_progress_percentage_caps_at_100():
    assert _progress_percentage(20, 10) == 100


def test_progress_percentage_zero_target_is_zero():
    assert _progress_percentage(5, 0) == 0


def test_label_goal_types():
    assert {"daily_labels", "weekly_labels", "monthly_labels"} == LABEL_GOAL_TYPES
