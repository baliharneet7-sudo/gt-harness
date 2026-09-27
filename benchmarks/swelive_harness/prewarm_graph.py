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
    output = Path(os.environ.get("GT_PREWARM_RECEIPT", "/logs/agent/pre-spend-graph.json"))
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
        # The 921bec20 runtime adopts its startup graph only after this dense
        # sidecar is current.  Finishing both before the provider call closes
        # the publication/edit race without changing the pinned product code.
        # The bound stays below Pier's 2,100-second setup watchdog.
        embedding_budget_seconds=1800.0,
    )
    # Neither miss may cost the task. The runtime already runs a task whose
    # graph is unavailable degraded-and-graded (an attached run is marked
    # treatment-invalid, never killed), and hybrid retrieval re-ranks the
    # lexical candidates with an on-demand dense index - it does not need this
    # whole-repository sidecar. Aborting here lost beancount__beancount-931 in
    # run 36303715831: the graph was built, 10,007 documents' dense sidecar
    # was estimated at 2,382 s against an 1,800 s budget, the install step
    # failed, and the agent never ran. Record the miss instead.
    graph_ready = bool(receipt.success and receipt.graph_db)
    dense_ready = receipt.embedding_state == "refreshed"
    if not graph_ready:
        print(
            "[GT][WARNING] task-local graph prewarm did not build: "
            f"{receipt.error_type or receipt.status}: {receipt.error_diagnostic}"
        )
    elif not dense_ready:
        print(
            "[GT][WARNING] task-local dense sidecar not prewarmed: "
            f"{receipt.embedding_state}: {receipt.embedding_failure_reason}"
        )
    payload = asdict(receipt) if is_dataclass(receipt) else dict(vars(receipt))
    payload.update(
        {
            "schema": "gt.swelive.pre_spend_graph.v1",
            "task_id": task_id,
            "workspace": str(workspace),
            "state_root": str(state_root),
            "source_revision": source_revision,
            "ready_before_provider": graph_ready,
            "dense_ready_before_provider": dense_ready,
            "dense_failure_reason": "" if dense_ready else str(receipt.embedding_failure_reason or receipt.embedding_state),
            "status": "ready" if graph_ready and dense_ready else ("graph_only" if graph_ready else "graph_unavailable"),
        }
    )
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
