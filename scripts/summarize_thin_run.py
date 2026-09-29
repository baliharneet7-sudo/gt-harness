"""Summarize a thin-GT run: per task reward, exit, steps, tokens and GT features.

Reads the Harbor trial directories under ``--root`` (downloaded artifacts),
never assumes a layout beyond Harbor's own: ``<trial>/result.json`` and
``<trial>/agent/miniswe_trajectory.json``. A task with no graded result is
reported as such - never as a fail.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# A feature "works" on a task when its counter is positive in info.gt.metrics.
FEATURES = {
    "grep augment": "augment_hits",
    "read augment": "read_augment_hits",
    "edit block": "edit_augment_hits",
    "failure block": "failure_augment_hits",
    "gt-* tool answered": "gt_tool_answered",
    "submit review": "submit_review_held",
}
PROBLEMS = ("augment_timeouts", "augment_faults", "gt_tool_faults", "action_augment_errors")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def trial_row(result_path: Path) -> dict:
    result = _load(result_path)
    trial = result_path.parent
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    exception = (result.get("exception_info") or {}).get("exception_type") or ""
    trajectory = _load(trial / "agent" / "miniswe_trajectory.json")
    info = trajectory.get("info") or {}
    metrics = ((info.get("gt") or {}).get("metrics")) or {}
    usage = [((m.get("extra") or {}).get("response") or {}).get("usage") or {}
             for m in trajectory.get("messages") or () if m.get("role") == "assistant"]
    return {
        "task": str(result.get("task_name") or trial.name.split("__")[0]),
        "graded": reward is not None,
        "reward": reward,
        "exception": exception,
        "exit_status": info.get("exit_status", ""),
        "mini_version": info.get("mini_version", ""),
        "agent_type": (info.get("config") or {}).get("agent_type", ""),
        "steps": sum(1 for m in trajectory.get("messages") or () if m.get("role") == "assistant"),
        "input_tokens": sum(int(u.get("prompt_tokens") or 0) for u in usage),
        "output_tokens": sum(int(u.get("completion_tokens") or 0) for u in usage),
        "features": {name: int(metrics.get(key) or 0) for name, key in FEATURES.items()},
        "problems": {key: metrics.get(key, 0) for key in PROBLEMS if metrics.get(key)},
        "gt_seconds": round(float(metrics.get("augment_seconds") or 0) + float(metrics.get("probe_seconds") or 0), 2),
    }


def summarize(root: Path, tasks: list[str]) -> dict:
    rows: dict[str, dict] = {}
    for path in sorted(root.rglob("result.json")):
        if (path.parent / "agent").is_dir():
            row = trial_row(path)
            rows[row["task"]] = row
    missing = [task for task in tasks if task not in rows]
    graded = [row for row in rows.values() if row["graded"]]
    coverage = {name: sum(1 for row in rows.values() if row["features"][name] > 0) for name in FEATURES}
    return {
        "tasks_requested": len(tasks),
        "trials_found": len(rows),
        "graded": len(graded),
        "solved": sum(1 for row in graded if row["reward"] == 1),
        "missing": missing,
        "feature_coverage": coverage,
        "rows": sorted(rows.values(), key=lambda row: row["task"]),
    }


def render(summary: dict) -> str:
    lines = [f"# Thin GT run: {summary['solved']}/{summary['graded']} solved of {summary['graded']} graded "
             f"({summary['trials_found']} trials, {summary['tasks_requested']} requested)", ""]
    if summary["missing"]:
        lines.append(f"No trial for: {', '.join(summary['missing'])}")
        lines.append("")
    lines.append("## GT features (tasks where each fired)")
    for name, count in summary["feature_coverage"].items():
        lines.append(f"- {name}: {count}/{summary['trials_found']}")
    lines += ["", "| task | reward | exit | steps | in tok | out tok | GT s | features | problems |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row in summary["rows"]:
        fired = ", ".join(f"{name} {count}" for name, count in row["features"].items() if count) or "-"
        problems = ", ".join(f"{key} {value}" for key, value in row["problems"].items()) or "-"
        reward = row["reward"] if row["graded"] else f"ungraded {row['exception']}"
        lines.append(f"| {row['task']} | {reward} | {row['exit_status']} | {row['steps']} | "
                     f"{row['input_tokens']} | {row['output_tokens']} | {row['gt_seconds']} | {fired} | {problems} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--tasks", default="[]")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    summary = summarize(Path(args.root), json.loads(args.tasks))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "SUMMARY.md").write_text(render(summary), encoding="utf-8")
    print(render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
