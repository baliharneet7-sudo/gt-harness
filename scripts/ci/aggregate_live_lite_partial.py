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
        metrics = next(iter(task_dir.rglob("gt_deep_metrics_*.json")), None)
        document = {}
        if metrics:
            try: document = json.loads(metrics.read_text(encoding="utf-8"))
            except (OSError, ValueError): document = {}
        agent = document.get("agent") if isinstance(document.get("agent"), dict) else {}
        efficiency = document.get("efficiency") if isinstance(document.get("efficiency"), dict) else {}
        rows.append({"task": task, "reward": reward, "error": error,
                     "resolved": document.get("resolved"),
                     "agent_steps": agent.get("action_count"),
                     "llm_calls": efficiency.get("llm_calls"),
                     "input_tokens": efficiency.get("llm_tokens_in"),
                     "output_tokens": efficiency.get("llm_tokens_out"),
                     "cached_tokens": efficiency.get("llm_tokens_cached"),
                     "total_tokens": efficiency.get("llm_tokens_total"),
                     "cost_usd": efficiency.get("llm_cost_usd")})
    graded = [r for r in rows if r["reward"] is not None]
    solved = [r for r in graded if r["reward"] == 1.0]
    payload = {
        "schema": "gt.live_lite.partial.v1",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "returned": len(rows), "graded": len(graded),
        "ungraded": len(rows) - len(graded), "solved": len(solved),
        "unsolved": len(graded) - len(solved),
        "metrics": {k: sum((r.get(k) or 0) for r in rows)
                    for k in ("agent_steps", "llm_calls", "input_tokens", "output_tokens", "cached_tokens", "total_tokens")},
        "cost_usd_observed": any(r.get("cost_usd") is not None for r in rows),
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
