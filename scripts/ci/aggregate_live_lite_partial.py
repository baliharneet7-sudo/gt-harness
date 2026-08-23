#!/usr/bin/env python3
"""Conservative merge-independent Live Lite artifact summary."""
from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    root = Path(os.environ.get("ARTIFACT_ROOT", "tasks"))
    rows: list[dict] = []
    for reward_path in sorted(root.rglob("reward.txt")):
        task_dir = next((p for p in reward_path.parents
                         if p.name.startswith("ll-full-")), reward_path.parent)
        task = task_dir.name.removeprefix("ll-full-")
        try:
            text = reward_path.read_text(encoding="utf-8").strip()
            reward = float(text)
            reward = reward if reward in (0.0, 1.0) else None
            error = None if reward is not None else "invalid_reward"
        except (OSError, ValueError) as exc:
            reward, error = None, f"unreadable_reward:{type(exc).__name__}"
        rows.append({"task": task, "reward": reward, "error": error})
    graded = [r for r in rows if r["reward"] is not None]
    solved = [r for r in graded if r["reward"] == 1.0]
    payload = {
        "schema": "gt.live_lite.partial.v1",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "returned": len(rows), "graded": len(graded),
        "ungraded": len(rows) - len(graded), "solved": len(solved),
        "unsolved": len(graded) - len(solved),
        "rows": sorted(rows, key=lambda r: r["task"]),
    }
    output = Path(os.environ.get("OUTPUT", "live_lite_partial_summary.json"))
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("## Live Lite partial results")
    print(f"returned={payload['returned']} graded={payload['graded']} "
          f"solved={payload['solved']} unsolved={payload['unsolved']} "
          f"ungraded={payload['ungraded']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
