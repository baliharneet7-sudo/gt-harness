"""The planning call: tool schema, validation, and what happens when it fails.

Validation is the safety property here: the model may cite only ids the input
offered. Everything else is dropped and recorded, never repaired.
"""
from __future__ import annotations

import sqlite3

import pytest

from gt_engine.persistent_plan import (
    STATUS_PARTIAL,
    STATUS_READY,
    build_plan_inputs,
)
from gt_engine.persistent_plan.bootstrap import (
    PLAN_TOOL_NAME,
    build_plan,
    build_planning_messages,
    command_is_admissible,
    parse_tool_arguments,
    plan_tool_schema,
    validate_plan,
)

PROMPT = (
    "Add a strict mode to the container loader.\n"
    "\n"
    "Assumptions:\n"
    " build_container must accept a registry argument\n"
    " The loader must respect DebugMode when reporting errors\n"
)


@pytest.fixture
def graph(tmp_path):
    path = tmp_path / "graph.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, label TEXT, name TEXT,"
            " qualified_name TEXT, file_path TEXT, start_line INTEGER,"
            " end_line INTEGER, signature TEXT, return_type TEXT,"
            " is_exported INTEGER, is_test INTEGER, language TEXT,"
            " parent_id INTEGER, repo_id INTEGER)"
        )
        db.execute(
            "CREATE TABLE edges (id INTEGER PRIMARY KEY, source_id INTEGER,"
            " target_id INTEGER, type TEXT, source_line INTEGER,"
            " source_file TEXT, resolution_method TEXT, confidence REAL,"
            " metadata TEXT, trust_tier TEXT, candidate_count INTEGER,"
            " evidence_type TEXT, verification_status TEXT, repo_id INTEGER)"
        )
        db.execute(
            "CREATE TABLE properties (id INTEGER PRIMARY KEY, node_id INTEGER,"
            " kind TEXT, value TEXT, line INTEGER, confidence REAL,"
            " property_id TEXT, start_line INTEGER, end_line INTEGER,"
            " extractor TEXT, evidence_method TEXT, trust_tier TEXT,"
            " verification_status TEXT, source_revision TEXT, repo_id INTEGER)"
        )
        db.executemany(
            "INSERT INTO nodes (id,label,name,qualified_name,file_path,"
            "start_line,signature,is_test,language) VALUES (?,?,?,?,?,?,?,0,?)",
            [
                (1, "Function", "build_container", "build_container",
                 "src/container.py", 10, "def build_container(registry):", "python"),
                (2, "Class", "DebugMode", "DebugMode", "src/modes.py", 1,
                 "class DebugMode:", "python"),
            ],
        )
        db.execute(
            "INSERT INTO edges (source_id,target_id,type,confidence)"
            " VALUES (1,2,'READS',0.9)"
        )
        db.executemany(
            "INSERT INTO properties (node_id,kind,value,line) VALUES (?,?,?,?)",
            [
                (2, "class_field", "OFF = 0", 2),
                (2, "class_field", "ERRORS = 1", 3),
                (2, "class_field", "ALL = 2", 4),
            ],
        )
    return str(path)


@pytest.fixture
def inputs(graph):
    return build_plan_inputs(
        PROMPT, graph_db=graph, source_revision="src1", graph_revision="g1",
        capture_baseline=False,
    )


def _row_id(inputs, needle: str) -> str:
    for row in inputs.ledger.rows:
        if needle in row.text:
            return row.row_id
    raise AssertionError(f"no ledger row containing {needle!r}")


def test_inputs_carry_rows_anchors_and_modes(inputs):
    counts = inputs.counts()
    assert counts["ledger_rows"] >= 3
    assert counts["anchored_rows"] >= 1
    assert counts["mode_candidates"] >= 1
    assert any(mode.symbol == "DebugMode" for mode in inputs.anchors.modes)


def test_the_planning_message_offers_ids_and_never_leaks_the_harness(inputs):
    messages = build_planning_messages(inputs, PROMPT)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    body = messages[1]["content"]
    assert "build_container" in body
    assert "DebugMode" in body
    assert "node_id=1" in body
    for forbidden in ("fail_to_pass", "test.patch", "grader.py", "/logs"):
        assert forbidden not in body


def test_the_tool_schema_pins_row_ids_to_the_ledger(inputs):
    schema = plan_tool_schema(inputs)
    assert schema["function"]["name"] == PLAN_TOOL_NAME
    enum = schema["function"]["parameters"]["properties"]["rows"]["items"][
        "properties"
    ]["row_id"]["enum"]
    assert enum == [row.row_id for row in inputs.ledger.rows]


def test_a_well_formed_plan_is_ready(inputs):
    row_id = _row_id(inputs, "build_container")
    payload = {
        "rows": [
            {
                "row_id": row_id,
                "anchors": [1],
                "verification_kind": "existing_test",
                "verification_command": "pytest tests/test_container.py",
            }
        ],
        "interactions": [
            {
                "row_id": row_id,
                "mode_symbol": "DebugMode",
                "member": "ALL",
                "applies": True,
                "reason": "error reporting differs",
            }
        ],
        "derived_rows": [
            {
                "text": "build_container reports every error under DebugMode.ALL",
                "from_row_id": row_id,
                "mode_symbol": "DebugMode",
                "member": "ALL",
            }
        ],
        "edit_order": [row_id],
    }
    plan = build_plan(payload, inputs)
    # PARTIAL, not READY: one prompt line resolves to no graph symbol and the
    # baseline was not captured in this fixture. Both are real gaps and the
    # plan is required to say so rather than present itself as complete.
    assert plan.status == STATUS_PARTIAL
    assert {reason for _t, reason in plan.abstentions} == {
        "no_anchor", "baseline_not_attempted",
    }
    assert plan.process_id
    assert len(plan.derived_rows) == 1
    assert plan.applicable_cells
    assert plan.planning_receipt["schema"] == "gt.planning_process.v1"
    assert plan.planning_receipt["citations"][0]["node_id"] == 1


def test_a_phantom_node_id_is_dropped_not_believed(inputs):
    row_id = _row_id(inputs, "build_container")
    payload = {"rows": [{"row_id": row_id, "anchors": [1, 9999]}]}
    rows, _cells, _order, abstentions = validate_plan(payload, inputs)
    assert rows[0].anchors == (1,)
    assert any(reason == "phantom_node_id" for _row, reason in abstentions)


def test_a_phantom_row_id_is_dropped(inputs):
    payload = {"rows": [{"row_id": "req-doesnotexist", "anchors": []}]}
    rows, _cells, _order, abstentions = validate_plan(payload, inputs)
    assert rows == ()
    assert any(reason == "phantom_row_id" for _row, reason in abstentions)


def test_a_mode_member_that_was_never_offered_is_dropped(inputs):
    row_id = _row_id(inputs, "build_container")
    payload = {
        "rows": [{"row_id": row_id, "anchors": [1]}],
        "interactions": [
            {"row_id": row_id, "mode_symbol": "DebugMode", "member": "INVENTED",
             "applies": True, "reason": "made up"},
            {"row_id": row_id, "mode_symbol": "NoSuchMode", "member": "X",
             "applies": True, "reason": "made up"},
        ],
    }
    _rows, cells, _order, abstentions = validate_plan(payload, inputs)
    assert cells == ()
    reasons = {reason for _row, reason in abstentions}
    assert "phantom_mode_member" in reasons
    assert "phantom_mode_symbol" in reasons


def test_a_derived_row_needs_an_applying_cell(inputs):
    """A derived requirement with no provenance is a new requirement."""
    row_id = _row_id(inputs, "build_container")
    payload = {
        "rows": [{"row_id": row_id, "anchors": [1]}],
        "interactions": [
            {"row_id": row_id, "mode_symbol": "DebugMode", "member": "OFF",
             "applies": False, "reason": "no difference"}
        ],
        "derived_rows": [
            {"text": "invented behaviour", "from_row_id": row_id,
             "mode_symbol": "DebugMode", "member": "OFF"}
        ],
    }
    rows, _cells, _order, abstentions = validate_plan(payload, inputs)
    assert all(not row.is_derived for row in rows)
    assert any(
        reason == "derived_row_without_applying_cell" for _row, reason in abstentions
    )


@pytest.mark.parametrize(
    "command,ok",
    [
        ("pytest tests/test_container.py", True),
        ("npm test -- --run", True),
        ("cat /logs/artifacts/model.patch", False),
        ("pytest tests/config.json", True),
        ("git apply test.patch", False),
        ("python grader.py", False),
        ("cat ../../secrets", False),
        ("pytest /app/tests", False),
        ("", False),
        ("x" * 400, False),
    ],
)
def test_verification_commands_stay_inside_the_repository(command, ok):
    admissible, _reason = command_is_admissible(command)
    assert admissible is ok


def test_a_command_naming_the_harness_is_stripped_but_the_row_survives(inputs):
    row_id = _row_id(inputs, "build_container")
    payload = {
        "rows": [
            {"row_id": row_id, "anchors": [1],
             "verification_command": "cat /logs/artifacts/model.patch"}
        ]
    }
    rows, _cells, _order, abstentions = validate_plan(payload, inputs)
    assert rows[0].verification_command == ""
    assert any("verification_command_" in reason for _row, reason in abstentions)


def test_an_empty_response_keeps_the_deterministic_plan(inputs):
    """The floor survives. Every requirement was known before the call."""
    plan = build_plan({"rows": []}, inputs)
    assert plan.origin == "deterministic"
    assert len(plan.rows) == len(inputs.ledger.rows)
    assert plan.abstentions


def test_an_unusable_response_still_yields_every_requirement(inputs):
    for payload in (None, "nope", {"rows": "not a list"}):
        plan = build_plan(payload, inputs)
        assert plan.origin == "deterministic"
        assert len(plan.rows) == len(inputs.ledger.rows), payload


def test_partial_status_when_anything_was_dropped(inputs):
    row_id = _row_id(inputs, "build_container")
    plan = build_plan(
        {"rows": [{"row_id": row_id, "anchors": [1, 4242]}]}, inputs
    )
    assert plan.status == STATUS_PARTIAL


def test_tool_arguments_are_parsed_from_a_provider_response():
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": PLAN_TOOL_NAME,
                                "arguments": '{"rows": [{"row_id": "req-a"}]}',
                            }
                        }
                    ]
                }
            }
        ]
    }
    assert parse_tool_arguments(response) == {"rows": [{"row_id": "req-a"}]}


def test_a_response_with_no_plan_call_parses_to_none():
    assert parse_tool_arguments({"choices": []}) is None
    assert parse_tool_arguments({"choices": [{"message": {"tool_calls": []}}]}) is None
    assert parse_tool_arguments(
        {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "other", "arguments": "{}"}}
        ]}}]}
    ) is None


def test_malformed_tool_arguments_parse_to_none():
    response = {
        "choices": [{"message": {"tool_calls": [
            {"function": {"name": PLAN_TOOL_NAME, "arguments": "{not json"}}
        ]}}]
    }
    assert parse_tool_arguments(response) is None


def test_inputs_without_a_graph_still_produce_a_ledger():
    inputs = build_plan_inputs(PROMPT, graph_db=None, capture_baseline=False)
    assert inputs.counts()["ledger_rows"] >= 3
    assert inputs.counts()["anchored_rows"] == 0
    assert any(reason == "graph_unavailable" for _t, reason in inputs.abstentions)


def test_ready_only_when_nothing_was_left_open(graph):
    """READY is reserved for a plan with no gaps at all."""
    prompt = "The build_container function must accept a registry argument.\n"
    inputs = build_plan_inputs(
        prompt, graph_db=graph, source_revision="src1", graph_revision="g1",
        capture_baseline=False,
    )
    # Remove the one remaining input-level gap so the assertion is about the
    # plan, not about the fixture's missing baseline.
    inputs.abstentions = ()
    row_id = inputs.ledger.rows[0].row_id
    plan = build_plan(
        {"rows": [{"row_id": row_id, "anchors": [1],
                   "verification_kind": "command",
                   "verification_command": "pytest -q"}]},
        inputs,
    )
    assert plan.status == STATUS_READY, plan.abstentions
    assert plan.abstentions == ()


def test_the_plan_artifact_is_deterministic(inputs):
    row_id = _row_id(inputs, "build_container")
    payload = {"rows": [{"row_id": row_id, "anchors": [1]}]}
    first = build_plan(payload, inputs)
    second = build_plan(payload, inputs)
    assert first.process_id == second.process_id
    assert first.canonical_json() == second.canonical_json()


def test_a_truncated_planning_call_is_named_as_such(inputs):
    """finish_reason=length must not read like a refusal.

    Measured in production: the planning call spent its whole output budget on
    reasoning tokens and returned no tool call. The journal has to say that, or
    the only way to tell a truncated call from an unusable one is to download a
    gigabyte of artifacts.
    """
    from gt_engine.persistent_plan.bootstrap import response_finish_reason

    response = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
    assert response_finish_reason(response) == "length"
    assert parse_tool_arguments(response) is None
    plan = build_plan(None, inputs, note="plan_call_truncated")
    assert any(reason == "plan_call_truncated" for _t, reason in plan.abstentions)
    # and the plan is still a plan: the call was the enrichment, not the floor
    assert plan.origin == "deterministic"
    assert len(plan.rows) == len(inputs.ledger.rows)


def test_finish_reason_is_empty_when_absent():
    from gt_engine.persistent_plan.bootstrap import response_finish_reason

    assert response_finish_reason({}) == ""
    assert response_finish_reason({"choices": []}) == ""
    assert response_finish_reason(None) == ""


def test_enrichment_never_drops_a_requirement(inputs):
    """The call named one row; the other requirements do not disappear."""
    row_id = _row_id(inputs, "build_container")
    plan = build_plan(
        {"rows": [{"row_id": row_id, "anchors": [1],
                   "verification_command": "pytest -k container"}]},
        inputs,
    )
    assert plan.origin == "enriched"
    assert len(plan.rows) == len(inputs.ledger.rows)
    enriched = plan.row(row_id)
    assert enriched.verification_command == "pytest -k container"


def test_the_planning_call_uses_the_runs_output_reservation():
    """A private budget smaller than the run's own is how the plan got cut off."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "gt_engine" / "miniswe_runtime.py"
    ).read_text(encoding="utf-8")
    assert "GT_PROVIDER_RESERVED_OUTPUT_TOKENS" in source
    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "PLAN_MAX_OUTPUT_TOKENS"
            for t in node.targets
        )
        for node in ast.walk(tree)
    )
    # and the old hardcoded 4096-only cap is gone
    assert "max_tokens=4096," not in source


def test_the_deterministic_plan_carries_checks_from_the_graph(tmp_path, graph):
    """A row's check comes from the covering tests, not from a suggestion."""
    from gt_engine.persistent_plan.deterministic import (
        build_deterministic_plan,
        default_check,
    )

    kind, command = default_check(("pytest",), ("tests/test_container.py",))
    assert kind == "existing_test"
    assert command == "pytest tests/test_container.py"

    # with no covering tests the repo's own suite is the check
    kind, command = default_check(("pytest",), ())
    assert (kind, command) == ("command", "pytest")

    # with no declared suite the plan admits it cannot prove the row
    assert default_check((), ()) == ("", "")

    inputs = build_plan_inputs(
        PROMPT, graph_db=graph, repo_root=str(tmp_path), capture_baseline=False
    )
    plan = build_deterministic_plan(inputs)
    assert plan.origin == "deterministic"
    assert len(plan.rows) == len(inputs.ledger.rows)
    assert plan.edit_order


def test_exactly_one_planning_call_is_ever_made():
    """The plan is made once. Phase 0 spends nothing; the call is guarded."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "gt_engine" / "miniswe_runtime.py"
    ).read_text(encoding="utf-8")
    body = source.split("def bootstrap_persistent_plan()", 1)[1].split(
        "\n    def query(", 1
    )[0]
    # one guard, set before anything can fail, and one provider call
    assert "if plan_started:" in body
    assert body.index("plan_started = True") < body.index("native_query(")
    assert body.count("native_query(") == 1

    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_plan"
    ]
    assert len(calls) == 1, "the plan is built from exactly one response"


def test_a_row_with_no_check_is_recorded_as_unprovable(inputs):
    """14 of 25 rows came back with no command and nothing said so."""
    row_id = _row_id(inputs, "build_container")
    _rows, _cells, _order, abstentions = validate_plan(
        {"rows": [{"row_id": row_id, "approach": "x"}]}, inputs
    )
    assert any(reason.startswith("no_check:") for _t, reason in abstentions)


def test_a_stated_reason_for_no_check_is_kept(inputs):
    row_id = _row_id(inputs, "build_container")
    _rows, _cells, _order, abstentions = validate_plan(
        {"rows": [{"row_id": row_id, "approach": "x",
                   "no_check_reason": "behaviour is only observable in CI"}]},
        inputs,
    )
    assert any(
        reason == "no_check:behaviour is only observable in CI"
        for _t, reason in abstentions
    )


def test_the_prompt_demands_a_concrete_check():
    from gt_engine.persistent_plan.bootstrap import PLANNING_SYSTEM_PROMPT

    assert "CONCRETE command" in PLANNING_SYSTEM_PROMPT
    assert "grepped for the exact string" in PLANNING_SYSTEM_PROMPT
    assert "no_check_reason" in PLANNING_SYSTEM_PROMPT
