"""Replay a recorded live GT-on task through the CURRENT attached delivery.

Live runs are the wrong place to find delivery bugs: every one found so far
(a failure trigger keyed on the shell return code while agents pipe tests
through ``tail``; 84-522 s blocking amends; silent edit blocks after a
second edit) was visible in data the run already recorded. This replays that
data offline, with no model and no container:

* the workspace is rebuilt at the task's base revision from the LSP
  enrichment's ``source/`` snapshot, with every file an edit transaction
  touched restored to its earliest pre-image, then checked against the
  initial graph's ``file_hashes``;
* the initial published graph is adopted exactly as the runtime adopts it;
* the agent's own actions are replayed in order through
  ``AttachedDelivery.observe_turn``: its commands and raw outputs from the
  trajectory, its edits from the recorded edit transactions (applied to disk
  and recorded as transactions, so the graph goes stale the same way), and
  the runtime's parsed test outcome for each action.

The result is what the current code would have attached to that exact
trajectory: blocks, features, and wall time per action. It cannot replay
what a different block would have made the agent do next.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_events(agent_dir: Path) -> list[dict[str, Any]]:
    path = agent_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()]


def _transactions(agent_dir: Path) -> dict[int, dict[str, Any]]:
    by_action: dict[int, dict[str, Any]] = {}
    for blob in agent_dir.glob("gt-state/*/edit_transactions/*.json"):
        data = json.loads(blob.read_text(encoding="utf-8"))
        by_action[int(data["action_id"])] = data
    return by_action


def _content(hexed: Any) -> bytes | None:
    return None if hexed in (None, "None", "") else bytes.fromhex(str(hexed))


def _initial_graph(agent_dir: Path, events: list[dict[str, Any]]) -> Path | None:
    ready = next((r for r in events if r.get("event") == "initial_index_ready"), None)
    revisions = list(agent_dir.glob("gt-state/*/revisions/*/graph.db"))
    if ready is not None:
        for graph in revisions:
            if graph.parent.name == str(ready.get("graph_revision")):
                return graph
    return max(revisions, key=lambda p: p.stat().st_mtime, default=None) if revisions else None


def rebuild_workspace(agent_dir: Path, graph: Path, tx: dict[int, dict[str, Any]], dest: Path) -> dict[str, int]:
    """Base-revision workspace; returns hash-check counts against the graph."""
    sources = sorted(agent_dir.glob("gt-state/*/enrichments/*/source"),
                     key=lambda p: sum(1 for _ in p.rglob("*")), reverse=True)
    if sources:
        shutil.copytree(sources[0], dest, dirs_exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    restored: set[str] = set()
    for action in sorted(tx):
        for change in tx[action]["changes"]:
            path = str(change["path"])
            if path in restored:
                continue
            restored.add(path)
            target = dest / path
            before = _content(change.get("before_content_hex"))
            if before is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
    conn = sqlite3.connect(graph.resolve().as_uri() + "?mode=ro", uri=True)
    counts = {"match": 0, "mismatch": 0, "missing": 0}
    try:
        for path, digest in conn.execute("SELECT file_path, content_hash FROM file_hashes"):
            target = dest / path
            if not target.is_file():
                counts["missing"] += 1
            elif hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                counts["match"] += 1
            else:
                counts["mismatch"] += 1
    finally:
        conn.close()
    return counts


def _actions(agent_dir: Path) -> list[dict[str, Any]]:
    """(command, raw output, returncode) per bash tool call, in order."""
    data = json.loads((agent_dir / "miniswe_trajectory.json").read_text(encoding="utf-8"))
    pending: dict[str, str] = {}
    actions: list[dict[str, Any]] = []
    for message in data.get("messages") or []:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                try:
                    command = json.loads(call["function"]["arguments"]).get("command", "")
                except (KeyError, TypeError, ValueError):
                    command = ""
                pending[str(call.get("id"))] = command
        elif message.get("role") == "tool":
            extra = message.get("extra") or {}
            actions.append({
                "command": pending.pop(str(message.get("tool_call_id")), ""),
                "output": str(extra.get("raw_output") or ""),
                "returncode": extra.get("returncode"),
            })
    return actions


def replay(agent_dir: Path, *, workdir: Path) -> dict[str, Any]:
    from gt_engine.attached_delivery import ATTACHED, DELIVERY_MODE_ENV, AttachedDelivery
    from gt_engine.engine_state import RuntimeLayout
    from gt_engine.gt_session import GTSession, GTSessionConfig
    from gt_engine.miniswe_integration import MiniSweAdapter
    from gt_engine.runtime_observation import capture_workspace, diff_workspace

    import os

    os.environ[DELIVERY_MODE_ENV] = ATTACHED
    events = _load_events(agent_dir)
    tx = _transactions(agent_dir)
    graph = _initial_graph(agent_dir, events)
    task = agent_dir.parent.name.split("__")[0]
    if graph is None:
        return {"task": task, "skipped": "no graph recorded"}
    root = workdir / "repo"
    hashes = rebuild_workspace(agent_dir, graph, tx, root)
    report = json.loads((agent_dir / "miniswe_report.json").read_text(encoding="utf-8"))
    issue = str(report.get("task") or report.get("instance_prompt") or "")
    if not issue:
        traj = json.loads((agent_dir / "miniswe_trajectory.json").read_text(encoding="utf-8"))
        issue = next((str(m.get("content")) for m in traj.get("messages") or [] if m.get("role") == "user"), "")
    local_graph = workdir / "graph.db"
    shutil.copyfile(graph, local_graph)
    layout = RuntimeLayout.resolve(workspace=root, state_root=workdir / "state", task_id=f"replay-{task}")
    adapter = MiniSweAdapter(task_id=f"replay-{task}", state_dir=workdir / "state", predicates=[],
                             repo_root=root, graph_db=None, layout=layout, issue_text=issue)
    revision = "replay-base"
    adapter.engine_state.bind_initial_source(revision)
    adapter.engine_state.publish_graph(graph_path=str(local_graph), graph_revision="replay-graph",
                                       source_revision=revision)
    adapter.graph_db = adapter.engine_state.graph_path
    # No producer runs in a replay: every passive read takes the stale-graph
    # path (the pessimistic case - a large repo whose amends are deferred).
    adapter._last_graph_build_ms = 10 ** 9
    session = GTSession(GTSessionConfig(task_id=f"replay-{task}"), engine=adapter)
    delivery = AttachedDelivery(session)
    outcomes = {int(r.get("action_id") or 0): str(r.get("observed_test_outcome") or "")
                for r in events if r.get("event") == "execution_evidence"}
    slow: list[tuple[int, str, float]] = []
    blocks: dict[str, int] = {}
    for index, action in enumerate(_actions(agent_dir), start=1):
        facts: dict[str, Any] = {"returncode": action["returncode"], "output": action["output"],
                                 "test_outcome": outcomes.get(index, ""), "changes": {}, "syntax": ()}
        if index in tx:
            pre_edit_graph = str(getattr(adapter.engine_state, "graph_path", "") or "")
            before_snapshot = capture_workspace(str(root))
            changes: dict[str, tuple[str | None, str]] = {}
            for change in tx[index]["changes"]:
                target = root / str(change["path"])
                after = _content(change.get("after_content_hex"))
                before = _content(change.get("before_content_hex"))
                if after is None:
                    if target.exists():
                        target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(after)
                changes[str(change["path"])] = (
                    before.decode("utf-8", "replace") if before is not None else None,
                    after.decode("utf-8", "replace") if after is not None else "")
            transaction = diff_workspace(before_snapshot, capture_workspace(str(root)),
                                         action_id=index, command=action["command"])
            if transaction.changes:
                adapter.record_edit_transaction(transaction)
            facts.update(changes=changes, pre_edit_graph=pre_edit_graph)
        started = time.perf_counter()
        out = delivery.observe_turn([action["command"]], [{"output": action["output"]}], [facts])
        elapsed = time.perf_counter() - started
        text = str(out[0].get("output") or "")
        for head in ("[GT] task plan", "[GT] graph context", "[GT] after your edit", "[GT] about this failure"):
            if head in text:
                blocks[head[5:]] = blocks.get(head[5:], 0) + 1
        if elapsed > 2.0:
            slow.append((index, action["command"][:60], round(elapsed, 1)))
    metrics = delivery.metrics()
    features: dict[str, int] = {}
    for key in ("augment_features", "action_augment_features"):
        for feature, count in (metrics.get(key) or {}).items():
            features[feature] = features.get(feature, 0) + int(count)
    for feature in metrics.get("gt_plan_features") or ():
        features[feature] = features.get(feature, 0) + 1
    return {
        "task": task, "workspace_hashes": hashes, "actions": len(_actions(agent_dir)),
        "blocks": blocks, "features": dict(sorted(features.items(), key=lambda kv: int(kv[0][1:]))),
        "feature_count": len(features),
        "searches": f"{metrics.get('augment_hits')}/{metrics.get('gt_search_commands')}",
        "edits": f"{metrics.get('edit_augment_hits')}/{metrics.get('edit_augment_calls')}",
        "failures": f"{metrics.get('failure_augment_hits')}/{metrics.get('failure_augment_calls')}",
        "gt_seconds": round(metrics.get("augment_time_s", 0) + metrics.get("action_augment_time_s", 0), 1),
        "slow_actions": slow[:8],
        "errors": metrics.get("augment_errors", 0) + metrics.get("action_augment_errors", 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--task", default="", help="substring filter on the task directory")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    results = []
    for root in args.root:
        for traj in sorted(root.rglob("agent/miniswe_trajectory.json")):
            agent_dir = traj.parent
            if "gt-state" in traj.parts or args.task not in str(agent_dir):
                continue
            with tempfile.TemporaryDirectory(prefix="gt-replay-", ignore_cleanup_errors=True) as tmp:
                try:
                    result = replay(agent_dir, workdir=Path(tmp))
                except Exception as exc:  # noqa: BLE001 - one task's failure is reported, not fatal
                    result = {"task": agent_dir.parent.name.split("__")[0],
                              "replay_error": f"{type(exc).__name__}: {exc}"[:300]}
            print(json.dumps(result, default=str), flush=True)
            results.append(result)
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
