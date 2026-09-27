"""Attached delivery (HAR-93) — pure unit tests, no graph or provider."""
from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from gt_engine import tool_server
from gt_engine.attached_delivery import (
    ATTACHED,
    DELIVERY_MODE_ENV,
    PUSH,
    AttachedDelivery,
    UptakeTracker,
    attached_system_section,
    delivery_mode,
    delivery_report,
    distinct_tokens,
)
from gt_engine.capabilities._query import CapabilityResult
from gt_engine.grep_augment import (
    extract_search_pattern,
    render_symbol_block,
    symbols_in_pattern,
)
from gt_engine.tool_render import cap_text, render_result
from gt_engine.tool_server import (
    EXIT_ANSWER,
    EXIT_NO_ANSWER,
    EXIT_USAGE,
    TOOLS,
    ToolDispatcher,
    ToolServer,
    install_wrappers,
    parse_ready_line,
)


class _Store:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict]] = []

    def append(self, event: str, **row) -> None:
        self.rows.append((event, row))


def _session(**engine_attrs):
    engine = SimpleNamespace(store=_Store(), graph_db="", graph_fresh=True, **engine_attrs)
    return SimpleNamespace(_engine=engine, engine=engine, disabled=False,
                           capability_active=lambda _name: True)


def _result(answer, status="partial", fresh=True, semantics="partial", omissions=()):
    return CapabilityResult(capability="x", status=status, answer=answer,
                            fresh=fresh, semantics=semantics, omissions=omissions)


# --- delivery mode -----------------------------------------------------------

def test_delivery_mode_defaults_to_push(monkeypatch):
    # setenv first so teardown restores the var the code under test rewrites.
    monkeypatch.setenv(DELIVERY_MODE_ENV, PUSH)
    monkeypatch.delenv(DELIVERY_MODE_ENV)
    assert delivery_mode() == PUSH
    assert delivery_mode("ATTACHED") == ATTACHED


def test_delivery_mode_rejects_unknown_value():
    with pytest.raises(ValueError, match="gt_delivery_mode_invalid"):
        delivery_mode("hybrid")


# --- search pattern extraction ----------------------------------------------

@pytest.mark.parametrize(("command", "expected"), [
    ('grep -rn "def execute" .', "def execute"),
    ("rg -n parse_config src/", "parse_config"),
    ("cd repo && grep -A 3 -n BoundField django/forms", "BoundField"),
    ("grep -e run_query -r .", "run_query"),
    ("git grep -n 'class Friendly'", "class Friendly"),
    ("rg --glob '*.py' -- load_items", "load_items"),
    ("cat file.py | grep handle_request", "handle_request"),
    ("/usr/bin/grep -r apply_tax .", "apply_tax"),
])
def test_extract_search_pattern(command, expected):
    assert extract_search_pattern(command) == expected


@pytest.mark.parametrize("command", [
    "ls -la", "python -m pytest -q", "sed -n 1,20p a.py", "grep -r ab .", "echo 'grep foo'",
])
def test_extract_search_pattern_ignores_non_searches(command):
    assert extract_search_pattern(command) is None


def test_symbols_in_pattern_drops_keywords_and_keeps_most_specific():
    assert symbols_in_pattern("def execute") == ("execute",)
    assert symbols_in_pattern(r"class\s+BoundField") == ("BoundField",)
    assert symbols_in_pattern("self.run_query(") == ("run_query",)
    assert symbols_in_pattern("return x") == ()
    assert len(symbols_in_pattern("alpha_one beta_two gamma_three")) == 2


def test_render_symbol_block_shows_tier_only_when_not_certified():
    answer = {
        "definition": {"qualified_name": "execute", "kind": "Function",
                       "file_path": "pyapp/server.py", "start_line": 64},
        "callers": [
            {"name": "run_query", "file_path": "pyapp/server.py", "call_line": 61,
             "trust_tier": "CERTIFIED"},
            {"name": "maybe", "file_path": "x.py", "call_line": 3, "trust_tier": "INFERRED"},
        ],
        "caller_count": 7,
        "callees": [],
        "flows": [{"label": "list_items -> execute"}],
        "additional_definitions": 1,
    }
    block = render_symbol_block("execute", answer)
    assert "execute (Function) pyapp/server.py:64" in block
    assert "run_query (pyapp/server.py:61)" in block
    assert "maybe (x.py:3) [INFERRED]" in block
    assert "(+5 more)" in block
    assert "in flow: list_items -> execute" in block
    assert "ambiguous: 1 other definition" in block


def test_render_symbol_block_is_silent_without_definition_or_neighbors():
    assert render_symbol_block("x", {"definition": None}) is None
    lone = {"definition": {"name": "x", "file_path": "a.py", "start_line": 1},
            "callers": [], "callees": [], "flows": []}
    assert render_symbol_block("x", lone) is None


# --- rendering ---------------------------------------------------------------

def test_render_result_is_compact_and_hash_free():
    answer = {
        "callers_by_depth": {"1": [{"name": "run_query", "file_path": "a.py",
                                    "call_line": 61, "trust_tier": "CERTIFIED"}]},
        "graph_revision": "deadbeef" * 8,
        "symbol": "execute",
    }
    text, has_answer = render_result("callers execute", _result(answer), next_hint="gt-impact x")
    assert has_answer
    assert "deadbeef" not in text
    assert "a.py:61  run_query  [CERTIFIED]" in text
    assert "partial:" in text and "next: gt-impact x" in text


def test_render_result_no_answer_names_the_reason():
    text, has_answer = render_result(
        "context nope", _result(None, status="unavailable", omissions=("graph_unavailable",)))
    assert not has_answer
    assert text == "[GT] context nope: no answer (graph_unavailable)"


def test_render_result_counts_and_echoes_alone_are_not_an_answer():
    text, has_answer = render_result(
        "definition zz", _result({"symbol": "zz", "definition_count": 0, "definitions": []}))
    assert not has_answer
    assert text == "[GT] definition zz: no answer (no matching facts in the graph)"


def test_render_result_flags_stale_graph():
    text, _ = render_result("x", _result({"symbol": "s", "rows": [{"name": "a"}]}, fresh=False))
    assert "graph not current" in text


def test_cap_text_states_truncation():
    text = cap_text("line\n" * 5000, 200)
    assert len(text.encode("utf-8")) <= 200
    assert text.endswith("[output truncated at 200 bytes]")


# --- dispatcher --------------------------------------------------------------

def test_dispatcher_usage_unknown_and_fault_paths(monkeypatch):
    dispatcher = ToolDispatcher(_session())
    text, code = dispatcher.dispatch("gt-callers", [])
    assert code == EXIT_USAGE and text.startswith("usage:")
    _, code = dispatcher.dispatch("gt-nope", [])
    assert code == EXIT_USAGE

    def boom(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(tool_server.structure, "symbol_context", boom)
    text, code = dispatcher.dispatch("gt-context", ["Foo"])
    assert code == EXIT_NO_ANSWER
    assert "Traceback" not in text and "internal_error:RuntimeError" in text
    metrics = dispatcher.metrics.as_dict()
    assert metrics["gt_tool_calls"] == 3
    assert metrics["gt_tool_usage_errors"] == 2 and metrics["gt_tool_faults"] == 1
    assert metrics["gt_tool_calls_by_name"]["gt-nope"] == 1


def test_dispatcher_answers_and_journals(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        tool_server.structure, "callers",
        lambda _s, symbol, depth=3, **_h: _result(
            {"callers_by_depth": {"1": [{"name": "caller_a", "file_path": "m.py", "line": 4}]}}),
    )
    dispatcher = ToolDispatcher(session)
    text, code = dispatcher.dispatch("gt-callers", ["execute", "2"])
    assert code == EXIT_ANSWER and "m.py:4  caller_a" in text
    assert dispatcher.metrics.calls_by_name == {"gt-callers": 1}
    events = [event for event, _ in session._engine.store.rows]
    assert events == ["gt_tool_call"]


def test_dispatcher_refreshes_a_stale_graph_first(monkeypatch):
    refreshed: list[str] = []
    session = _session()
    session._engine.graph_db = "graph.db"
    session._engine.graph_fresh = False
    session._engine.refresh_graph = lambda phase: refreshed.append(phase)
    monkeypatch.setattr(tool_server.localization, "definition",
                        lambda *_a, **_k: _result({"definitions": []}))
    ToolDispatcher(session).dispatch("gt-def", ["x"])
    assert refreshed == ["graph_query"]


# --- server + wrappers -------------------------------------------------------

@pytest.mark.parametrize(("line", "expected"), [
    ("GT_TOOL_SERVER_READY:127.0.0.1:4848", ("127.0.0.1", 4848)),
    ("GT_TOOL_SERVER_READY:[::1]:4848", ("[::1]", 4848)),
    ("GT_TOOL_SERVER_READY:bad", None),
    ("other", None),
])
def test_parse_ready_line(line, expected):
    assert parse_ready_line(line) == expected


def _empty_env() -> dict[str, str]:
    keep = ("SYSTEMROOT", "SystemRoot") if os.name == "nt" else ()
    return {key: os.environ[key] for key in keep if key in os.environ}


def test_wrappers_work_with_an_empty_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tool_server.structure, "symbol_context",
        lambda _s, symbol, **_h: _result(
            {"definition": {"name": symbol, "file_path": "a.py", "start_line": 3}}),
    )
    server = ToolServer(ToolDispatcher(_session())).start()
    try:
        paths = install_wrappers(tmp_path / "bin", server.url)
        assert {path.name for path in paths} == set(TOOLS)
        wrapper = tmp_path / "bin" / "gt-context"
        done = subprocess.run([sys.executable, str(wrapper), "Foo"], env=_empty_env(),
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == EXIT_ANSWER, done.stdout + done.stderr
        assert "definition: a.py:3  Foo" in done.stdout
        usage = subprocess.run([sys.executable, str(tmp_path / "bin" / "gt-slice")],
                               env=_empty_env(), capture_output=True, text=True, timeout=60)
        assert usage.returncode == EXIT_USAGE
    finally:
        server.stop()


def test_wrapper_reports_a_dead_server_without_traceback(tmp_path):
    install_wrappers(tmp_path / "bin", "http://127.0.0.1:9")
    done = subprocess.run([sys.executable, str(tmp_path / "bin" / "gt-query"), "x"],
                          env=_empty_env(), capture_output=True, text=True, timeout=60)
    assert done.returncode == EXIT_NO_ANSWER
    assert "tool server unavailable" in done.stdout and "Traceback" not in done.stderr


# --- uptake + turn observation -------------------------------------------------

def test_distinct_tokens_excludes_what_the_trigger_already_named():
    tokens = distinct_tokens("execute (Function) pyapp/server.py:64\n  called by: run_query (pyapp/api.py:3)",
                             "grep -rn execute .")
    assert "pyapp/server.py" in tokens and "run_query" in tokens and "execute" not in tokens


def test_uptake_counts_reuse_within_the_window_once():
    tracker = UptakeTracker()
    tracker.register("called by: run_query (pyapp/api.py:3)", "grep execute")
    tracker.observe("ls")
    tracker.observe("sed -n 1,40p pyapp/api.py")
    tracker.observe("cat pyapp/api.py")
    assert tracker.as_dict()["gt_context_referenced"] == 1
    tracker.register("called by: other_fn (z/zz.py:1)", "grep y")
    for _ in range(4):
        tracker.observe("ls")
    assert tracker.as_dict()["gt_context_referenced"] == 1
    assert tracker.as_dict()["gt_context_deliveries"] == 2


def test_observe_turn_appends_block_to_the_search_observation_only():
    delivery = AttachedDelivery.__new__(AttachedDelivery)
    delivery.dispatcher = SimpleNamespace(metrics=SimpleNamespace(delivered_texts=[]))
    delivery.uptake = UptakeTracker()
    delivery._tool_texts_seen = 0
    delivery.augmenter = SimpleNamespace(
        augment=lambda cmd: "[GT] graph context" if cmd.startswith("grep") else "")
    outputs = [{"output": "a.py:1:foo", "returncode": 0}, {"output": "x", "returncode": 0},
               {"output": "typed", "returncode": 0}]
    new = delivery.observe_turn(["grep foo .", "ls", None], outputs)
    assert new[0]["output"] == "a.py:1:foo\n\n[GT] graph context"
    assert new[1] == outputs[1] and new[2] == outputs[2]
    assert outputs[0]["output"] == "a.py:1:foo"


def test_delivery_report_modes():
    assert delivery_report(None) == {"gt_delivery_mode": "off"}
    adapter = SimpleNamespace(_model_visible_delivery_bytes=120, _model_visible_delivery_count=3)
    assert delivery_report(adapter) == {
        "gt_delivery_mode": "push", "gt_bytes_delivered": 120, "gt_deliveries": 3}


def test_system_section_lists_only_core_tools_and_points_to_help():
    section = attached_system_section()
    for name, spec in TOOLS.items():
        assert (f"`{spec.usage}`" in section) == spec.core, name
    assert "`gt-help`" in section
    assert "{{" not in section and "{%" not in section
    assert len(section.encode("utf-8")) < 2_000


def test_every_feature_has_a_registered_attached_surface():
    from gt_engine.attached_delivery import FEATURE_SURFACES

    assert len(FEATURE_SURFACES) == 21
    for feature, surfaces in FEATURE_SURFACES.items():
        for surface in surfaces:
            assert surface in ("substrate", "augment") or surface in TOOLS, (feature, surface)


# --- treatment flag + runtime bypasses ---------------------------------------

def _flag_args(**overrides):
    base = dict(gt_off=False, gt_mode="advisory", integration_mode="", step_limit=0,
                time_budget_seconds=1, execution_budget_sec=0, task_id="", product_source_sha="",
                treatment_runtime_contract_path="", gt_delivery_mode="")
    base.update(overrides)
    return SimpleNamespace(**base)


def test_treatment_flag_attached_forces_shadow_session(monkeypatch):
    from gt_engine.treatment_flags import resolve_treatment_flags

    # setenv first so teardown restores the var the code under test rewrites.
    monkeypatch.setenv(DELIVERY_MODE_ENV, PUSH)
    monkeypatch.delenv(DELIVERY_MODE_ENV)
    args = _flag_args(gt_delivery_mode="attached")
    resolution = resolve_treatment_flags(args)
    assert args.gt_mode == "shadow"
    assert os.environ[DELIVERY_MODE_ENV] == ATTACHED
    assert resolution["gt_delivery_mode"]["disposition"] == "wired:attached_shadow_session"


def test_treatment_flag_push_default_and_refusals(monkeypatch):
    from gt_engine.treatment_flags import TreatmentFlagRefusal, resolve_treatment_flags

    # setenv first so teardown restores the var the code under test rewrites.
    monkeypatch.setenv(DELIVERY_MODE_ENV, PUSH)
    monkeypatch.delenv(DELIVERY_MODE_ENV)
    args = _flag_args()
    assert resolve_treatment_flags(args)["gt_delivery_mode"]["disposition"] == "unset"
    assert os.environ[DELIVERY_MODE_ENV] == PUSH and args.gt_mode == "advisory"
    with pytest.raises(TreatmentFlagRefusal, match="attached_under_gt_off"):
        resolve_treatment_flags(_flag_args(gt_off=True, gt_delivery_mode="attached"))
    with pytest.raises(TreatmentFlagRefusal, match="attached_vs_gt_mode"):
        resolve_treatment_flags(_flag_args(gt_mode="enforced", gt_delivery_mode="attached"))
    with pytest.raises(TreatmentFlagRefusal, match="value_invalid:gt_delivery_mode"):
        resolve_treatment_flags(_flag_args(gt_delivery_mode="both"))


def test_submit_gate_never_blocks_under_attached(monkeypatch):
    from gt_engine import miniswe_runtime

    monkeypatch.setenv(DELIVERY_MODE_ENV, ATTACHED)
    store = _Store()
    engine = SimpleNamespace(store=store, phase="IMPLEMENT")
    session = SimpleNamespace(engine=engine, disabled=False, can_enforce=True,
                              plan_submit_gate=lambda: False)
    assert miniswe_runtime._run_submit_gate(session, "echo done", pre_execution=True) is True
    assert store.rows == [("submit_gate_bypassed", {"reason": "attached_delivery"})]


@pytest.mark.parametrize(("path", "is_test"), [
    ("src/__tests__/container.test.ts", True), ("tests/integration/test_attrs.py", True),
    ("ast/ast_test.go", True), ("lib/__tests/clone.js", True), ("src/container.ts", False),
    ("src/adaptix/_internal/provider.py", False), ("src/testenv_helper.rs", False),
])
def test_query_test_path_classifier(path, is_test):
    assert tool_server._looks_like_test(path) is is_test


def test_query_shows_source_before_tests():
    answer = {"fused": [{"stable_id": "a"}, {"stable_id": "b"}, {"stable_id": "c"}],
              "provenance": {"a": {"file_path": "src/__tests__/x.test.ts", "start_line": 3, "name": "it: x"},
                             "b": {"file_path": "src/x.ts", "start_line": 9, "qualified_name": "X.run"},
                             "c": {"file_path": "src/y.ts", "start_line": 1, "name": "y"}}}
    shaped = tool_server._shape_query(answer, ["q"])
    assert [row["file_path"] for row in shaped["1 source"]] == ["src/x.ts", "src/y.ts"]
    assert [row["file_path"] for row in shaped["2 related tests"]] == ["src/__tests__/x.test.ts"]


def test_grep_augmentation_brings_a_stale_graph_current_before_reading(monkeypatch):
    """After the agent's first edit the graph is invalidated; attached mode
    refreshes only on demand. The augmenter must refresh like a gt-* tool
    does, or it answers from nothing for the rest of the run (SWE-Live
    amoffat__sh-744, run 36303715831: 34 augmentations, 0 hits)."""
    from types import SimpleNamespace

    from gt_engine.capabilities import structure
    from gt_engine.grep_augment import GrepAugmenter

    class Adapter:
        graph_db = "graph.db"
        global_action = 0
        _edit_epoch = 1
        store = None

        def __init__(self):
            self.graph_fresh = False
            self.refreshes = 0

        def refresh_graph(self, *, phase):
            self.refreshes += 1
            self.graph_fresh = True
            return True

    adapter = Adapter()
    session = SimpleNamespace(_engine=adapter, capability_active=lambda name: True)

    def symbol_context(_session, symbol):
        if not adapter.graph_fresh:
            return SimpleNamespace(status="unavailable", answer=None)
        return SimpleNamespace(status="ok", answer={
            "definition": {"qualified_name": symbol, "kind": "Function",
                           "file_path": "tests/sh_test.py", "start_line": 131},
            "callers": [{"qualified_name": "test_async", "file_path": "tests/sh_test.py",
                         "line": 1700}],
            "caller_count": 1,
        })

    monkeypatch.setattr(structure, "symbol_context", symbol_context)
    block = GrepAugmenter(session).augment('grep -rn "create_tmp_test" tests/')
    assert adapter.refreshes == 1
    assert "create_tmp_test (Function) tests/sh_test.py:131" in block
    assert "called by: test_async" in block
    # A current graph is not refreshed again.
    GrepAugmenter(session).augment('grep -rn "create_tmp_test" tests/')
    assert adapter.refreshes == 1


def test_a_read_recovers_a_graph_the_startup_race_never_published():
    """No adopted graph at all is refreshed too - refresh_graph owns the
    bounded recovery build - so a superseded startup index does not leave
    attached mode graph-less for the whole run."""
    from types import SimpleNamespace

    from gt_engine.tool_server import refresh_if_stale

    calls = []
    adapter = SimpleNamespace(graph_db=None, graph_fresh=False,
                              refresh_graph=lambda *, phase: calls.append(phase))
    refresh_if_stale(SimpleNamespace(_engine=adapter, capability_active=lambda name: True))
    assert calls == ["graph_query"]
    fresh = SimpleNamespace(graph_db="g.db", graph_fresh=True,
                            refresh_graph=lambda *, phase: calls.append("unexpected"))
    refresh_if_stale(SimpleNamespace(_engine=fresh, capability_active=lambda name: True))
    assert calls == ["graph_query"]


def test_absolute_paths_inside_the_repository_become_relative(tmp_path):
    """Agents pass `gt-changes /app/x.py`; the graph keys files relatively."""
    from types import SimpleNamespace

    from gt_engine.tool_server import repo_relative_args

    (tmp_path / "pkg").mkdir()
    session = SimpleNamespace(_engine=SimpleNamespace(repo_root=str(tmp_path)))
    inside = str(tmp_path / "pkg" / "mod.py")
    outside = str(tmp_path.parent / "elsewhere.py")
    assert repo_relative_args(session, [inside, "run_query", "12", "./pkg/a.py", outside]) == [
        "pkg/mod.py", "run_query", "12", "pkg/a.py", outside]


def test_changes_baseline_without_git_is_unknown_not_a_fault(monkeypatch):
    """TB2 images may ship no git binary; gt-changes died with
    internal_error:FileNotFoundError (run 36306639259)."""
    import subprocess

    from gt_engine import tool_server

    def no_git(*_a, **_k):
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(tool_server.subprocess, "run", no_git)
    assert tool_server._base_text("/app", "parallel_linear.py") == ""


def test_callees_are_located_at_their_definition_not_the_call_site():
    """A callee row's call_line belongs to the searched symbol's file;
    printing it beside the callee's file named a location that does not
    exist ("New (lexer/lexer.go:1637)", DeepSWE abs, run 36306735814)."""
    from gt_engine.grep_augment import render_symbol_block
    from gt_engine.tool_render import render_answer

    answer = {
        "definition": {"qualified_name": "create_tmp_test", "kind": "Function",
                       "file_path": "tests/sh_test.py", "start_line": 131},
        "callers": [{"qualified_name": "test_async", "file_path": "tests/sh_test.py",
                     "line": 1690, "call_line": 1700}],
        "callees": [{"qualified_name": "StreamBufferer.flush", "file_path": "sh.py",
                     "line": 3273, "call_line": 141}],
        "caller_count": 1, "callee_count": 1,
    }
    block = render_symbol_block("create_tmp_test", answer)
    assert "called by: test_async (tests/sh_test.py:1700)" in block
    assert "calls: StreamBufferer.flush (sh.py:3273)" in block
    assert "sh.py:141" not in block
    lines, _ = render_answer(answer)
    text = "\n".join(lines)
    assert "sh.py:3273" in text and "sh.py:141" not in text
    assert "tests/sh_test.py:1700" in text
