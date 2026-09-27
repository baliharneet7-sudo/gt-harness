"""Live 21-feature matrix of a GT-on run from its small per-task artifacts.

Reads only the per-task progress receipts (TB2 ``benchmark-progress-tb2-gt-*``,
SWE-Live ``benchmark-progress-swelive-*``) or DeepSWE ``gt-features-deepswe-*``
- no graphs, no trajectories - so it can run while the benchmark is going.

For each feature, across finished tasks:
  delivered   tasks where a delivery carried it (``features_reached``)
  available   tasks whose graph held data for it (``feature_inventory``)
  gap         available but not delivered - either the agent never took the
              action that surfaces it (no trigger) or a delivery defect; the
              task's journal (``features=`` on hit rows) separates the two.

Usage:
  python scripts/live_feature_matrix.py --repo hbali-stack/gt-harness --run 36356069277
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

FEATURES = [f"F{i}" for i in range(1, 22)]
PATTERNS = ("benchmark-progress-", "gt-features-deepswe-")


def _gh(args: list[str], token: str | None) -> str:
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    return subprocess.run(["gh", *args], capture_output=True, text=True, env=env, check=True).stdout


def _rows_from(directory: Path) -> list[dict[str, Any]]:
    rows = []
    for path in directory.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):  # progress receipt
            for task in data["tasks"]:
                delivery = task.get("gt_delivery") or {}
                rows.append({"task": task.get("task") or task.get("id") or path.parent.name,
                             "reward": task.get("reward"), **delivery})
        elif isinstance(data, dict) and "gt_delivery" in data:  # miniswe report (DeepSWE)
            task_file = path.parent / "task.txt"
            rows.append({"task": task_file.read_text().strip() if task_file.is_file() else path.parent.name,
                         **(data.get("gt_delivery") or {})})
    return rows


def matrix(rows: list[dict[str, Any]]) -> str:
    lines = [f"tasks with a report: {len(rows)}",
             f"tasks with a graph: {sum(1 for r in rows if (r.get('feature_inventory') or {}).get('F2'))}",
             "", "| feature | delivered | available | gap (available, not delivered) |", "|---|---|---|---|"]
    for feature in FEATURES:
        delivered = sum(1 for r in rows if (r.get("features_reached") or {}).get(feature))
        available = sum(1 for r in rows if (r.get("feature_inventory") or {}).get(feature))
        gap = sum(1 for r in rows if (r.get("feature_inventory") or {}).get(feature)
                  and not (r.get("features_reached") or {}).get(feature))
        lines.append(f"| {feature} | {delivered} | {available} | {gap} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--run", required=True)
    parser.add_argument("--token-user", default="", help="gh auth account for the repo")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    token = _gh(["auth", "token", "-u", args.token_user], None).strip() if args.token_user else None
    names = [n for n in _gh(["api", f"repos/{args.repo}/actions/runs/{args.run}/artifacts?per_page=100",
                             "--paginate", "-q", ".artifacts[]|select(.expired==false)|.name"], token).split()
             if n.startswith(PATTERNS)]
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            subprocess.run(["gh", "run", "download", args.run, "-R", args.repo, "-n", name, "-D",
                            str(Path(tmp) / name)], capture_output=True,
                           env={**os.environ, **({"GH_TOKEN": token} if token else {})})
        rows = _rows_from(Path(tmp))
    print(matrix(rows))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
