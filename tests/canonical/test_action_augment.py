"""Edit and test-failure augmentation against the real producer graph."""
from __future__ import annotations

from pathlib import Path

from gt_engine.action_augment import ActionAugmenter, failure_frames, is_test_command
from gt_engine.grep_augment import GrepAugmenter
# Imported by the running tool server before any edit; importing it here keeps
# its cold import (litellm, ~20 s) out of the edit block's taint budget.
import gt_engine.tool_server  # noqa: F401,E402

SERVER = "pyapp/server.py"


def _server_text(adapter) -> str:
    return (Path(adapter.repo_root) / SERVER).read_text(encoding="utf-8")


def test_edit_block_names_changed_function_callers_tests_and_sink(polyglot_session):
    session, adapter = polyglot_session
    before = _server_text(adapter)
    after = before.replace("    return execute(command)", "    return execute(command.strip())")
    assert after != before
    augmenter = ActionAugmenter(session)
    block = augmenter.after_edit({SERVER: (before, after)})
    assert block.startswith("[GT] after your edit (from the graph before it):"), block
    assert "changed: run_query (pyapp/server.py:60)" in block
    assert "run_query is called by: list_items" in block
    assert "run_query reaches sensitive sink(s): execute" in block
    features = augmenter.metrics.as_dict()["action_augment_features"]
    assert {"F13", "F19"} <= set(features)
    assert len(block.encode("utf-8")) <= augmenter.max_bytes


def test_edit_block_reports_tests_reaching_the_file_and_parse_errors(polyglot_session):
    session, adapter = polyglot_session
    before = _server_text(adapter)
    after = before.replace('if raw and raw.startswith("-"):', 'if raw and raw.startswith("--"):')
    syntax = [{"path": SERVER, "valid": False, "line": 55, "error": "SyntaxError"}]
    block = ActionAugmenter(session).after_edit({SERVER: (before, after)}, syntax)
    assert "PARSE ERROR pyapp/server.py:55 (SyntaxError)" in block
    assert "changed: sanitize" in block
    assert "tests reaching pyapp/server.py:" in block and "test_sanitize" in block


def test_edit_of_a_route_handler_names_the_route(polyglot_session):
    session, adapter = polyglot_session
    before = _server_text(adapter)
    after = before.replace('warm = run_query("ls")', 'warm = run_query("pwd")')
    block = ActionAugmenter(session).after_edit({SERVER: (before, after)})
    assert "changed: list_items" in block
    assert "list_items handles route GET /api/items" in block


def test_no_edit_or_passing_run_is_silent(polyglot_session):
    session, _adapter = polyglot_session
    augmenter = ActionAugmenter(session)
    assert augmenter.after_edit({}) == ""
    assert augmenter.after_failure("python -m pytest", "1 passed", 0) == ""
    assert augmenter.after_failure("ls -la", "Traceback", 1) == ""


def _traceback(repo_root: str) -> str:
    return (
        "FAIL: test_sanitize (pyapp.test_server.ServerHelpersTest)\n"
        "Traceback (most recent call last):\n"
        f'  File "{repo_root}/pyapp/test_server.py", line 11, in test_sanitize\n'
        '    self.assertEqual(sanitize("-abc"), "abc")\n'
        f'  File "{repo_root}/pyapp/server.py", line 56, in sanitize\n'
        "    return raw[1:]\n"
        "AssertionError: 'bc' != 'abc'\n"
    )


def test_failure_block_locates_the_test_the_function_and_its_slice(polyglot_session):
    session, adapter = polyglot_session
    augmenter = ActionAugmenter(session)
    output = _traceback(str(adapter.repo_root))
    block = augmenter.after_failure("python -m pytest pyapp", output, 1)
    assert block.startswith("[GT] about this failure:"), block
    assert "failing test: test_sanitize (pyapp/test_server.py:11)" in block
    assert "failure surfaced in: sanitize (pyapp/server.py:56)" in block
    assert "backward slice" in block and 'pyapp/server.py:55: if raw and raw.startswith("-"):' in block
    assert {"F14", "F17", "F20"} <= set(augmenter.metrics.as_dict()["action_augment_features"])


def test_same_failure_after_an_edit_is_called_out(polyglot_session):
    session, adapter = polyglot_session
    augmenter = ActionAugmenter(session)
    output = _traceback(str(adapter.repo_root))
    first = augmenter.after_failure("pytest", output, 1)
    assert "same failure" not in first
    adapter._edit_epoch += 1
    try:
        again = augmenter.after_failure("pytest", output, 1)
    finally:
        adapter._edit_epoch -= 1
    assert "same failure as before your last edit(s)" in again


def test_failure_frames_map_container_paths_and_skip_installed_packages():
    output = (
        'File "/testbed/src/app.py", line 3, in f\n'
        'File "/usr/lib/python3.11/site-packages/x.py", line 9, in g\n'
        "src/app_test.go:14: expected 1\n"
    )
    assert failure_frames(output, "/testbed") == [("src/app.py", 3)]
    assert failure_frames("src/app_test.go:14: expected 1", "/x") == [("src/app_test.go", 14)]
    assert is_test_command("cd /testbed && python -m pytest tests/ -x")
    assert is_test_command("go test ./...")
    assert not is_test_command("grep -rn test .")


def test_grep_block_carries_references_overrides_routes_and_injection(polyglot_session):
    session, _adapter = polyglot_session
    execute = GrepAugmenter(session).augment('grep -rn "def execute" .')
    assert "referenced from 1 file(s): pyapp/server.py" in execute
    assert "call sites: 1 proven" in execute
    assert "module pyapp/" in execute
    render = GrepAugmenter(session).augment('grep -rn "def render" pyapp')
    assert "overridden by: JsonRenderer.render (pyapp/server.py:35)" in render
    renderer = GrepAugmenter(session).augment('grep -rn "class Renderer" pyapp')
    assert "extended/implemented by: JsonRenderer" in renderer
    items = GrepAugmenter(session).augment('grep -rn "def list_items" pyapp')
    assert "handles route GET /api/items" in items
    store = GrepAugmenter(session).augment('grep -rn "def get_store" pyapp')
    assert "injected into: list_items" in store


ISSUE = """Greetings drop the name's first letter.

- `format_greeting` must keep the full name in its output.
- `list_items` must call `run_query` once per request.
"""


def _with_issue(adapter, text):
    previous = getattr(adapter, "issue_text", "")
    adapter.issue_text = text
    adapter.attached_plan = None
    return previous


def test_plan_ties_issue_lines_to_code_and_is_delivered_once(polyglot_session):
    from gt_engine.attached_delivery import AttachedDelivery

    session, adapter = polyglot_session
    previous = _with_issue(adapter, ISSUE)
    try:
        delivery = AttachedDelivery(session)
        first = delivery.observe_turn(["ls"], [{"output": "a.txt"}])
        text = first[0]["output"]
        assert text.startswith("a.txt\n\n[GT] task plan"), text
        assert "format_greeting (pyapp/server.py:68" in text, text
        assert "list_items (pyapp/server.py:79" in text
        assert "test_greeting" in text
        second = delivery.observe_turn(["ls"], [{"output": "a.txt"}])
        assert second[0]["output"] == "a.txt"
        metrics = delivery.metrics()
        assert metrics["gt_plan_delivered"] is True and metrics["gt_plan_bytes_delivered"] > 0
        assert metrics["gt_tool_calls"] == 0
        tool_text, code = delivery.dispatcher.dispatch("gt-plan", [])
        assert code == 0 and "R1:" in tool_text
    finally:
        _with_issue(adapter, previous)


def test_observe_turn_appends_edit_and_failure_blocks(polyglot_session):
    from gt_engine.attached_delivery import AttachedDelivery

    session, adapter = polyglot_session
    previous = _with_issue(adapter, "")
    try:
        delivery = AttachedDelivery(session)
        before = _server_text(adapter)
        after = before.replace("    return execute(command)", "    return execute(command.strip())")
        outputs = delivery.observe_turn(
            ["sed -i 's/x/y/' pyapp/server.py", "python -m pytest pyapp"],
            [{"output": ""}, {"output": "FAILED"}],
            [{"changes": {SERVER: (before, after)}, "syntax": (), "returncode": 0, "output": ""},
             {"changes": {}, "syntax": (), "returncode": 1,
              "output": _traceback(str(adapter.repo_root))}],
        )
        assert outputs[0]["output"].startswith("[GT] after your edit"), outputs[0]
        assert outputs[1]["output"].startswith("FAILED\n\n[GT] about this failure:"), outputs[1]
        metrics = delivery.metrics()
        assert metrics["edit_augment_hits"] == 1 and metrics["failure_augment_hits"] == 1
        assert metrics["gt_bytes_delivered"] >= metrics["action_augment_bytes_delivered"] > 0
    finally:
        _with_issue(adapter, previous)


def test_edit_block_never_refreshes_the_graph(polyglot_session, monkeypatch):
    import gt_engine.tool_server as tool_server

    def refuse(*_args, **_kwargs):
        raise AssertionError("an edit block must not amend the graph")

    monkeypatch.setattr(tool_server, "refresh_if_stale", refuse)
    session, adapter = polyglot_session
    before = _server_text(adapter)
    after = before.replace("    return execute(command)", "    return execute(command.strip())")
    block = ActionAugmenter(session).after_edit({SERVER: (before, after)})
    assert "changed: run_query" in block


def test_graph_indexed_at_other_content_never_names_changed_functions(polyglot_session):
    session, adapter = polyglot_session
    before = "# edited earlier by the agent\n" + _server_text(adapter)
    after = before.replace("    return execute(command)", "    return execute(command.strip())")
    block = ActionAugmenter(session).after_edit({SERVER: (before, after)})
    assert "changed:" not in block


def test_failure_block_fires_on_parsed_outcome_even_when_the_shell_exits_zero(polyglot_session):
    # `pytest ... | tail -20` exits 0; the runtime still parses the failure.
    session, adapter = polyglot_session
    augmenter = ActionAugmenter(session)
    output = _traceback(str(adapter.repo_root))
    assert augmenter.after_failure("python -m pytest pyapp | tail -20", output, 0) == ""
    block = augmenter.after_failure("python -m pytest pyapp | tail -20", output, 0, "fail")
    assert "failure surfaced in: sanitize (pyapp/server.py:56)" in block


def test_failure_in_an_edited_python_file_is_located_and_sliced_without_the_graph(polyglot_session):
    session, adapter = polyglot_session
    path = Path(adapter.repo_root) / SERVER
    original_bytes = path.read_bytes()  # restore byte-exact: write_text adds CRLF on Windows
    original = original_bytes.decode("utf-8")
    edited = original.replace('def sanitize(raw):\n', 'def sanitize(raw):\n    raw = raw or ""\n')
    assert edited != original
    path.write_bytes(edited.encode("utf-8"))
    try:
        output = _traceback(str(adapter.repo_root)).replace("server.py\", line 56", "server.py\", line 57")
        block = ActionAugmenter(session).after_failure("pytest", output, 1, "fail")
    finally:
        path.write_bytes(original_bytes)
    assert "failure surfaced in: sanitize (pyapp/server.py:57)" in block, block
    assert 'pyapp/server.py:55: raw = raw or ""' in block


def test_a_second_edit_to_a_file_maps_against_the_indexed_text(polyglot_session, monkeypatch):
    session, adapter = polyglot_session
    original = _server_text(adapter)
    first = original.replace("    return execute(command)", "    return execute(command.strip())")
    second = first.replace("    return subprocess.run(command, shell=True)",
                           "    return subprocess.run(command, shell=False)")
    augmenter = ActionAugmenter(session)
    monkeypatch.setattr(augmenter, "_preimages", lambda: {SERVER: original})
    block = augmenter.after_edit({SERVER: (first, second)})
    assert "changed: run_query" in block and "execute (pyapp/server.py:64)" in block, block


def test_sink_reach_is_answered_from_the_call_graph(polyglot_session):
    import sqlite3

    from gt_engine.action_augment import _reached_sinks
    from gt_engine.capabilities._query import graph_conn

    session, _adapter = polyglot_session
    conn = graph_conn(session)
    try:
        node = conn.execute("SELECT id FROM nodes WHERE name = 'run_query'").fetchone()[0]
        assert "execute" in _reached_sinks(conn, node)
    finally:
        conn.close()
    assert isinstance(conn, sqlite3.Connection)


def test_plan_carries_related_code_and_is_withheld_when_nothing_anchors(polyglot_session):
    from gt_engine.attached_delivery import AttachedDelivery

    session, adapter = polyglot_session
    previous = _with_issue(adapter, ISSUE)
    try:
        delivery = AttachedDelivery(session)
        text = delivery.observe_turn(["ls"], [{"output": ""}])[0]["output"]
        assert "code most related to the issue (hybrid lexical + semantic rank)" in text, text
        assert "F11" in delivery.metrics()["gt_plan_features"]
    finally:
        _with_issue(adapter, previous)
    from gt_engine.attached_plan import AttachedPlan

    empty = AttachedPlan(requirements=({"name": "R1: x  -> no code anchor"},), tests=(),
                         rows_total=1, anchored_rows=0, graph_revision="")
    assert empty.worth_showing is False and empty.features == ()
    related_only = AttachedPlan(requirements=(), tests=(), rows_total=1, anchored_rows=0,
                                graph_revision="", related=({"file_path": "a.py"},))
    assert related_only.worth_showing is True and related_only.features == ("F11",)


def test_grep_block_says_how_callers_were_resolved(polyglot_session):
    block = GrepAugmenter(polyglot_session[0]).augment('grep -rn "def execute" .')
    assert "callers resolved by:" in block, block


def test_edit_outside_a_function_maps_to_the_class_and_names_new_definitions(polyglot_session):
    session, adapter = polyglot_session
    before = _server_text(adapter)
    after = before.replace('''    def content_type(self):
        return "text/plain"
''', '''    def content_type(self):
        return "text/plain"

    def charset(self):
        return "utf-8"
''', 1)
    assert after != before
    block = ActionAugmenter(session).after_edit({SERVER: (before, after)})
    assert "added: charset (pyapp/server.py) - new, so nothing calls it yet" in block, block


def test_editing_a_test_lists_the_code_it_exercises(polyglot_session):
    session, adapter = polyglot_session
    path = "pyapp/test_server.py"
    before = (Path(adapter.repo_root) / path).read_text(encoding="utf-8")
    after = before.replace('self.assertEqual(sanitize("ok"), "ok")', 'self.assertEqual(sanitize("ok!"), "ok!")')
    assert after != before
    block = ActionAugmenter(session).after_edit({path: (before, after)})
    assert "test ServerHelpersTest.test_sanitize exercises: sanitize" in block or \
        "test test_sanitize exercises: sanitize" in block, block


def test_a_name_that_is_not_a_definition_shows_where_it_is_used(polyglot_session):
    block = GrepAugmenter(polyglot_session[0]).augment('grep -rn "rate" pyapp')
    assert "rate (not a definition) is used in: apply_tax (pyapp/helpers.py:9, data flow)" in block, block
    assert "next: `gt-impact apply_tax`" in block
