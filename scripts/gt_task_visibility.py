"""Per-task run visibility for the GT benchmark workflows.

Two modes:

  emit       run inside a matrix task job (``if: always()``); writes one
             outcome record for that task.
  aggregate  run in a final job (``if: always()``); folds every emitted
             record into a table for the run summary.

Outcomes are deliberately coarse and mutually exclusive:

  passed        the task ran and its receipt says it solved.
  failed_task   the task ran to completion and did not solve. A real result.
  failed_infra  the task never got a fair attempt -- registry throttle, agent
                timeout, runner/artifact fault, or a pre-execution gate.
  running       still in flight when the record was written.

Separating ``failed_infra`` from ``failed_task`` is the point: an infra failure
must never be read as a benchmark result.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

PASSED = "passed"
FAILED_TASK = "failed_task"
FAILED_INFRA = "failed_infra"
RUNNING = "running"

_ORDER = (PASSED, FAILED_TASK, FAILED_INFRA, RUNNING)

# Substrings that prove the task never got a fair attempt.
_INFRA_MARKERS = (
    "agenttimeouterror",
    "toomanyrequests",
    "too many requests",
    "rate limit",
    "429 client error",
    "connection reset",
    "manifest unknown",
    "pull access denied",
    "error pulling image",
    "no space left on device",
    "the runner has received a shutdown signal",
    "failed to download action",
    "actions/upload-artifact",
    "no gt provider query started",
)

_RECEIPT_NAMES = ("central_receipt.json", "receipt.json", "result.json")
_SOLVED_KEYS = ("resolved", "solved", "passed", "success", "is_resolved")
_SOLVED_STATUSES = {"resolved", "solved", "passed", "success"}


def _read(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def looks_like_infra(text: str) -> bool:
    """True when the log text carries a known infrastructure fault marker."""
    lowered = text.lower()
    return any(marker in lowered for marker in _INFRA_MARKERS)


def find_receipt(results_dir: Path) -> dict[str, Any] | None:
    """Return the first task receipt under results_dir, if one was written."""
    for name in _RECEIPT_NAMES:
        for candidate in sorted(results_dir.rglob(name)):
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def receipt_says_solved(receipt: dict[str, Any]) -> bool:
    """Interpret the several shapes a solved-flag takes across harnesses."""
    for key in _SOLVED_KEYS:
        value = receipt.get(key)
        if isinstance(value, bool):
            return value
    reward = receipt.get("reward")
    if isinstance(reward, (int, float)) and not isinstance(reward, bool):
        return reward > 0
    return str(receipt.get("status") or "").lower() in _SOLVED_STATUSES


def classify(job_status: str, results_dir: Path, log_path: Path | None) -> str:
    """Decide a single task's outcome from job status, receipt, and log."""
    status = (job_status or "").lower()
    if status in {"cancelled", "canceled"}:
        return FAILED_INFRA
    if status in {"", "in_progress", "queued"}:
        return RUNNING

    receipt = find_receipt(results_dir)
    if receipt is None:
        # Nothing was produced: infra fault, or a gate that fired before the
        # task ever started. Either way it is not a benchmark result.
        return FAILED_INFRA

    if receipt_says_solved(receipt):
        return PASSED
    # A receipt exists, so the task genuinely ran. Only an explicit infra
    # marker can still demote it out of the graded set.
    return FAILED_INFRA if looks_like_infra(_read(log_path)) else FAILED_TASK


def reason_for(outcome: str, job_status: str, log_path: Path | None) -> str:
    """Short human-readable reason, used in the failure column."""
    if outcome == PASSED:
        return ""
    if outcome == RUNNING:
        return "in flight"
    lowered = _read(log_path).lower()
    for marker in _INFRA_MARKERS:
        if marker in lowered:
            return marker
    if (job_status or "").lower() in {"cancelled", "canceled"}:
        return "cancelled"
    if outcome == FAILED_INFRA:
        return "no receipt produced (gate or infra)"
    return "task did not solve"


def emit(args: argparse.Namespace) -> int:
    log_path = Path(args.log) if args.log and Path(args.log).exists() else None
    outcome = classify(args.job_status, Path(args.results_dir), log_path)
    record = {
        "workflow": args.workflow,
        "task": args.task,
        "outcome": outcome,
        "reason": reason_for(outcome, args.job_status, log_path),
        "job_status": args.job_status,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"`{record['task']}` -> **{outcome}** {record['reason']}\n\n")

    print(f"{args.task}: {outcome} {record['reason']}".rstrip())
    return 0


def _render(workflow: str, counts: dict[str, int], records: list[dict[str, Any]]) -> str:
    total = len(records)
    graded = counts[PASSED] + counts[FAILED_TASK]
    rate = f"{counts[PASSED]}/{graded}" if graded else "0/0 (nothing graded)"

    lines = [
        f"## {workflow} - task visibility",
        "",
        f"**Dispatched:** {total} &nbsp;&nbsp; **Pass rate (graded only):** {rate}",
        "",
        "| Outcome | Count | Meaning |",
        "|---|---:|---|",
        f"| passed | {counts[PASSED]} | solved |",
        f"| failed_task | {counts[FAILED_TASK]} | ran, did not solve - a real result |",
        f"| failed_infra | {counts[FAILED_INFRA]} | **never got a fair attempt - not a result** |",
        f"| running | {counts[RUNNING]} | still in flight |",
        "",
    ]

    failures = [r for r in records if r.get("outcome") in (FAILED_TASK, FAILED_INFRA)]
    if failures:
        lines += ["### Current failures", "", "| Task | Outcome | Reason |", "|---|---|---|"]
        for record in sorted(failures, key=lambda r: str(r.get("task"))):
            reason = record.get("reason") or "-"
            lines.append(f"| `{record.get('task')}` | {record.get('outcome')} | {reason} |")
        lines.append("")

    return "\n".join(lines)


def aggregate(args: argparse.Namespace) -> int:
    records: list[dict[str, Any]] = []
    for path in sorted(Path(args.input_dir).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "outcome" in data:
            records.append(data)

    counts = {name: 0 for name in _ORDER}
    for record in records:
        outcome = record.get("outcome", FAILED_INFRA)
        counts[outcome] = counts.get(outcome, 0) + 1

    report = _render(args.workflow, counts, records)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    print(report)

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(
                {"workflow": args.workflow, "counts": counts, "records": records},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    graded = counts[PASSED] + counts[FAILED_TASK]
    if counts[FAILED_INFRA] and graded == 0:
        print("::warning::every task failed on infrastructure; this run produced no benchmark result")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="GT per-task run visibility")
    sub = parser.add_subparsers(dest="mode", required=True)

    emitter = sub.add_parser("emit", help="write one task outcome record")
    emitter.add_argument("--workflow", required=True)
    emitter.add_argument("--task", required=True)
    emitter.add_argument("--job-status", default="")
    emitter.add_argument("--results-dir", default="results")
    emitter.add_argument("--log", default="")
    emitter.add_argument("--output", required=True)
    emitter.set_defaults(func=emit)

    agg = sub.add_parser("aggregate", help="fold task records into a run summary")
    agg.add_argument("--workflow", required=True)
    agg.add_argument("--input-dir", required=True)
    agg.add_argument("--json-output", default="")
    agg.set_defaults(func=aggregate)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
