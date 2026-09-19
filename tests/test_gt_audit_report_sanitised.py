"""REVIEW-15: the human report is stdio the Actions runner parses.

``scripts/gt_audit.py`` prints ``render_report(...)`` to the runner's STDOUT in
both paid workflows (``deepswe_gt_harness_product_p0731.yaml`` and
``swelive_gt_harness_paid.yaml`` run ``python scripts/gt_audit.py
attestation/tasks ... --json ...`` with stdout going to the step log; ``--json``
writes a FILE, it does not divert stdout). A line that BEGINS with ``::`` off
that stdout is a workflow command the runner obeys.

Most of what the report interpolates is container-derived free text: a
capability row's ``evidence`` comes verbatim out of
``<task>/agent/diagnostics.json``, written inside the container the model
controls, and ``annotated_capability_rows`` states in its docstring that it
leaves the ``state``/``evidence`` bytes exactly as written. The same holds for
a ledger row's ``status_reason`` and ``quote``, for the ``agent error ...``
verdict reason that carries ``agent_error``, for parser ``UNPARSED`` samples
(raw transcript lines) and for the task name.

This file pins ONE invariant end to end, and it is the guard for the whole
class rather than for the fields that happen to exist today:

    no physical line of ``render_report(...)`` output, for ANY input, and no
    physical line the CLI writes to stdout, begins with ``::``.

``tests/test_verify_run_receipts.py``'s AST guard cannot see this defect:
``scripts/gt_audit.py`` owns no ``::`` literal at all. The hole is that it
prints attacker-chosen bytes at column zero, so the guard has to be a
rendering test, not a source scan.
"""
from __future__ import annotations

import io
import json
import sys

import pytest

from scripts import gt_audit
from scripts.gh_annotations import ANNOTATION_FIELD_LIMIT, ANNOTATION_TRUNCATION
from tests.test_gt_audit import (
    capability_row,
    make_native_miniswe_task,
    write_diagnostics_document,
)

# The reviewer's payload, byte for byte. ``::stop-commands`` silences the
# step's own ``::error`` on rc=1 and the forged ``::error title=Grader::``
# states a verdict nothing produced.
PAYLOAD = "\n::stop-commands::hunter2\n::error title=Grader::TASK PASSED"


def column_zero_commands(text: str) -> list[str]:
    """Every physical line of ``text`` the runner could read as a command.

    Split on every terminator the runner can see (``\\r\\n``, ``\\r``, ``\\n``)
    rather than on ``\\n`` alone: a bare carriage return puts the cursor at
    column zero on a console too, and a guard that only knows ``\\n`` is the
    next hole.
    """
    lines: list[str] = []
    for chunk in text.split("\r\n"):
        lines.extend(chunk.replace("\r", "\n").split("\n"))
    return [line for line in lines if line.startswith("::")]


def audit_with(**overrides) -> gt_audit.TaskAudit:
    """A minimal audit row, with named fields overridden."""
    audit = gt_audit.TaskAudit(task_name="native-task", trial_dir="native-task__trial")
    audit.verdict = "GREEN-quiet"
    for key, value in overrides.items():
        setattr(audit, key, value)
    return audit


def ledger_row(**overrides) -> gt_audit.LedgerRow:
    row = gt_audit.LedgerRow(
        event_id="1", boundary="task_start", evidence_type="covering",
        tier="gateway", dedup_key="d", rendered_bytes_hash="0" * 64,
        chain_head="1" * 64, len_shipped_chars=12, status=gt_audit.CONFIRMED,
        status_reason="located in panel",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# --------------------------------------------------------------------------- #
# one field at a time
# --------------------------------------------------------------------------- #
def test_capability_evidence_cannot_open_a_workflow_command(tmp_path):
    """The reviewer's reproduction: evidence comes straight out of the container."""
    audit = audit_with(capabilities=[
        capability_row("lsp_promotion", "DEGRADED", PAYLOAD),
    ])

    rendered = gt_audit.render_report([audit], tmp_path)

    assert column_zero_commands(rendered) == []


def test_capability_state_cannot_open_a_workflow_command(tmp_path):
    """``state`` is left exactly as the container wrote it, same as evidence."""
    audit = audit_with(capabilities=[
        capability_row("lsp_promotion", PAYLOAD, "fine"),
    ])

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_agent_error_verdict_reason_cannot_open_a_workflow_command(tmp_path):
    """``agent_error`` reaches the report inside a verdict reason."""
    audit = audit_with(
        verdict="RED",
        agent_error=PAYLOAD,
        verdict_reasons=[f"agent error at iteration 3, 0+0 tokens: {PAYLOAD}"],
    )

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_ledger_status_reason_cannot_open_a_workflow_command(tmp_path):
    audit = audit_with(
        ledger_present=True,
        ledger_rows=[ledger_row(status_reason=PAYLOAD)],
    )

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_ledger_quote_cannot_open_a_workflow_command(tmp_path):
    audit = audit_with(
        ledger_present=True,
        ledger_rows=[ledger_row(quote=PAYLOAD)],
    )

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_a_multi_line_quote_stays_readable_and_stays_indented(tmp_path):
    """The quote is evidence a human reads, so it keeps its line breaks.

    Every physical line carries the report's own indent instead, which is what
    puts column zero out of reach without flattening the excerpt into one
    percent-escaped blob.
    """
    audit = audit_with(
        ledger_present=True,
        ledger_rows=[ledger_row(quote="first line\nsecond line\nthird line")],
    )

    rendered = gt_audit.render_report([audit], tmp_path)

    assert column_zero_commands(rendered) == []
    assert "second line" in rendered
    assert "third line" in rendered
    for line in rendered.splitlines():
        if "second line" in line or "third line" in line:
            assert line.startswith("    ")


def test_a_pathological_quote_is_bounded_by_line_count(tmp_path):
    """An unbounded quote floods the step log and buries every line around it."""
    audit = audit_with(
        ledger_present=True,
        ledger_rows=[ledger_row(quote="\n".join(f"q{i}" for i in range(500)))],
    )

    rendered = gt_audit.render_report([audit], tmp_path)

    quoted = [ln for ln in rendered.splitlines() if "q0" in ln or "q1" in ln]
    assert len(quoted) <= gt_audit.REPORT_BLOCK_LINE_LIMIT
    assert "q499" not in rendered


def test_task_name_cannot_open_a_workflow_command(tmp_path):
    """``task_name`` is the FIRST column: a newline in it starts a line."""
    audit = audit_with(task_name=PAYLOAD)

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_stop_reason_and_notes_and_unparsed_samples_cannot_open_a_command(tmp_path):
    audit = audit_with(
        stop_reason=PAYLOAD,
        notes=[PAYLOAD],
        unparsed_samples=[PAYLOAD],
        unparsed_structures=[PAYLOAD],
        ledger_issues=[PAYLOAD],
        verdict_reasons=[PAYLOAD],
    )

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_task_role_and_lifecycle_phases_cannot_open_a_command(tmp_path):
    """Both come off the attribution journal, which is written in the container."""
    audit = audit_with(
        graph_surface_receipt_present=True,
        task_role=PAYLOAD,
        lifecycle_checkpoints={PAYLOAD: {"count": 1}},
    )

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_feature_attribution_ids_cannot_open_a_command(tmp_path):
    audit = audit_with(feature_attribution={PAYLOAD: {
        "kind": PAYLOAD, "status": "WITNESSED", "deliveries": [],
        "exposed": False, "response_observed": False,
    }})

    assert column_zero_commands(gt_audit.render_report([audit], tmp_path)) == []


def test_paired_table_task_names_cannot_open_a_command():
    """``render_paired`` prints to the same stdout under ``--baseline``."""
    gt = audit_with(task_name=PAYLOAD, reward=1.0)
    base = audit_with(task_name=PAYLOAD, reward=0.0)

    assert column_zero_commands(gt_audit.render_paired([gt], [base])) == []


# --------------------------------------------------------------------------- #
# all at once, and bounded
# --------------------------------------------------------------------------- #
def poisoned_audit() -> gt_audit.TaskAudit:
    """Every artifact-derived field carrying the payload at the same time."""
    return audit_with(
        task_name=PAYLOAD,
        verdict="RED",
        stop_reason=PAYLOAD,
        agent_error=PAYLOAD,
        exception_info=PAYLOAD,
        verdict_reasons=[PAYLOAD, f"harness exception_info present: {PAYLOAD}"],
        gt_delivery_kinds={PAYLOAD: 1},
        delivery_consumption_summary={PAYLOAD: 1},
        gt_overhead_chars=7,
        ledger_present=True,
        deliveries_file_present=True,
        ledger_rows=[ledger_row(
            event_id=PAYLOAD, evidence_type=PAYLOAD, tier=PAYLOAD,
            status=PAYLOAD, status_reason=PAYLOAD, quote=PAYLOAD,
            provider_confirmed=True, provider_confirmation_reason=PAYLOAD,
        )],
        ledger_issues=[PAYLOAD],
        attribution_present=True,
        attribution_rows=1,
        attribution_issues=[PAYLOAD],
        lifecycle_checkpoints={PAYLOAD: {"count": 1}},
        graph_surface_receipt_present=True,
        task_role=PAYLOAD,
        graph_surface_counts={PAYLOAD: 1},
        graph_projection_surface_hits={PAYLOAD: 1},
        evidence_router_admitted=1,
        evidence_router_reasons={PAYLOAD: 1},
        verification_plan_evaluated=True,
        verification_plan_decisions=[PAYLOAD],
        capabilities=[
            capability_row(PAYLOAD, PAYLOAD, PAYLOAD),
            capability_row("lsp_promotion", "DEGRADED", PAYLOAD)
            | {"lsp_no_op_verdict": PAYLOAD, "lsp_no_op_detail": PAYLOAD},
        ],
        memory_pressure={"oom_kill_during_index": PAYLOAD,
                         "graph_refresh_refusals": 0, "headroom_refusals": 0},
        notes=[PAYLOAD],
        unparsed_samples=[PAYLOAD],
        unparsed_structures=[PAYLOAD],
        feature_attribution={PAYLOAD: {
            "kind": PAYLOAD, "status": "WITNESSED", "deliveries": [],
            "exposed": False, "response_observed": False,
        }},
    )


def test_every_artifact_derived_field_at_once_emits_no_command(tmp_path):
    rendered = gt_audit.render_report([poisoned_audit()], tmp_path)

    assert column_zero_commands(rendered) == []
    # And the payload cannot be reassembled out of the escaped text either:
    # the line break is gone, not merely displaced.
    assert "\n::stop-commands" not in rendered


def test_a_five_thousand_character_evidence_is_bounded(tmp_path):
    audit = audit_with(capabilities=[
        capability_row("lsp_promotion", "DEGRADED", "A" * 5000),
    ])

    rendered = gt_audit.render_report([audit], tmp_path)

    line = next(ln for ln in rendered.splitlines() if "CAPABILITY" in ln)
    assert ANNOTATION_TRUNCATION in line
    assert len(line) < ANNOTATION_FIELD_LIMIT + 200
    assert "A" * (ANNOTATION_FIELD_LIMIT + 1) not in rendered


# --------------------------------------------------------------------------- #
# the CLI: the actual sink, and the console that has to carry it
# --------------------------------------------------------------------------- #
def poisoned_run(tmp_path, evidence: str = PAYLOAD):
    task = make_native_miniswe_task(tmp_path)
    write_diagnostics_document(task, capabilities=[
        capability_row("lsp_promotion", "DEGRADED", evidence),
    ])
    return task


def test_cli_stdout_carries_no_column_zero_command(tmp_path, capsys):
    """End to end through ``main()``: the payload on disk, stdout captured."""
    poisoned_run(tmp_path)

    rc = gt_audit.main([str(tmp_path)])

    assert rc in (0, 1)
    assert column_zero_commands(capsys.readouterr().out) == []


def test_cli_json_receipt_is_safe_and_keeps_the_bytes(tmp_path, capsys):
    """``json.dumps`` escapes the newline, so the FILE keeps the evidence whole.

    Confirmed rather than asserted: the receipt is the lossless copy and the
    console line is the bounded one, and that split is the point.
    """
    poisoned_run(tmp_path)
    out = tmp_path / "audit.json"

    gt_audit.main([str(tmp_path), "--json", str(out)])
    capsys.readouterr()

    text = out.read_text(encoding="utf-8")
    assert column_zero_commands(text) == []
    payload = json.loads(text)
    evidence = payload["tasks"][0]["capabilities"][0]["evidence"]
    assert evidence == PAYLOAD


class Cp1252Console(io.StringIO):
    """A console that cannot hold non-cp1252 text and cannot be reconfigured.

    ``main()`` calls ``reconfigure(encoding="utf-8")`` on any stream that has
    it; a wrapped or captured stream does not, and that is the case the
    reviewer hit - a ``UnicodeEncodeError`` out of ``print`` takes the whole
    run down with a traceback and rc 1, which is a real verdict elsewhere.
    """

    encoding = "cp1252"

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        return super().write(text)


@pytest.mark.parametrize(
    "hostile",
    [" menu ", "boom \U0001f4a5", "na\xefve 中文"],
)
def test_a_cp1252_console_does_not_kill_the_run(tmp_path, monkeypatch, hostile):
    poisoned_run(tmp_path, evidence=hostile)
    console = Cp1252Console()
    monkeypatch.setattr(sys, "stdout", console)

    rc = gt_audit.main([str(tmp_path)])

    assert rc in (0, 1)
    assert column_zero_commands(console.getvalue()) == []


def test_a_line_separator_is_not_a_column_zero_escape(tmp_path):
    """U+2028 ends a line for ``str.splitlines`` - so it must not reach the report."""
    audit = audit_with(capabilities=[
        capability_row("lsp_promotion", "DEGRADED", "x ::error title=G::PASSED"),
    ])

    rendered = gt_audit.render_report([audit], tmp_path)

    assert [ln for ln in rendered.splitlines() if ln.startswith("::")] == []
