"""Graph anchoring, blast radius, mode enumeration and edit order.

The graph fixture below mirrors the real producer schema (columns and label
vocabulary taken from a published graph), so these tests exercise the same SQL
the live path runs. Nothing here reads a task's tests or solution.
"""
from __future__ import annotations

import sqlite3

import pytest

from gt_engine.persistent_plan.anchors import (
    build_anchor_result,
    callers_of,
    connect_readonly,
    edit_order,
    mode_candidates,
    resolve_row_anchors,
)
from gt_engine.persistent_plan.ledger import build_requirement_ledger

_NODES = """
CREATE TABLE nodes (
  id INTEGER PRIMARY KEY, label TEXT, name TEXT, qualified_name TEXT,
  file_path TEXT, start_line INTEGER, end_line INTEGER, signature TEXT,
  return_type TEXT, is_exported INTEGER, is_test INTEGER, language TEXT,
  parent_id INTEGER, repo_id INTEGER
)
"""
_EDGES = """
CREATE TABLE edges (
  id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER, type TEXT,
  source_line INTEGER, source_file TEXT, resolution_method TEXT,
  confidence REAL, metadata TEXT, trust_tier TEXT, candidate_count INTEGER,
  evidence_type TEXT, verification_status TEXT, repo_id INTEGER
)
"""
_PROPERTIES = """
CREATE TABLE properties (
  id INTEGER PRIMARY KEY, node_id INTEGER, kind TEXT, value TEXT, line INTEGER,
  confidence REAL, property_id TEXT, start_line INTEGER, end_line INTEGER,
  extractor TEXT, evidence_method TEXT, trust_tier TEXT,
  verification_status TEXT, source_revision TEXT, repo_id INTEGER
)
"""


@pytest.fixture
def graph(tmp_path):
    """A small graph in the producer's real shape.

    ``resolve_scope`` calls ``build_container``; ``DebugMode`` is an enum-shaped
    class (constant members, no Enum label -- exactly how Python enums land in
    the graph); ``LoaderOptions`` is config-shaped; ``build_container`` carries
    defaulted parameters.
    """
    path = tmp_path / "graph.db"
    with sqlite3.connect(path) as db:
        db.execute(_NODES)
        db.execute(_EDGES)
        db.execute(_PROPERTIES)
        rows = [
            (1, "Function", "build_container", "build_container", "src/container.py", 10, 40,
             "def build_container(registry, strict=False, debug=DebugMode.OFF):", "Container",
             1, 0, "python", None, 1),
            (2, "Function", "resolve_scope", "resolve_scope", "src/scope.py", 5, 30,
             "def resolve_scope(container):", "Scope", 1, 0, "python", None, 1),
            (3, "Class", "DebugMode", "DebugMode", "src/modes.py", 1, 8, "class DebugMode:",
             "", 1, 0, "python", None, 1),
            (4, "Class", "LoaderOptions", "LoaderOptions", "src/options.py", 1, 12,
             "class LoaderOptions:", "", 1, 0, "python", None, 1),
            (5, "Function", "test_build_container", "test_build_container",
             "tests/test_container.py", 1, 9, "def test_build_container():", "", 0, 1,
             "python", None, 1),
            (6, "Function", "unrelated_helper", "unrelated_helper", "src/other.py", 1, 4,
             "def unrelated_helper():", "", 0, 0, "python", None, 1),
        ]
        db.executemany(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        db.executemany(
            "INSERT INTO edges (id,source_id,target_id,type,resolution_method,confidence) "
            "VALUES (?,?,?,?,?,?)",
            [
                (1, 2, 1, "CALLS", "import_resolved", 0.95),
                (2, 5, 1, "CALLS", "import_resolved", 0.95),
                (3, 1, 3, "READS", "import_resolved", 0.9),
                (4, 1, 4, "READS", "import_resolved", 0.9),
            ],
        )
        db.executemany(
            "INSERT INTO properties (node_id,kind,value,line) VALUES (?,?,?,?)",
            [
                (3, "class_field", "OFF = 0", 2),
                (3, "class_field", "ERRORS = 1", 3),
                (3, "class_field", "ALL = 2", 4),
                (4, "class_field", "retries: int = 3", 2),
                (4, "class_field", "timeout: float = 1.0", 3),
                (4, "class_field", "verbose: bool = False", 4),
                (1, "param", "registry", 10),
                (1, "param", "strict:bool opt=False", 10),
                (1, "param", "debug:DebugMode opt=DebugMode.OFF", 10),
            ],
        )
    return str(path)


def test_exact_identifier_resolves_to_its_definition(graph):
    connection = connect_readonly(graph)
    anchors = resolve_row_anchors(connection, ("build_container",))
    assert anchors
    first = anchors[0]
    assert first.name == "build_container"
    assert first.basis == "exact_name"
    assert first.file_path == "src/container.py"
    assert first.label == "Function"


def test_test_definitions_are_never_anchors(graph):
    connection = connect_readonly(graph)
    anchors = resolve_row_anchors(connection, ("test_build_container",))
    assert all(anchor.name != "test_build_container" for anchor in anchors)


def test_a_row_with_no_graph_match_abstains(graph):
    ledger = build_requirement_ledger("The zzzqqq subsystem must be rewritten.\n")
    result = build_anchor_result(graph, ledger)
    assert result.anchored_rows() == 0
    assert any(reason == "no_anchor" for _row, reason in result.abstentions)


def test_callers_are_the_blast_radius(graph):
    connection = connect_readonly(graph)
    callers = callers_of(connection, (1,))
    names = {caller.name for caller in callers.get(1, ())}
    assert "resolve_scope" in names
    assert "test_build_container" not in names, "test callers are not source blast radius"


def test_enum_shaped_class_is_found_without_an_enum_label(graph):
    """Python enums are plain Classes in the graph; structure must find them."""
    connection = connect_readonly(graph)
    anchors = resolve_row_anchors(connection, ("build_container",))
    modes = mode_candidates(connection, anchors)
    enum_modes = [mode for mode in modes if mode.kind == "enum_like"]
    assert enum_modes, [mode.symbol for mode in modes]
    debug = next(mode for mode in enum_modes if mode.symbol == "DebugMode")
    assert set(debug.members) == {"OFF", "ERRORS", "ALL"}
    assert debug.file_path == "src/modes.py"


def test_config_shaped_and_flag_parameter_modes_are_found(graph):
    connection = connect_readonly(graph)
    anchors = resolve_row_anchors(connection, ("build_container",))
    modes = mode_candidates(connection, anchors)
    by_kind = {mode.kind for mode in modes}
    assert "config_like" in by_kind
    assert "flag_param" in by_kind
    options = next(mode for mode in modes if mode.symbol == "LoaderOptions")
    assert set(options.members) == {"retries", "timeout", "verbose"}
    flags = next(mode for mode in modes if mode.kind == "flag_param")
    assert any("strict" in member for member in flags.members)
    assert not any(member.startswith("self") for member in flags.members)


def test_modes_record_which_anchor_reached_them(graph):
    connection = connect_readonly(graph)
    anchors = resolve_row_anchors(connection, ("build_container",))
    modes = mode_candidates(connection, anchors)
    debug = next(mode for mode in modes if mode.symbol == "DebugMode")
    assert 1 in debug.reached_from


def test_edit_order_puts_the_callee_before_its_caller(graph):
    connection = connect_readonly(graph)
    callee = resolve_row_anchors(connection, ("build_container",))
    caller = resolve_row_anchors(connection, ("resolve_scope",))
    order = edit_order(connection, {"row-caller": caller, "row-callee": callee})
    assert order.index("row-callee") < order.index("row-caller")


def test_edit_order_survives_a_call_cycle(graph, tmp_path):
    """A cycle is normal in real code and must not hang or drop a row."""
    path = tmp_path / "cycle.db"
    with sqlite3.connect(path) as db:
        db.execute(_NODES)
        db.execute(_EDGES)
        db.execute(_PROPERTIES)
        db.executemany(
            "INSERT INTO nodes (id,label,name,qualified_name,file_path,start_line,is_test) "
            "VALUES (?,?,?,?,?,?,0)",
            [
                (1, "Function", "ping", "ping", "src/a.py", 1),
                (2, "Function", "pong", "pong", "src/b.py", 1),
            ],
        )
        db.executemany(
            "INSERT INTO edges (source_id,target_id,type,confidence) VALUES (?,?,?,?)",
            [(1, 2, "CALLS", 0.9), (2, 1, "CALLS", 0.9)],
        )
    connection = connect_readonly(str(path))
    ping = resolve_row_anchors(connection, ("ping",))
    pong = resolve_row_anchors(connection, ("pong",))
    order = edit_order(connection, {"row-ping": ping, "row-pong": pong})
    assert set(order) == {"row-ping", "row-pong"}


def test_a_missing_graph_abstains_rather_than_raising():
    ledger = build_requirement_ledger("The loader must retry.\n")
    result = build_anchor_result(None, ledger)
    assert result.abstentions == (("*", "graph_unavailable"),)
    assert result.anchored_rows() == 0


def test_a_corrupt_graph_abstains_rather_than_raising(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database")
    ledger = build_requirement_ledger("The loader must retry.\n")
    result = build_anchor_result(str(broken), ledger)
    assert result.anchored_rows() == 0
    assert result.abstentions


def test_full_result_reports_surfaces_and_anchors(graph):
    prompt = "The build_container function must accept a registry.\n"
    ledger = build_requirement_ledger(prompt)
    result = build_anchor_result(graph, ledger)
    assert result.surfaces["nodes"] is True
    assert result.anchored_rows() == 1
    assert result.all_names()
    assert result.edit_order
