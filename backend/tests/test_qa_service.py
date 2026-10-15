"""Unit tests for the pure rules in :mod:`app.services.qa_service`."""
from unittest.mock import MagicMock

from app.models.models import TaskStage, TaskStatus
from app.services.qa_service import (
    QANotFoundError,
    next_stage_after_qa,
    sort_suggestions,
)


def test_next_stage_after_qa_skips_customer_qa():
    stage, task_status = next_stage_after_qa(TaskStage.QA.value, True)
    assert stage == TaskStage.ACCEPTED.value
    assert task_status == TaskStatus.ACCEPTED.value


def test_next_stage_after_qa_goes_to_customer_qa():
    stage, task_status = next_stage_after_qa(TaskStage.QA.value, False)
    assert stage == TaskStage.CUSTOMER_QA.value
    assert task_status == TaskStatus.IN_PROGRESS.value


def test_next_stage_after_customer_qa_accepts():
    stage, task_status = next_stage_after_qa(TaskStage.CUSTOMER_QA.value, False)
    assert stage == TaskStage.ACCEPTED.value
    assert task_status == TaskStatus.ACCEPTED.value


def test_next_stage_after_qa_unknown_stage_returns_none():
    assert next_stage_after_qa(TaskStage.ANNOTATION.value, False) == (None, None)


def _suggestion(severity, created_at):
    return MagicMock(severity=severity, created_at=created_at)


def test_sort_suggestions_orders_by_severity_then_time():
    s1 = _suggestion("low", 3)
    s2 = _suggestion("critical", 1)
    s3 = _suggestion("high", 2)
    s4 = _suggestion("unknown_level", 0)  # defaults to medium (2)
    ordered = sort_suggestions([s1, s2, s3, s4])
    assert ordered == [s2, s3, s4, s1]


def test_sort_suggestions_tie_breaks_by_created_at():
    older = _suggestion("high", 1)
    newer = _suggestion("high", 2)
    assert sort_suggestions([newer, older]) == [older, newer]


def test_not_found_error_messages():
    assert str(QANotFoundError("Task")) == "Task not found"
    assert str(QANotFoundError("QA review", "abc")) == "QA review abc not found"
