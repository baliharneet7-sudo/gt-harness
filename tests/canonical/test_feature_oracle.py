"""Ground-truth checks for the 21 GT features, as the agent receives them.

The fixture under ``fixtures/oracle`` was written so every correct answer is
known in advance: who calls what, which implementations a virtual call can
reach, which tests reach which file, what a slice must contain. Each test
asserts that truth - not a snapshot of whatever GT returned - through the
same tool surface the attached agent uses. Line numbers are located from the
fixture text, so the expectations are exact without being brittle.

A feature GT cannot yet deliver is a strict xfail naming the gap, so it flips
the moment the gap is closed.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from gt_engine.capabilities import analysis, localization, structure
from gt_engine.grep_augment import GrepAugmenter
from gt_engine.tool_server import EXIT_ANSWER, ToolDispatcher

ORACLE = Path(__file__).resolve().parent / "fixtures" / "oracle"
REVISION = "oracle-rev-1"


def line_of(root: Path, path: str, marker: str) -> int:
    for number, text in enumerate((root / path).read_text(encoding="utf-8").splitlines(), start=1):
        if marker in text:
            return number
    raise AssertionError(f"marker {marker!r} not in {path}")


def publish(binary: str, base: Path, tag: str):
    from gt_engine import indexer
    from gt_engine.engine_state import RuntimeLayout
    from gt_engine.gt_session import GTSession, GTSessionConfig
    from gt_engine.miniswe_integration import MiniSweAdapter

    root = base / "repo"
    shutil.copytree(ORACLE, root)
    layout = RuntimeLayout.resolve(workspace=root, state_root=base / "state", task_id=tag)
    diagnostics: list[str] = []
    graph = indexer.ensure_index(str(root), layout=layout, source_revision=REVISION,
                                 diagnostics=diagnostics)
    if graph is None:
        pytest.skip("producer could not publish the oracle graph: " + "; ".join(diagnostics))
    adapter = MiniSweAdapter(task_id=tag, state_dir=base / "state", predicates=[], repo_root=root,
                             graph_db=graph, layout=layout)
    adapter.engine_state.bind_initial_source(REVISION)
    return GTSession(GTSessionConfig(task_id=tag), engine=adapter), adapter, root


@pytest.fixture(scope="module")
def oracle(gt_index, tmp_path_factory):
    from gt_engine import indexer, wheel_perf

    binary, _info = gt_index
    patch = pytest.MonkeyPatch()
    patch.setenv("GT_INDEX_BINARY", binary)
    # The runtime enables patch analysis through apply_profile_env on every GT-on run.
    patch.setenv("GT_PATCH_DELTA", "1")
    if os.name == "nt":
        patch.setattr(indexer, "_has_verified_index_process_tree_guard", lambda: True)
        patch.setattr(indexer, "_kill_index_process_tree",
                      lambda process: (process.poll() is None and process.kill()) or True)
    wheel_perf.install()
    session, adapter, root = publish(binary, tmp_path_factory.mktemp("oracle"), "oracle")
    yield session, ToolDispatcher(session), root
    patch.undo()


def rows_of(answer, key):
    value = (answer or {}).get(key) or {}
    if isinstance(value, dict):
        return [row for band in value.values() for row in band]
    return list(value)


# ---------------------------------------------------------------- F1 / F2


def test_f2_definition_of_a_top_level_function(oracle):
    session, _d, root = oracle
    rows = localization.definition(session, "apply_tax").answer["definitions"]
    assert [(r["file_path"], r["start_line"]) for r in rows] == [
        ("py/shop/pricing.py", line_of(root, "py/shop/pricing.py", "def apply_tax"))]


@pytest.mark.xfail(strict=True, reason="F1 producer gap: nested function declarations are not "
                   "definitions (awilix createContainer pattern); only their callsites are indexed")
def test_f1_nested_function_is_a_definition_ts(oracle):
    session, _d, root = oracle
    rows = (localization.definition(session, "isReady").answer or {}).get("definitions") or []
    assert ("ts/src/container.ts", line_of(root, "ts/src/container.ts", "function isReady")) in {
        (r["file_path"], r["start_line"]) for r in rows}


@pytest.mark.xfail(strict=True, reason="F1 producer gap: nested function declarations are not "
                   "definitions in Python either (closure factories)")
def test_f1_nested_function_is_a_definition_py(oracle):
    session, _d, root = oracle
    rows = (localization.definition(session, "format_line").answer or {}).get("definitions") or []
    assert ("py/shop/pricing.py", line_of(root, "py/shop/pricing.py", "def format_line")) in {
        (r["file_path"], r["start_line"]) for r in rows}


# ---------------------------------------------------------------- F3 / F4 / F12


def test_f3_reference_points_at_the_call_even_inside_a_callback(oracle):
    session, dispatcher, root = oracle
    refs = rows_of(localization.references(session, "apply_tax").answer, "references_by_type")
    lines = {(r["file_path"], r.get("reference_line")) for r in refs}
    assert ("py/tests/test_pricing.py", line_of(root, "py/tests/test_pricing.py", "lambda: apply_tax")) in lines
    assert ("py/shop/pricing.py", line_of(root, "py/shop/pricing.py", "result = apply_tax")) in lines
    text, _code = dispatcher.dispatch("gt-refs", ["apply_tax"])
    assert f"py/tests/test_pricing.py:{line_of(root, 'py/tests/test_pricing.py', 'lambda: apply_tax')}" in text


def test_f4_callers_are_exactly_the_call_sites(oracle):
    session, _d, root = oracle
    rows = rows_of(structure.callers(session, "round_money", depth=1).answer, "callers_by_depth")
    assert {(r["file_path"], r["call_line"]) for r in rows} == {
        ("py/shop/pricing.py", line_of(root, "py/shop/pricing.py", "return round_money(taxed)"))}
    two = rows_of(structure.callers(session, "round_money", depth=2).answer, "callers_by_depth")
    assert {r["name"] for r in two} >= {"apply_tax", "total"}


def test_f4_heavily_called_symbol_still_answers(oracle):
    _s, dispatcher, _root = oracle
    text, code = dispatcher.dispatch("gt-callers", ["log_event", "2"])
    assert code == EXIT_ANSWER, text
    assert "emit_00" in text and "caller_count: 80" in text  # 40 emitters + 40 drivers


def test_f12_symbol_context_has_callers_and_callees(oracle):
    session, _d, _root = oracle
    answer = structure.symbol_context(session, "apply_tax").answer
    assert {r["name"] for r in answer["callers"]} >= {"total"}
    assert {r["name"] for r in answer["callees"]} >= {"round_money"}


# ---------------------------------------------------------------- F5 / F6 / F7


@pytest.mark.parametrize(("function", "callee", "targets"), [
    ("persist", "save", {"MemoryStore.save", "FileStore.save"}),
    ("TotalArea", "Area", {"Square.Area", "Circle.Area"}),
    ("welcome", "greet", {"Polite.greet", "Rude.greet"}),
])
def test_f6_virtual_call_lists_every_implementation(oracle, function, callee, targets):
    _s, dispatcher, _root = oracle
    text, code = dispatcher.dispatch("gt-calls", [function])
    assert code == EXIT_ANSWER, text
    line = next(l for l in text.splitlines() if f"  {callee} ->" in l)
    for target in targets:
        assert target in line, (target, line)
    assert "[other language" not in line


def test_f5_external_call_is_reported_unresolved(oracle):
    _s, dispatcher, _root = oracle
    text, _code = dispatcher.dispatch("gt-calls", ["run_report"])
    line = next(l for l in text.splitlines() if "  run ->" in l)
    assert "unresolved" in line


def test_f7_shape_flags_the_implementation_missing_a_method(oracle):
    _s, dispatcher, _root = oracle
    text, code = dispatcher.dispatch("gt-shape", ["Greeter"])
    assert code == EXIT_ANSWER, text
    rude = [l for l in text.splitlines() if "Rude" in l]
    polite = [l for l in text.splitlines() if "Polite" in l]
    assert rude and "MISSING farewell" in rude[0], text
    assert polite and "has every method" in polite[0], text


# ---------------------------------------------------------------- F8 / F18 / F9 / F10 / F11


def test_f18_routes_with_handlers_and_middleware(oracle):
    _s, dispatcher, _root = oracle
    text, code = dispatcher.dispatch("gt-routes", [])
    assert code == EXIT_ANSWER, text
    assert "/report -> report_view" in text and "/safe -> safe_view" in text
    express = next(l for l in text.splitlines() if "/api/items -> listItems" in l)
    assert "middleware=[audit]" in express


def test_f9_flow_follows_the_real_call_chain(oracle):
    session, _d, _root = oracle
    processes = structure.processes(session, "", limit=75).answer["processes"]
    chains = [[step.split(" (")[0] for step in p["steps"]] for p in processes]
    assert ["total", "apply_tax", "round_money"] in chains or any(
        chain[-3:] == ["total", "apply_tax", "round_money"] for chain in chains), chains[:10]


def test_f10_module_lists_real_sibling_files(oracle):
    _s, dispatcher, root = oracle
    text, code = dispatcher.dispatch("gt-module", ["py/shop/pricing.py"])
    assert code == EXIT_ANSWER, text
    members = [l.strip() for l in text.splitlines() if l.startswith("  ") and "/" in l]
    assert members and all((root / m.split()[0]).is_file() for m in members)


def test_f11_query_ranks_the_owning_source_file_first(oracle):
    _s, dispatcher, _root = oracle
    text, code = dispatcher.dispatch("gt-query", ["compute the tax on an order total"])
    assert code == EXIT_ANSWER, text
    source = text.split("1 source")[1].split("2 related tests")[0]
    first = [l for l in source.splitlines() if l.startswith("  ")][:3]
    assert any("py/shop/pricing.py" in l for l in first), text


# ---------------------------------------------------------------- F14-F17 / F19


def test_f17_slice_tool_shows_the_dependent_statements(oracle):
    _s, dispatcher, root = oracle
    path = "go/calc/shapes.go"
    text, code = dispatcher.dispatch("gt-slice", ["TotalArea", str(line_of(root, path, "return scaled"))])
    assert code == EXIT_ANSWER, text
    assert f"{path}:{line_of(root, path, 'total := 0.0')}  total := 0.0" in text, text


def test_f17_go_slice_contains_the_data_dependencies(oracle):
    session, _d, root = oracle
    path = "go/calc/shapes.go"
    answer = analysis.slice(session, "TotalArea", line_of(root, path, "return scaled")).answer
    lines = {n for item in answer["slices"] for n in item.get("slice_lines") or []}
    for marker in ("scaled := total * 2", "total += shape.Area()", "total := 0.0"):
        assert line_of(root, path, marker) in lines, (marker, sorted(lines))


def test_f17_python_slice_contains_the_data_dependencies(oracle):
    session, _d, root = oracle
    path = "py/shop/pricing.py"
    answer = analysis.slice(session, "total", line_of(root, path, "    return result")).answer
    lines = {n for item in answer["slices"] for n in item.get("slice_lines") or []}
    for marker in ("result = apply_tax", "subtotal = subtotal + item.price", "subtotal = 0"):
        assert line_of(root, path, marker) in lines, (marker, sorted(lines))


def test_f19_taint_path_from_request_handler_to_the_shell(oracle):
    session, _d, _root = oracle
    answer = analysis.taint(session, "report_view", "run_report").answer
    assert ["report_view", "run_report"] in [p.get("path") if isinstance(p, dict) else p
                                            for p in answer["paths"]]


# ---------------------------------------------------------------- F20


@pytest.mark.parametrize(("source", "test_file"), [
    ("py/shop/pricing.py", "py/tests/test_pricing.py"),
    ("go/calc/shapes.go", "go/calc/shapes_test.go"),
    ("ts/src/container.ts", "ts/src/__tests__/container.test.ts"),
])
def test_f20_tests_reaching_a_source_file(oracle, source, test_file):
    _s, dispatcher, _root = oracle
    text, code = dispatcher.dispatch("gt-tests", [source])
    assert code == EXIT_ANSWER and test_file in text, text


# ---------------------------------------------------------------- edits: F13 / F20 / F21


@pytest.fixture
def edited(gt_index, tmp_path, monkeypatch):
    from gt_engine import indexer, wheel_perf
    from gt_engine.attached_delivery import ATTACHED, DELIVERY_MODE_ENV

    binary, _info = gt_index
    monkeypatch.setenv("GT_INDEX_BINARY", binary)
    monkeypatch.setenv(DELIVERY_MODE_ENV, ATTACHED)
    monkeypatch.setenv("GT_PATCH_DELTA", "1")
    if os.name == "nt":
        monkeypatch.setattr(indexer, "_has_verified_index_process_tree_guard", lambda: True)
        monkeypatch.setattr(indexer, "_kill_index_process_tree",
                            lambda process: (process.poll() is None and process.kill()) or True)
    wheel_perf.install()
    return publish(binary, tmp_path, "oracle-edit")


def _edit(adapter, root: Path, path: str, *replacements: tuple[str, str]) -> None:
    """One captured edit transaction applying every replacement to ``path``."""
    from gt_engine.runtime_observation import capture_workspace, diff_workspace

    before = capture_workspace(root)
    target = root / path
    text = target.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    target.write_text(text, encoding="utf-8")
    adapter.record_edit_transaction(diff_workspace(before, capture_workspace(root), action_id=1,
                                                   command="edit"))


def test_f21_a_function_added_by_an_edit_is_found_with_its_caller(edited):
    session, adapter, root = edited
    _edit(adapter, root, "py/shop/pricing.py",
          ("result = apply_tax(subtotal, rate)", "result = apply_tax(discount(subtotal), rate)"),
          ("def make_formatter(prefix):",
           "def discount(amount):\n    return amount * 0.9\n\n\ndef make_formatter(prefix):"))
    dispatcher = ToolDispatcher(session)
    text, code = dispatcher.dispatch("gt-def", ["discount"])
    assert code == EXIT_ANSWER, text
    callers, code = dispatcher.dispatch("gt-callers", ["discount"])
    assert code == EXIT_ANSWER and "total" in callers, callers


def test_f13_changes_list_the_callers_of_an_edited_function(edited):
    session, adapter, root = edited
    _edit(adapter, root, "py/shop/pricing.py",
          ("def apply_tax(amount, rate):", "def apply_tax(amount, rate, region=None):"))
    text, code = ToolDispatcher(session).dispatch("gt-changes", [])
    assert code == EXIT_ANSWER, text
    assert "total" in text, text


def test_f20_syntax_error_is_reported(edited):
    session, _adapter, root = edited
    (root / "py/shop/pricing.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    text, _code = ToolDispatcher(session).dispatch("gt-check", ["py/shop/pricing.py"])
    assert "invalid" in text.lower() or "error" in text.lower(), text


# ---------------------------------------------------------------- automatic augmentation


def test_augmentation_names_the_real_callers_of_the_searched_symbol(oracle):
    session, _d, _root = oracle
    block = GrepAugmenter(session).augment('grep -rn "apply_tax" py/')
    assert "apply_tax" in block and "py/shop/pricing.py" in block
    assert "called by: total" in block or "total (" in block, block
