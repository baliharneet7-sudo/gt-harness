"""Predeclared GT-on experiment assignment and Pareto release gates."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import fmean

BASELINE_TASKS = 89
BASELINE_SOLVED = 66
BASELINE_TOKENS = 242_540_464
BASELINE_ACTIONS = 4_394
BASELINE_ERRORS = 4
MINIMUM_MEAN_SOLVED = 72.0
MAXIMUM_EFFICIENCY_RATIO = 0.85


@dataclass(frozen=True, slots=True)
class TrialRecord:
    task: str
    trial: int
    arm: str
    solved: bool
    tokens: float
    actions: float
    errored: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseAssessment:
    passed: bool
    failures: tuple[str, ...]
    mean_solved: float
    mean_tokens: float
    mean_actions: float
    max_errors_per_run: int
    solve_delta_lower_95: float
    token_ratio_upper_95: float
    action_ratio_upper_95: float


def deterministic_arm(
    task_id: str,
    trial_index: int,
    feature: str,
    feature_version: str,
    seed: str,
) -> str:
    payload = "\0".join(
        (task_id, str(trial_index), feature, feature_version, seed)
    ).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return "treatment" if value & 1 else "shadow"


def select_eligible_panel(
    severity_by_task: Mapping[str, float],
    *,
    minimum: int = 20,
    maximum: int = 30,
) -> tuple[str, ...]:
    if len(severity_by_task) < minimum:
        return ()
    ordered = sorted(severity_by_task, key=lambda task: (-severity_by_task[task], task))
    return tuple(ordered[:maximum])


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile needs at least one value")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(probability * len(ordered))))
    return ordered[index]


def _group_candidate(records: Iterable[TrialRecord]) -> dict[str, list[TrialRecord]]:
    grouped: dict[str, list[TrialRecord]] = {}
    for record in records:
        grouped.setdefault(record.task, []).append(record)
    return grouped


def assess_release(
    baseline: Mapping[str, TrialRecord],
    candidate: Iterable[TrialRecord],
    *,
    bootstrap_samples: int = 100_000,
    seed: int = 20260803,
    runtime_errors: int = 0,
    permanently_blocked_submissions: int = 0,
) -> ReleaseAssessment:
    """Evaluate the frozen-baseline, five-repeat GT-on Pareto contract."""
    if len(baseline) != BASELINE_TASKS:
        raise ValueError(f"baseline must contain exactly {BASELINE_TASKS} tasks")
    grouped = _group_candidate(candidate)
    if set(grouped) != set(baseline):
        raise ValueError("candidate and baseline task sets differ")
    trial_ids = {record.trial for records in grouped.values() for record in records}
    if len(trial_ids) != 5:
        raise ValueError("release gate requires exactly five candidate trials per task")
    if any(
        len(records) != 5 or {record.trial for record in records} != trial_ids
        for records in grouped.values()
    ):
        raise ValueError("every candidate task must contain the same five unique trials")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")

    tasks = sorted(baseline)
    candidate_solve = {
        task: fmean(float(record.solved) for record in grouped[task]) for task in tasks
    }
    candidate_tokens = {
        task: fmean(record.tokens for record in grouped[task]) for task in tasks
    }
    candidate_actions = {
        task: fmean(record.actions for record in grouped[task]) for task in tasks
    }
    mean_solved = sum(candidate_solve.values())
    mean_tokens = sum(candidate_tokens.values())
    mean_actions = sum(candidate_actions.values())
    errors_by_trial = {
        trial: sum(
            1
            for records in grouped.values()
            for record in records
            if record.trial == trial and record.errored
        )
        for trial in trial_ids
    }
    max_errors = max(errors_by_trial.values(), default=0)

    rng = random.Random(seed)
    solve_deltas: list[float] = []
    token_ratios: list[float] = []
    action_ratios: list[float] = []
    for _ in range(bootstrap_samples):
        sample = rng.choices(tasks, k=len(tasks))
        solve_deltas.append(
            fmean(candidate_solve[task] - float(baseline[task].solved) for task in sample)
        )
        baseline_token_sum = sum(baseline[task].tokens for task in sample)
        baseline_action_sum = sum(baseline[task].actions for task in sample)
        token_ratios.append(
            sum(candidate_tokens[task] for task in sample) / baseline_token_sum
        )
        action_ratios.append(
            sum(candidate_actions[task] for task in sample) / baseline_action_sum
        )

    solve_lcb = _percentile(solve_deltas, 0.05)
    token_ucb = _percentile(token_ratios, 0.95)
    action_ucb = _percentile(action_ratios, 0.95)
    failures: list[str] = []
    if mean_solved < MINIMUM_MEAN_SOLVED or solve_lcb <= 0:
        failures.append("solve_rate")
    if mean_tokens > BASELINE_TOKENS * MAXIMUM_EFFICIENCY_RATIO or token_ucb > 0.85:
        failures.append("tokens")
    if mean_actions > BASELINE_ACTIONS * MAXIMUM_EFFICIENCY_RATIO or action_ucb > 0.85:
        failures.append("actions")
    if max_errors > BASELINE_ERRORS:
        failures.append("errors")
    if runtime_errors:
        failures.append("runtime_errors")
    if permanently_blocked_submissions:
        failures.append("blocked_submissions")

    return ReleaseAssessment(
        passed=not failures,
        failures=tuple(failures),
        mean_solved=mean_solved,
        mean_tokens=mean_tokens,
        mean_actions=mean_actions,
        max_errors_per_run=max_errors,
        solve_delta_lower_95=solve_lcb,
        token_ratio_upper_95=token_ucb,
        action_ratio_upper_95=action_ucb,
    )
