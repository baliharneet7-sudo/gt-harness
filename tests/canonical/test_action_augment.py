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


def test_go_test_output_with_bare_file_names_is_located_and_sliced(polyglot_session):
    # `go test` prints `main_test.go:15:` without the package directory; live
    # DeepSWE abs tasks got failure blocks with no location because of it.
    session, _adapter = polyglot_session
    output = ("--- FAIL: TestGreet (0.00s)\n"
              "    main_test.go:16: Greet(ada) = \"hi  ada\", want \"hi ada\"\n"
              "FAIL\nFAIL\texample.com/gosvc\t0.004s\n")
    block = ActionAugmenter(session).after_failure("go test ./...", output, 1, "fail")
    assert "failing test: TestGreet (gosvc/main_test.go:16)" in block, block


def test_plan_wiring_and_feature_trace(polyglot_session):
    import json as _json

    from gt_engine.attached_delivery import AttachedDelivery

    session, adapter = polyglot_session
    previous = _with_issue(adapter, ISSUE)
    try:
        delivery = AttachedDelivery(session)
        text = delivery.observe_turn(["ls"], [{"output": ""}])[0]["output"]
        assert "wiring of the anchored code" in text, text
        assert "list_items handles route GET /api/items" in text
        assert "run_query reaches sink-like call(s): execute" in text
        delivery.augmenter.augment('grep -rn "def execute" .')
        metrics = delivery.metrics()
        for feature in ("F2", "F4", "F8", "F11", "F18", "F19"):
            assert metrics["features_reached"].get(feature), (feature, metrics["features_reached"])
        inventory = metrics["feature_inventory"]
        assert inventory["F18"] > 0 and inventory["F2"] > 0 and inventory["F1"] == 1
        rows = [_json.loads(line) for line in Path(adapter.store.path).read_text(encoding="utf-8").splitlines()]
        assert any(r.get("event") == "gt_feature_inventory" for r in rows)
        hits = [r for r in rows if r.get("event") == "gt_augment" and r.get("outcome") == "hit"]
        assert hits and "F2" in hits[-1]["features"]
        built = [r for r in rows if r.get("event") == "attached_plan_built"]
        assert built and "F18" in built[-1]["features"]
    finally:
        _with_issue(adapter, previous)


def test_budget_says_each_thing_once(polyglot_session):
    from gt_engine.attached_delivery import AttachedDelivery

    session, adapter = polyglot_session
    previous = _with_issue(adapter, "")
    try:
        delivery = AttachedDelivery(session)
        first = delivery.augmenter.augment('grep -rn "def execute" .')
        again = delivery.augmenter.augment('grep -rn "execute(" pyapp')
        assert "called by: run_query" in first
        assert again == ""  # the same block again says nothing
        before = _server_text(adapter)
        after = before.replace("    return execute(command)", "    return execute(command.strip())")
        one = delivery.action_augmenter.after_edit({SERVER: (before, after)})
        two = delivery.action_augmenter.after_edit({SERVER: (before, after)})
        assert "run_query is called by: list_items" in one
        assert "callers unchanged since shown earlier" in two and "tests reaching" not in two
        hints = sum("next: `gt-impact" in delivery.augmenter.augment(f'grep -rn "def {name}" .')
                    for name in ("sanitize", "format_total", "apply_tax", "round_price", "audit"))
        assert hints <= 2  # three hints per task in total; one was already spent
        assert delivery.metrics()["gt_repeats_suppressed"] > 0
    finally:
        _with_issue(adapter, previous)


def _callers(count: int) -> list[dict]:
    return [{"name": f"c{i}", "file_path": "pkg/mod.py", "line": i} for i in range(count)]


def test_callers_cut_by_the_display_cap_are_never_called_shown():
    augmenter = ActionAugmenter(session=None)
    augmenter._draft = augmenter.budget.draft()
    first = augmenter._caller_lines(_callers(6), "f", "pkg/f.py")
    augmenter._draft.commit("\n".join(first))
    assert "(+2 more)" in first[0]
    augmenter._draft = augmenter.budget.draft()
    second = augmenter._caller_lines(_callers(6), "f", "pkg/f.py")
    augmenter._draft.commit("\n".join(second))
    # the two callers the cap hid are shown now, and the four shown are counted
    assert "c4 (pkg/mod.py:4)" in second[0] and "c5 (pkg/mod.py:5)" in second[0]
    assert "(4 shown earlier)" in second[0] and "c0 " not in second[0]
    augmenter._draft = augmenter.budget.draft()
    third = augmenter._caller_lines(_callers(6), "f", "pkg/f.py")
    assert third == ["    f: callers unchanged since shown earlier"]


def test_a_new_caller_after_an_edit_is_shown():
    augmenter = ActionAugmenter(session=None)
    augmenter._draft = augmenter.budget.draft()
    augmenter._draft.commit("\n".join(augmenter._caller_lines(_callers(2), "f", "pkg/f.py")))
    augmenter._draft = augmenter.budget.draft()
    grown = augmenter._caller_lines(_callers(3), "f", "pkg/f.py")
    assert "c2 (pkg/mod.py:2)" in grown[0] and "(2 shown earlier)" in grown[0]


def test_a_fact_lost_to_truncation_or_silence_is_not_recorded():
    from gt_engine.attached_budget import DeliveryBudget
    from gt_engine.tool_render import cap_text

    budget = DeliveryBudget()
    draft = budget.draft()
    draft.stage("a", "line a")
    draft.stage("b", "line b " + "x" * 400)
    draft.commit(cap_text("header\nline a\nline b " + "x" * 400, 120))
    assert budget.was_shown("a") and not budget.was_shown("b")
    draft = budget.draft()
    draft.stage("c", "line c")
    draft.commit("")  # a silent block delivers nothing
    assert not budget.was_shown("c")


def test_symbol_block_is_keyed_by_content_not_location():
    augmenter = GrepAugmenter(session=None)
    definition = {"qualified_name": "f", "kind": "function", "file_path": "a.py", "start_line": 3}
    before = {"definition": definition, "callers": [{"name": "g", "file_path": "b.py", "line": 1}],
              "caller_count": 1}
    after = {**before, "callers": [*before["callers"], {"name": "h", "file_path": "c.py", "line": 2}],
             "caller_count": 2}
    for answer, expect_block in ((before, True), (before, False), (after, True)):
        draft = augmenter.budget.draft()
        block, _features = augmenter._budgeted(draft, "f", answer, ())
        assert bool(block) is expect_block
        draft.commit(block or "")


def test_a_repeated_failure_points_back_to_the_earlier_location():
    augmenter = ActionAugmenter(session=None)
    lines = augmenter._repeat_lines("E   AssertionError: boom", [("pkg/a.py", 3)], False, True)
    augmenter._failures_seen = {k: -1 for k in augmenter._failures_seen}
    lines = augmenter._repeat_lines("E   AssertionError: boom", [("pkg/a.py", 3)], False, True)
    assert lines and "location shown earlier" in lines[0]


def test_a_removed_caller_is_never_reported_as_unchanged():
    augmenter = ActionAugmenter(session=None)
    augmenter._draft = augmenter.budget.draft()
    augmenter._draft.commit("\n".join(augmenter._caller_lines(_callers(3), "f", "pkg/f.py")))
    augmenter._draft = augmenter.budget.draft()
    shrunk = augmenter._caller_lines(_callers(2), "f", "pkg/f.py")
    augmenter._draft.commit("\n".join(shrunk))
    assert "unchanged" not in shrunk[0] and "called by (current): c0" in shrunk[0]
    augmenter._draft = augmenter.budget.draft()
    assert augmenter._caller_lines(_callers(2), "f", "pkg/f.py") == [
        "    f: callers unchanged since shown earlier"]


def test_a_different_message_at_the_same_line_is_a_different_failure():
    from gt_engine.action_augment import _failure_signature

    frames = [("pkg/a.py", 3)]
    one = _failure_signature("E   KeyError: 'foo'", frames, detailed=True)
    two = _failure_signature("E   KeyError: 'bar'", frames, detailed=True)
    assert one and two and one != two
    assert _failure_signature("E   KeyError: 'foo'", frames) == _failure_signature("E   KeyError: 'bar'", frames)


def test_compaction_keeps_parse_errors_and_sinks():
    from gt_engine.action_augment import _ALWAYS_SHOWN
    from gt_engine.attached_budget import compact_lines

    lines = ["  changed: f", "    f is called by: g", "  tests reaching a.py: t",
             "    f reaches sink-like call(s): os.system", "  PARSE ERROR a.py:3 (syntax)"]
    kept = compact_lines(lines, always=_ALWAYS_SHOWN)
    assert kept[:2] == lines[:2]
    assert lines[3] in kept and lines[4] in kept and lines[2] not in kept
    assert kept[-1] == "  (+1 more line(s); GT detail budget reached)"

