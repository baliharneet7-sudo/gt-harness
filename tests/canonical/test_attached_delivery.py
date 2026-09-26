"""Attached delivery against a real producer graph (the polyglot fixture)."""
from __future__ import annotations

import os
import subprocess
import sys

from gt_engine.grep_augment import GrepAugmenter
from gt_engine.tool_server import (
    EXIT_ANSWER,
    EXIT_NO_ANSWER,
    ToolDispatcher,
    ToolServer,
    install_wrappers,
)


def test_context_tool_answers_from_the_graph(polyglot_session):
    session, _adapter = polyglot_session
    text, code = ToolDispatcher(session).dispatch("gt-context", ["execute"])
    assert code == EXIT_ANSWER, text
    assert "pyapp/server.py" in text
    assert "run_query" in text


def test_callers_tool_reports_depth_bands_with_tiers(polyglot_session):
    session, _adapter = polyglot_session
    text, code = ToolDispatcher(session).dispatch("gt-callers", ["execute", "2"])
    assert code == EXIT_ANSWER, text
    assert "run_query" in text and "list_items" in text
    assert "[CERTIFIED]" in text


def test_unknown_symbol_is_a_named_no_answer(polyglot_session):
    session, _adapter = polyglot_session
    text, code = ToolDispatcher(session).dispatch("gt-def", ["no_such_symbol_zz"])
    assert code == EXIT_NO_ANSWER
    assert text.startswith("[GT] definition no_such_symbol_zz")


def test_grep_augmentation_is_anchored_to_the_agents_pattern(polyglot_session):
    session, _adapter = polyglot_session
    augmenter = GrepAugmenter(session)
    block = augmenter.augment('grep -rn "def execute" pyapp/')
    assert block.startswith("[GT] graph context for your search:")
    assert "execute" in block and "called by: run_query" in block
    assert len(block.encode("utf-8")) <= augmenter.max_bytes
    assert augmenter.augment("grep -rn no_such_symbol_zz .") == ""
    assert augmenter.augment("ls -la") == ""
    again = GrepAugmenter(session).augment('grep -rn "def execute" pyapp/')
    assert again == block
    metrics = augmenter.metrics.as_dict(augmenter.search_commands)
    assert metrics["augment_hits"] == 1 and metrics["augment_calls"] == 2


def test_wrapper_round_trip_on_the_real_graph(polyglot_session, tmp_path):
    session, _adapter = polyglot_session
    server = ToolServer(ToolDispatcher(session)).start()
    try:
        install_wrappers(tmp_path / "bin", server.url)
        env = {key: os.environ[key] for key in ("SYSTEMROOT",) if key in os.environ}
        done = subprocess.run(
            [sys.executable, str(tmp_path / "bin" / "gt-callers"), "execute"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert done.returncode == EXIT_ANSWER, done.stdout + done.stderr
        assert "run_query" in done.stdout
    finally:
        server.stop()
