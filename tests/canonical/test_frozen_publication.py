"""A graph built from a frozen snapshot survives the agent editing meanwhile."""
from __future__ import annotations

import os
import shutil

from tests.canonical.conftest import FIXTURE_DIR, FIXTURE_REVISION


def test_edit_during_a_frozen_build_does_not_discard_the_graph(gt_index, tmp_path, monkeypatch):
    # DeepSWE aiomonitor (run 36336203906): three startup graphs in a row were
    # built from a frozen, hash-verified snapshot and then discarded as
    # "producer input superseded before publication" because the agent had
    # edited the live tree during the build; the task ran with no graph.
    from gt_engine import indexer
    from gt_engine.engine_state import RuntimeLayout

    binary, _info = gt_index
    monkeypatch.setenv("GT_INDEX_BINARY", binary)
    if os.name == "nt":
        monkeypatch.setattr(indexer, "_has_verified_index_process_tree_guard", lambda: True)
        monkeypatch.setattr(indexer, "_kill_index_process_tree",
                            lambda process: process.kill() if process.poll() is None else True)
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE_DIR, root)
    layout = RuntimeLayout.resolve(workspace=root, state_root=tmp_path / "state", task_id="frozen")
    assert layout.excluded_roots, "benchmark layouts always build from a frozen snapshot"

    original = indexer._build_index_with_attempts

    def build_while_the_agent_edits(*args, **kwargs):
        (root / "pyapp" / "helpers.py").write_text(
            (root / "pyapp" / "helpers.py").read_text(encoding="utf-8") + "\n# agent edit\n",
            encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(indexer, "_build_index_with_attempts", build_while_the_agent_edits)
    diagnostics: list[str] = []
    graph = indexer.ensure_index(str(root), layout=layout, source_revision=FIXTURE_REVISION,
                                 diagnostics=diagnostics)
    assert graph is not None, diagnostics
    assert not any("superseded" in item for item in diagnostics), diagnostics
