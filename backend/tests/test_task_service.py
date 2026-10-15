"""Unit tests for the pure rules in :mod:`app.services.task_service`."""
from unittest.mock import MagicMock

from asyncpg import Range as PgRange

from app.models.models import TaskStatus
from app.services.task_service import (
    VALID_TRANSITIONS,
    compute_frame_window,
    frame_range_to_postgres,
    is_task_participant,
    revision_reset_reason,
)


def test_frame_range_to_postgres_is_half_open():
    result = frame_range_to_postgres(0, 9)
    assert (result.lower, result.upper) == (0, 10)
    assert result.upper_inc is False


def test_compute_frame_window_with_context_clamps_to_zero():
    window = compute_frame_window(PgRange(5, 15), 10, 3, True)
    assert window == (0, 17)


def test_compute_frame_window_without_context_is_inclusive():
    window = compute_frame_window(PgRange(5, 15), 10, 3, False)
    assert window == (5, 14)


def test_valid_transitions_table():
    assert TaskStatus.IN_PROGRESS.value in VALID_TRANSITIONS[TaskStatus.PENDING.value]
    assert TaskStatus.IN_PROGRESS.value not in VALID_TRANSITIONS[TaskStatus.SUBMITTED.value]
    assert VALID_TRANSITIONS[TaskStatus.ACCEPTED.value] == []


def test_revision_reset_reason_stage_change_takes_precedence():
    reason = revision_reset_reason(
        "qa", "annotation", {"revision_count": 0}, stage_changing=True
    )
    assert reason == "stage_change"


def test_revision_reset_reason_same_stage_annotation():
    reason = revision_reset_reason(
        "annotation", "annotation", {}, stage_changing=False
    )
    assert reason == "same_stage_annotation"


def test_revision_reset_reason_explicit_zero():
    reason = revision_reset_reason("qa", "qa", {"revision_count": 0}, False)
    assert reason == "explicit_zero"


def test_revision_reset_reason_none_when_no_rule_matches():
    assert revision_reset_reason("qa", "qa", {"name": "rename"}, False) is None


def test_is_task_participant_matches_any_of_three_roles():
    user = MagicMock(id="u1")
    assignee_task = MagicMock(assignee_id="u1", reviewer_id="u2", customer_reviewer_id="u3")
    reviewer_task = MagicMock(assignee_id="u2", reviewer_id="u1", customer_reviewer_id="u3")
    outsider_task = MagicMock(assignee_id="u2", reviewer_id="u3", customer_reviewer_id="u4")
    assert is_task_participant(user, assignee_task)
    assert is_task_participant(user, reviewer_task)
    assert not is_task_participant(user, outsider_task)
