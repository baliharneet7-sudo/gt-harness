from __future__ import annotations

from gt_engine.benchmark_population import build_benchmark_population


def _trial(task: str, *, reward=None, exception=None):
    row = {"task_name": task}
    if reward is not None:
        row["verifier_result"] = {"rewards": {"reward": reward}}
    if exception is not None:
        row["exception_info"] = {"exception_type": exception}
    return row


def test_population_assigns_one_typed_status_to_every_expected_task() -> None:
    receipt = build_benchmark_population(
        ("solved", "unsolved", "censored", "error", "ungraded", "missing"),
        (
            _trial("solved", reward=1),
            _trial("unsolved", reward=0),
            _trial("censored", exception="AgentTimeoutError"),
            _trial("error", exception="ValueError"),
            _trial("ungraded"),
        ),
    ).as_dict()

    assert receipt["status_counts"] == {
        "CENSORED": 1,
        "ERROR": 1,
        "MISSING": 1,
        "MISSING_VERIFIER": 1,
        "SOLVED": 1,
        "UNSOLVED_GRADED": 1,
    }
    assert receipt["missing_tasks"] == ["missing"]
    assert receipt["graded_tasks"] == ["solved", "unsolved"]
    assert receipt["complete"] is False


def test_population_cannot_report_no_missing_tasks_when_a_trial_is_absent() -> None:
    receipt = build_benchmark_population(("alpha", "beta"), (_trial("alpha", reward=1),))

    assert receipt.as_dict()["missing_tasks"] == ["beta"]
    assert receipt.complete is False


def test_population_reports_duplicates_and_unexpected_tasks_separately() -> None:
    receipt = build_benchmark_population(
        ("alpha",),
        (
            _trial("alpha", reward=1),
            _trial("alpha", reward=1),
            _trial("extra", reward=1),
        ),
    ).as_dict()

    assert receipt["duplicate_tasks"] == ["alpha"]
    assert receipt["unexpected_tasks"] == ["extra"]
    assert receipt["missing_tasks"] == []
    assert receipt["complete"] is False
