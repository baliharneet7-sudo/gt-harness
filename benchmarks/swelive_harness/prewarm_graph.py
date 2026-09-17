"""Build the task-local GT graph before a paid SWE-Live model request."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path

from gt_engine.engine_state import RuntimeLayout
from gt_engine.indexer import ensure_index_with_receipt
from gt_engine.runtime_observation import capture_workspace


def main() -> int:
    workspace = Path.cwd().resolve()
    state_root = Path(os.environ["GT_STATE_DIR"]).resolve()
    task_id = os.environ["GT_TASK_ID"].strip()
    if not task_id:
        raise RuntimeError("GT_TASK_ID is required for the task-local graph prewarm")

    layout = RuntimeLayout.resolve(
        workspace=workspace,
        state_root=state_root,
        task_id=task_id,
    )
    source_revision = capture_workspace(
        workspace, excluded_roots=layout.excluded_roots
    ).revision
    output = Path("/logs/agent/pre-spend-graph.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema": "gt.swelive.pre_spend_graph.v1",
                "task_id": task_id,
                "source_revision": source_revision,
                "status": "building",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = ensure_index_with_receipt(
        workspace,
        layout=layout,
        excluded_roots=layout.excluded_roots,
        contract_store_path=layout.contract_store_path,
        source_revision=source_revision,
        # Pre-spend exists only to close the graph-publication/edit race.  A
        # cold dense sidecar can take many minutes and is a cache, so give its
        # planner a deliberately impossible budget here.  The normal runtime
        # refreshes it asynchronously after the provider session starts.
        embedding_budget_seconds=1.0,
    )
    if not receipt.success or not receipt.graph_db:
        raise RuntimeError(
            "task-local graph prewarm failed: "
            f"{receipt.error_type or receipt.status}: {receipt.error_diagnostic}"
        )
    payload = asdict(receipt) if is_dataclass(receipt) else dict(vars(receipt))
    payload.update(
        {
            "schema": "gt.swelive.pre_spend_graph.v1",
            "task_id": task_id,
            "workspace": str(workspace),
            "state_root": str(state_root),
            "source_revision": source_revision,
            "ready_before_provider": True,
            "dense_refresh_deferred_to_runtime": True,
            "status": "ready",
        }
    )
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
