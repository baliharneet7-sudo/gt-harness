#!/usr/bin/env python3
"""Executable trigger/payload census for the host-owned 17-feature runtime.

This is a producer test, not a claim that every real task triggers every
feature.  It exercises each boundary deliberately and rejects any delivery
whose payload is empty, stale, or attached to the wrong lifecycle boundary.
"""

from __future__ import annotations

import json

from gt_engine.central_runtime import (
    CENTRAL_FEATURE_IDS,
    CentralFeatureRuntime,
    WorkspaceTransition,
)


def census() -> dict:
    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task("Implement the requested change", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="rg -n 'Bottle|caller' .",
        output=(
            "bottle.py:10:class Bottle\n"
            "tests/test_bottle.py:20:caller references Bottle; existing registry pattern\n"
        ),
        returncode=0,
        transition=WorkspaceTransition(1, "search", "r0", "r0"),
        revision="r0",
    )
    runtime.observe_action(
        action_id=2,
        command="sed -i 's/def f(/def f(x:/' app.py",
        output="def f(x: -> syntax error",
        returncode=0,
        transition=WorkspaceTransition(
            2,
            "edit",
            "r0",
            "r1",
            created=("new_module.py",),
            modified=("app.py",),
        ),
        revision="r1",
    )
    for action_id in (3, 4):
        runtime.observe_action(
            action_id=action_id,
            command="pytest -q",
            output="1 failed: Error",
            returncode=1,
            transition=WorkspaceTransition(action_id, "test", "r1", "r1"),
            revision="r1",
        )
    runtime.record_syntax(action_id=2, revision="r1", failed=True, reason="fixture_syntax_failure")
    runtime.record_submit(action_id=5, revision="r1", refused=True, sensor_healthy=True)
    summary = runtime.summary()
    summary["all_17_deliverable"] = (
        summary["feature_count"] == 17
        and set(summary["feature_ids"]) == set(CENTRAL_FEATURE_IDS)
        and all(summary["delivered_counts"][feature] >= 1 for feature in CENTRAL_FEATURE_IDS)
        and all(
            row["fresh"] and row["payload"].get("message") and row["model_visible"]
            for row in summary["receipts"]
        )
    )
    return summary


def main() -> int:
    result = census()
    print(json.dumps(result, indent=2, sort_keys=True))
    print("ALL_17_DELIVERABLE" if result["all_17_deliverable"] else "NOT_READY")
    return 0 if result["all_17_deliverable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
