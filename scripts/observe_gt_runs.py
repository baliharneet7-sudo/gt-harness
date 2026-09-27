"""Read a GT-on run's task artifacts and say what GT actually did.

For every task directory under ``--root`` (a ``gh run download`` of one run)
this reports, from the runner's own receipts - never from the job status:

* delivery: mode, treatment validity, graph readiness, effective step limit
* usage: ``gt-*`` tool calls by name and outcome, grep augmentation calls and
  hits, bytes delivered, and how often a delivery was referenced by the
  agent's next action (``gt_context_referenced``)
* outcome: official reward and the model's step count
* feature coverage: which of the 21 audited features reached the agent,
  through which surface (``FEATURE_SURFACES``), across the whole run

It reads ``agent/miniswe_report.json`` and the GT journal (``events.jsonl``,
rows ``gt_tool_call`` / ``gt_augment``). Nothing is inferred from logs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from gt_engine.attached_delivery import FEATURE_SURFACES


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _events(agent_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # The runner tees one journal to agent/events.jsonl and keeps the original
    # under agent/gt-state/<task>/; reading both double-counts every row.
    primary = agent_dir / "events.jsonl"
    paths = [primary] if primary.is_file() else sorted(agent_dir.parent.rglob("events.jsonl"))[:1]
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _reward(agent_dir: Path) -> Any:
    verifier = _read(agent_dir / "official-verifier-result.json")
    if verifier and "reward" in verifier:
        return verifier["reward"]
    for path in agent_dir.parent.rglob("reward.txt"):
        return path.read_text(encoding="utf-8").strip()
    for path in agent_dir.parent.rglob("result.json"):
        doc = _read(path) or {}
        rewards = (doc.get("verifier_result") or {}).get("rewards") or {}
        if "reward" in rewards:
            return rewards["reward"]
    return None


def _task_name(agent_dir: Path) -> str:
    trial = agent_dir.parent.name
    return trial.split("__", 1)[0] if "__" in trial else trial


def observe_task(agent_dir: Path) -> dict[str, Any]:
    report = _read(agent_dir / "miniswe_report.json") or {}
    delivery = report.get("gt_delivery") or {}
    events = _events(agent_dir)
    tool_rows = [row for row in events if row.get("event") == "gt_tool_call"]
    augment_rows = [row for row in events if row.get("event") == "gt_augment"]
    event_names = Counter(str(row.get("event")) for row in events)
    unavailable = [row for row in events if row.get("event") == "index_unavailable"]
    if event_names.get("initial_index_ready") or event_names.get("graph_publication"):
        graph = "ready"
    elif unavailable:
        graph = "none: " + str(unavailable[0].get("error") or unavailable[0].get("error_type"))[:80]
    else:
        graph = "unknown"
    return {
        "task": _task_name(agent_dir),
        "graph": graph,
        "report_present": bool(report),
        "reward": _reward(agent_dir),
        "mode": delivery.get("gt_delivery_mode"),
        "treatment_valid": delivery.get("treatment_valid"),
        "invalid_reason": delivery.get("treatment_invalid_reason") or "",
        "requested_step_limit": report.get("requested_step_limit"),
        "effective_step_limit": report.get("effective_step_limit"),
        "steps": report.get("n_steps") or report.get("steps") or report.get("api_calls"),
        "exit_status": report.get("exit_status") or report.get("status"),
        "tool_calls": delivery.get("gt_tool_calls", len(tool_rows)),
        "tool_calls_by_name": delivery.get("gt_tool_calls_by_name")
        or dict(Counter(str(row.get("tool")) for row in tool_rows)),
        "tool_answered": delivery.get("gt_tool_answered"),
        "tool_no_answer": delivery.get("gt_tool_no_answer"),
        "tool_errors": (delivery.get("gt_tool_usage_errors") or 0) + (delivery.get("gt_tool_faults") or 0),
        "tool_status": dict(Counter(str(row.get("status")) for row in tool_rows)),
        "search_commands": delivery.get("gt_search_commands"),
        "augment_calls": delivery.get("augment_calls", len(augment_rows)),
        "augment_hits": delivery.get("augment_hits",
                                     sum(row.get("outcome") == "hit" for row in augment_rows)),
        "augment_outcomes": dict(Counter(str(row.get("outcome")).split(":")[0] for row in augment_rows)),
        "bytes_delivered": delivery.get("gt_bytes_delivered"),
        "deliveries": delivery.get("gt_context_deliveries"),
        "referenced": delivery.get("gt_context_referenced"),
        "referenced_rate": delivery.get("gt_context_referenced_rate"),
        "graph_events": {name: count for name, count in event_names.items()
                         if any(key in name for key in ("graph", "index", "amend", "refresh"))},
    }


def feature_coverage(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    used: Counter[str] = Counter()
    for task in tasks:
        for name, count in (task.get("tool_calls_by_name") or {}).items():
            used[name] += int(count or 0)
        used["augment"] += int(task.get("augment_hits") or 0)
    any_valid_graph = any(task.get("treatment_valid") for task in tasks)
    coverage: dict[str, dict[str, Any]] = {}
    for feature, surfaces in FEATURE_SURFACES.items():
        if surfaces == ("substrate",):
            coverage[feature] = {"reached": any_valid_graph, "via": "substrate (every answer)"}
            continue
        hits = {surface: used[surface] for surface in surfaces if used[surface]}
        coverage[feature] = {"reached": bool(hits), "via": hits or "unused"}
    return coverage


def render(tasks: list[dict[str, Any]], coverage: dict[str, dict[str, Any]]) -> str:
    lines = ["| task | reward | graph | mode | valid | steps (limit) | gt tools | augment hit/calls | referenced | bytes |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for t in tasks:
        limit = t["effective_step_limit"]
        lines.append(
            f"| {t['task']} | {t['reward']} | {t['graph']} | {t['mode']} | {t['treatment_valid']}"
            f"{(' (' + t['invalid_reason'] + ')') if t['invalid_reason'] else ''} "
            f"| {t['steps']} ({limit}) | {t['tool_calls']} | {t['augment_hits']}/{t['augment_calls']} "
            f"| {t['referenced']}/{t['deliveries']} | {t['bytes_delivered']} |"
        )
    lines += ["", "Tool calls by name:"]
    for t in tasks:
        lines.append(f"- {t['task']}: {t['tool_calls_by_name'] or '{}'} status={t['tool_status'] or '{}'}"
                     f" augment={t['augment_outcomes'] or '{}'}")
    reached = sum(1 for row in coverage.values() if row["reached"])
    lines += ["", f"Feature coverage: {reached}/{len(coverage)} reached the agent"]
    for feature, row in coverage.items():
        lines.append(f"- {'YES' if row['reached'] else 'no '} {feature}: {row['via']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    agent_dirs = sorted({path.parent for path in args.root.rglob("agent/miniswe_report.json")})
    if not agent_dirs:
        agent_dirs = sorted({path.parent for path in args.root.rglob("agent/official-verifier-result.json")})
    tasks = [observe_task(agent_dir) for agent_dir in agent_dirs]
    coverage = feature_coverage(tasks)
    print(render(tasks, coverage))
    if args.json:
        args.json.write_text(json.dumps({"tasks": tasks, "coverage": coverage}, indent=2, default=str),
                             encoding="utf-8")
    return 0 if tasks else 1


if __name__ == "__main__":
    sys.exit(main())
