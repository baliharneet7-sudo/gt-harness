"""Aggregate a push-vs-attached DeepSWE A/B (HAR-93) from per-leg artifacts.

Each planned leg (task x arm x run) is classified before any outcome is read
into the statistics:

* ``never_graded``  - no GRADED official-verifier receipt. Reported, never
  counted as a failure.
* ``excluded``      - provider_failed_calls above the pre-declared threshold
  (rate limiting contaminates the outcome regardless of arm).
* ``included``      - graded and clean.

Paired test: an exact two-sided sign test over tasks, comparing each task's
per-arm solve rate (ties dropped). With one run per task this is exactly the
exact McNemar test on discordant pairs.

Exit codes: 0 ok; 2 when any graded leg cannot prove its step limit (the
effective limit differs from the requested one, or the runner report is
missing) - run 36255669736 asked for 300 steps and ran at 100 unnoticed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ARMS = ("push", "attached")
ARTIFACT_PREFIX = "gt-harness-deepswe-ab-leg-"
_MECHANISM_FIELDS = (
    "gt_bytes_delivered", "gt_tool_calls", "augment_hits", "augment_hit_rate",
    "gt_context_referenced", "gt_context_referenced_rate", "gt_deliveries",
)
_USAGE_FIELDS = ("input_tokens", "output_tokens", "total_cost", "provider_failed_calls")


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _leg_dir(legs_root: Path, leg_id: str) -> Path | None:
    for candidate in sorted(legs_root.glob(f"{ARTIFACT_PREFIX}{leg_id}-*")):
        if candidate.is_dir():
            return candidate
    exact = legs_root / leg_id
    return exact if exact.is_dir() else None


def read_leg(legs_root: Path, leg: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {key: leg[key] for key in ("leg_id", "task", "arm", "run")}
    row["requested_step_limit"] = int(leg["step_limit"])
    directory = _leg_dir(legs_root, leg["leg_id"])
    verifier = None
    agent_dir = None
    if directory is not None:
        for path in sorted(directory.rglob("agent/official-verifier-result.json")):
            verifier = _read(path)
            agent_dir = path.parent
            break
    reward = verifier.get("reward") if verifier else None
    graded = bool(verifier) and verifier.get("status") == "GRADED" and reward in (0, 1)
    row["graded"] = graded
    row["reward"] = int(reward) if graded else None
    row["failure_class"] = (verifier or {}).get("failure_class") or ("artifact_missing" if directory is None else "")
    report = _read(agent_dir / "miniswe_report.json") if agent_dir else None
    product = _read(agent_dir / "gt-run.json") if agent_dir else None
    row["report_present"] = report is not None
    row["effective_step_limit"] = (report or {}).get("effective_step_limit")
    delivery = (report or {}).get("gt_delivery") or {}
    row["gt_delivery_mode"] = delivery.get("gt_delivery_mode")
    for field in _MECHANISM_FIELDS:
        row[field] = delivery.get(field)
    for field in _USAGE_FIELDS:
        row[field] = (product or {}).get(field)
    return row


def sign_test_p(wins_a: int, wins_b: int) -> float:
    """Exact two-sided binomial sign test, p=0.5."""
    n = wins_a + wins_b
    if n == 0:
        return 1.0
    k = min(wins_a, wins_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _mean(values: list[Any]) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, (int, float))
               and not isinstance(value, bool)]
    return round(sum(numbers) / len(numbers), 4) if numbers else None


def aggregate(
    plan: dict[str, Any],
    legs_root: Path,
    *,
    provider_failure_threshold: int,
    comparator: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    legs = [read_leg(legs_root, leg) for leg in plan["legs"]]
    step_violations = []
    for leg in legs:
        if leg["graded"] is not True:
            leg["status"] = "never_graded"
            continue
        failed = leg.get("provider_failed_calls")
        if isinstance(failed, int) and failed > provider_failure_threshold:
            leg["status"] = "excluded"
        else:
            leg["status"] = "included"
        if not leg["report_present"] or leg["effective_step_limit"] != leg["requested_step_limit"]:
            step_violations.append({
                "leg_id": leg["leg_id"],
                "requested": leg["requested_step_limit"],
                "effective": leg["effective_step_limit"],
                "report_present": leg["report_present"],
            })

    arms_present = sorted({leg["arm"] for leg in legs})
    per_task: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for leg in legs:
        if leg["status"] == "included":
            per_task[leg["task"]][leg["arm"]].append(leg["reward"])
    rates = {
        task: {arm: round(sum(values) / len(values), 4) for arm, values in by_arm.items()}
        for task, by_arm in sorted(per_task.items())
    }
    arms: dict[str, Any] = {}
    for arm in arms_present:
        arm_legs = [leg for leg in legs if leg["arm"] == arm]
        included = [leg for leg in arm_legs if leg["status"] == "included"]
        task_rates = [rates[task][arm] for task in rates if arm in rates[task]]
        arms[arm] = {
            "legs": len(arm_legs),
            "included": len(included),
            "excluded": sum(leg["status"] == "excluded" for leg in arm_legs),
            "never_graded": sum(leg["status"] == "never_graded" for leg in arm_legs),
            "tasks_scored": len(task_rates),
            "pass_at_1": _mean(task_rates),
            "solves": sum(leg["reward"] for leg in included),
            "mechanism_means": {field: _mean([leg[field] for leg in included])
                                for field in _MECHANISM_FIELDS + _USAGE_FIELDS},
        }
    paired = None
    if all(arm in arms_present for arm in ARMS):
        both = [task for task in rates if all(arm in rates[task] for arm in ARMS)]
        push_better = sum(rates[task]["push"] > rates[task]["attached"] for task in both)
        attached_better = sum(rates[task]["attached"] > rates[task]["push"] for task in both)
        paired = {
            "tasks_paired": len(both),
            "push_better": push_better,
            "attached_better": attached_better,
            "ties": len(both) - push_better - attached_better,
            "sign_test_p_two_sided": round(sign_test_p(push_better, attached_better), 6),
            "method": "exact sign test over per-task solve rates; ties dropped",
        }
    result = {
        "schema": "gt.deepswe_delivery_ab.v1",
        "provider_failure_threshold": provider_failure_threshold,
        "arms": arms,
        "paired": paired,
        "per_task_solve_rate": rates,
        "never_graded": [leg["leg_id"] for leg in legs if leg["status"] == "never_graded"],
        "excluded": [leg["leg_id"] for leg in legs if leg["status"] == "excluded"],
        "step_limit_violations": step_violations,
        "comparator": comparator,
        "legs": legs,
    }
    return result, (2 if step_violations else 0)


def render_markdown(result: dict[str, Any]) -> str:
    lines = ["# DeepSWE delivery A/B", "",
             "| arm | legs | included | excluded | never graded | tasks | pass@1 | mean bytes | mean tool calls | referenced rate |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, row in result["arms"].items():
        means = row["mechanism_means"]
        lines.append(
            f"| {arm} | {row['legs']} | {row['included']} | {row['excluded']} | "
            f"{row['never_graded']} | {row['tasks_scored']} | {row['pass_at_1']} | "
            f"{means['gt_bytes_delivered']} | {means['gt_tool_calls']} | "
            f"{means['gt_context_referenced_rate']} |")
    paired = result.get("paired")
    if paired:
        lines += ["", f"Paired over {paired['tasks_paired']} tasks: push better "
                  f"{paired['push_better']}, attached better {paired['attached_better']}, "
                  f"ties {paired['ties']}; sign-test p={paired['sign_test_p_two_sided']}."]
    comparator = (result.get("comparator") or {}).get("comparator")
    if comparator:
        lines += ["", f"Leaderboard comparator ({comparator['leaderboard_model']}, "
                  f"effort {comparator['reasoning_effort']}, match {comparator['match']}): "
                  f"pass@1 {comparator['pass_at_1']} over {comparator['n_tasks']} tasks. "
                  "Context only: different run conditions."]
    if result["step_limit_violations"]:
        lines += ["", f"**Step-limit proof failed on {len(result['step_limit_violations'])} leg(s).**"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--legs-root", type=Path, required=True)
    parser.add_argument("--comparator", type=Path)
    parser.add_argument("--provider-failure-threshold", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    comparator = _read(args.comparator) if args.comparator else None
    result, code = aggregate(plan, args.legs_root,
                             provider_failure_threshold=args.provider_failure_threshold,
                             comparator=comparator)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = render_markdown(result)
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
    print(markdown)
    return code


if __name__ == "__main__":
    sys.exit(main())
