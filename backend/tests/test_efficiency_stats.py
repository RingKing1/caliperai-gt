"""Unit tests for pure helpers extracted from efficiency stats/report routes."""
from datetime import datetime

from app.services.efficiency.reports import format_duration
from app.services.efficiency.stats import (
    build_quality_metrics,
    leaderboard_period_start,
    resolve_active_time,
    team_period_start,
    throughput_metrics,
)

NOW = datetime(2026, 10, 15, 12, 30, 45, 123)


def test_team_period_start_today_is_midnight():
    assert team_period_start(NOW, "today") == datetime(2026, 10, 15, 0, 0, 0)


def test_team_period_start_week_and_month_are_relative_days():
    assert team_period_start(NOW, "week") == datetime(2026, 10, 8, 12, 30, 45, 123)
    assert team_period_start(NOW, "month") == datetime(2026, 9, 15, 12, 30, 45, 123)
    # unknown period falls back to the 30-day window
    assert team_period_start(NOW, "quarter") == datetime(2026, 9, 15, 12, 30, 45, 123)


def test_leaderboard_period_start_all_time_is_2020():
    assert leaderboard_period_start(NOW, "all_time") == datetime(2020, 1, 1)
    assert leaderboard_period_start(NOW, "today") == datetime(2026, 10, 15)


def test_quality_metrics_zeros_without_reviews():
    q = build_quality_metrics(0, 0, 0)
    assert q.first_time_acceptance_rate == 0.0
    assert q.rejection_rate == 0.0
    assert q.quality_score == 0.0
    assert q.revision_turnaround_hours == 0.0


def test_quality_metrics_counts_rates():
    q = build_quality_metrics(tasks_accepted=8, tasks_rejected=2, revision_count=1)
    assert q.rejection_rate == 20.0
    # (8 - min(1, 8)) / max(8, 1) * 100
    assert q.first_time_acceptance_rate == 87.5
    # 100 - 20*0.5 - 1*2 = 88
    assert q.quality_score == 88.0


def test_quality_metrics_score_is_clamped_to_zero():
    q = build_quality_metrics(tasks_accepted=0, tasks_rejected=100, revision_count=50)
    assert q.rejection_rate == 100.0
    assert q.quality_score == 0.0


def test_throughput_requires_minimum_tracked_time():
    assert throughput_metrics(59, 10) == (0.0, 0.0)
    labels_per_hour, avg_seconds = throughput_metrics(3600, 90)
    assert labels_per_hour == 90.0
    assert avg_seconds == 40.0


def test_throughput_requires_annotations():
    assert throughput_metrics(3600, 0) == (0.0, 0.0)


def test_resolve_active_time_priority():
    assert resolve_active_time(100, 50, 20) == 100
    assert resolve_active_time(0, 50, 20) == 50
    assert resolve_active_time(0, 0, 20) == 20


def test_format_duration():
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(3661) == "1h 1m 1s"
