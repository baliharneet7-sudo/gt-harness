"""Self-describing benchmark population accounting.

Every declared task receives exactly one typed population record.  Missing,
duplicate, errored, censored, and ungraded trials remain distinct so a partial
run cannot masquerade as a smaller complete benchmark.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from gt_engine.deep_metrics import TrialOutcome, classify_trial_outcome


class PopulationStatus(StrEnum):
    SOLVED = "SOLVED"
    UNSOLVED_GRADED = "UNSOLVED_GRADED"
    CENSORED = "CENSORED"
    ERROR = "ERROR"
    MISSING_VERIFIER = "MISSING_VERIFIER"
    MISSING = "MISSING"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class PopulationRecord:
    task: str
    status: PopulationStatus
    trial_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "status": self.status.value,
            "trial_count": self.trial_count,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkPopulationReceipt:
    records: tuple[PopulationRecord, ...]
    unexpected_tasks: tuple[str, ...]

    @property
    def status_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(row.status.value for row in self.records).items()))

    def tasks_with(self, *statuses: PopulationStatus) -> tuple[str, ...]:
        selected = frozenset(statuses)
        return tuple(row.task for row in self.records if row.status in selected)

    @property
    def complete(self) -> bool:
        return bool(self.records) and not self.tasks_with(
            PopulationStatus.MISSING,
            PopulationStatus.DUPLICATE,
        ) and not self.unexpected_tasks

    def as_dict(self) -> dict[str, Any]:
        missing = self.tasks_with(PopulationStatus.MISSING)
        duplicate = self.tasks_with(PopulationStatus.DUPLICATE)
        return {
            "schema": "gt.benchmark_population.v1",
            "expected_count": len(self.records),
            "observed_trial_count": sum(row.trial_count for row in self.records),
            "observed_unique_count": sum(row.trial_count > 0 for row in self.records),
            "complete": self.complete,
            "status_counts": self.status_counts,
            "missing_tasks": list(missing),
            "duplicate_tasks": list(duplicate),
            "unexpected_tasks": list(self.unexpected_tasks),
            "graded_tasks": list(
                self.tasks_with(
                    PopulationStatus.SOLVED,
                    PopulationStatus.UNSOLVED_GRADED,
                )
            ),
            "solved_tasks": list(self.tasks_with(PopulationStatus.SOLVED)),
            "unsolved_graded_tasks": list(
                self.tasks_with(PopulationStatus.UNSOLVED_GRADED)
            ),
            "censored_tasks": list(self.tasks_with(PopulationStatus.CENSORED)),
            "errored_tasks": list(self.tasks_with(PopulationStatus.ERROR)),
            "missing_verifier_tasks": list(
                self.tasks_with(PopulationStatus.MISSING_VERIFIER)
            ),
            "records": [row.as_dict() for row in self.records],
        }


def trial_task_identity(trial: Mapping[str, Any]) -> str:
    raw = str(trial.get("task_name") or trial.get("trial_name") or trial.get("task") or "")
    return raw.split("__", 1)[0].strip()


def _population_status(trial: Mapping[str, Any]) -> PopulationStatus:
    outcome = classify_trial_outcome(dict(trial))
    return {
        TrialOutcome.SOLVED: PopulationStatus.SOLVED,
        TrialOutcome.UNSOLVED_GRADED: PopulationStatus.UNSOLVED_GRADED,
        TrialOutcome.CENSORED: PopulationStatus.CENSORED,
        TrialOutcome.ERROR: PopulationStatus.ERROR,
        TrialOutcome.MISSING_VERIFIER: PopulationStatus.MISSING_VERIFIER,
    }[outcome]


def build_benchmark_population(
    expected_tasks: Iterable[str],
    trials: Iterable[Mapping[str, Any]],
) -> BenchmarkPopulationReceipt:
    expected = tuple(str(task).strip() for task in expected_tasks if str(task).strip())
    if len(set(expected)) != len(expected):
        raise ValueError("expected task population contains duplicates")
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trial in trials:
        identity = trial_task_identity(trial)
        if identity:
            grouped[identity].append(trial)
    records: list[PopulationRecord] = []
    for task in expected:
        rows = grouped.get(task, [])
        status = (
            PopulationStatus.MISSING
            if not rows
            else PopulationStatus.DUPLICATE
            if len(rows) != 1
            else _population_status(rows[0])
        )
        records.append(PopulationRecord(task=task, status=status, trial_count=len(rows)))
    return BenchmarkPopulationReceipt(
        records=tuple(records),
        unexpected_tasks=tuple(sorted(set(grouped) - set(expected))),
    )


__all__ = [
    "BenchmarkPopulationReceipt",
    "PopulationRecord",
    "PopulationStatus",
    "build_benchmark_population",
    "trial_task_identity",
]
