"""Every one of the 21 GT features is reachable through attached delivery.

Runs each surface named in ``FEATURE_SURFACES`` against a real producer graph
and pins the attached-mode freshness contract: edits are not amended per
action, but the next tool call answers from the amended graph.
"""
from __future__ import annotations

import pytest

from gt_engine.attached_delivery import ATTACHED, DELIVERY_MODE_ENV, FEATURE_SURFACES
from gt_engine.grep_augment import GrepAugmenter
from gt_engine.tool_server import EXIT_ANSWER, EXIT_NO_ANSWER, TOOLS, ToolDispatcher
from tests.canonical.test_runtime_intelligence import _transact_edit

# Arguments that address real symbols/files/routes in the polyglot fixture.
FIXTURE_CALLS: dict[str, list[str]] = {
    "gt-query": ["format the total price with tax"],
    "gt-context": ["execute"],
    "gt-callers": ["execute", "2"],
    "gt-impact": ["apply_tax"],
    "gt-refs": ["execute"],
    "gt-def": ["sanitize"],
    "gt-flows": [],
    "gt-tests": ["pyapp/helpers.py"],
    "gt-routes": ["/api/items"],
    "gt-api": ["/api/items"],
    "gt-slice": ["list_items", "83"],
    "gt-taint": ["list_items", "execute"],
    "gt-shape": ["Friendly"],
    "gt-calls": ["execute"],
    "gt-module": ["pyapp/server.py"],
    "gt-cochange": ["pyapp/server.py"],
    "gt-rename": ["sanitize", "clean_input"],
    "gt-tools": [],
    "gt-check": ["pyapp/server.py"],
    "gt-changes": ["pyapp/server.py"],
    "gt-verify": [],
    "gt-failures": [],
    "gt-help": [],
}

# Surfaces whose fixture has no data to report: a named no-answer is the
# correct behaviour (no test was run; no git history; no recurring failure).
NAMED_NO_ANSWER_OK = {"gt-tests", "gt-cochange", "gt-verify", "gt-failures",
                      "gt-module", "gt-tools"}


def test_every_tool_has_a_fixture_call():
    assert set(FIXTURE_CALLS) == set(TOOLS)


@pytest.mark.parametrize("tool", sorted(FIXTURE_CALLS))
def test_tool_answers_or_names_why_not(polyglot_session, tool):
    session, _adapter = polyglot_session
    text, code = ToolDispatcher(session).dispatch(tool, FIXTURE_CALLS[tool])
    assert "internal_error" not in text and "Traceback" not in text, text
    if tool in NAMED_NO_ANSWER_OK:
        assert code in (EXIT_ANSWER, EXIT_NO_ANSWER), text
        if code == EXIT_NO_ANSWER:
            assert "no answer (" in text
    else:
        assert code == EXIT_ANSWER, text
    assert len(text.encode("utf-8")) <= ToolDispatcher(session).max_bytes


@pytest.mark.parametrize("feature", sorted(FEATURE_SURFACES))
def test_feature_reaches_the_agent(polyglot_session, feature):
    session, _adapter = polyglot_session
    surfaces = FEATURE_SURFACES[feature]
    dispatcher = ToolDispatcher(session)
    answered = []
    for surface in surfaces:
        if surface == "substrate":
            # Parsing, call resolution and freshness have no surface of their
            # own; a graph-backed answer is only possible when they worked.
            _text, code = dispatcher.dispatch("gt-callers", ["execute"])
            answered.append(code == EXIT_ANSWER)
        elif surface == "augment":
            answered.append(bool(GrepAugmenter(session).augment('grep -rn "def execute" .')))
        else:
            _text, code = dispatcher.dispatch(surface, FIXTURE_CALLS[surface])
            answered.append(code == EXIT_ANSWER)
    assert any(answered), f"{feature}: no surface answered ({surfaces})"


def test_attached_edits_defer_the_amend_until_a_tool_reads_the_graph(
    runtime_workspace, monkeypatch
):
    monkeypatch.setenv(DELIVERY_MODE_ENV, ATTACHED)
    ws = runtime_workspace("attached-fresh")
    txn = _transact_edit(ws)
    # Pay per intent: no transaction-boundary amend in attached mode.
    assert ws.journal_event("graph_sync_amend") is None
    assert ws.adapter.engine_state.graph_current is False

    text, code = ToolDispatcher(ws.session).dispatch("gt-callers", ["sanitize"])
    assert code == EXIT_ANSWER, text
    assert ws.adapter.engine_state.graph_current is True
    assert ws.adapter.engine_state.graph_source_revision == txn.post_revision
    assert "render_item" in text
    assert "list_items" not in text

    changed, code = ToolDispatcher(ws.session).dispatch("gt-changes", [])
    assert code in (EXIT_ANSWER, EXIT_NO_ANSWER), changed
    assert "internal_error" not in changed
