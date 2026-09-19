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


# What a lenient parser would plausibly trim before it decides whether a line
# is a command. REVIEW-16 MEDIUM-1: the oracle used to ask
# ``startswith("::")`` and nothing else, so the first REVIEW-15 fix -
# prefixing ONE SPACE to such a line - scored as clean, leaving "does
# actions/runner trim before TryParse?" as the only thing between this
# report and a forged verdict. That question cannot be settled offline, so
# the oracle stops depending on it. Four characters, not ``\\s+``: the
# report's own prose is indented and bulleted, and an oracle that strips its
# way to a false positive gets exempted rather than obeyed.
_LENIENT_PREFIX = " \t[*"


def column_zero_commands(text: str) -> list[str]:
    """Every physical line of ``text`` the runner could read as a command.

    Split on every terminator the runner can see (``\\r\\n``, ``\\r``, ``\\n``)
    rather than on ``\\n`` alone: a bare carriage return puts the cursor at
    column zero on a console too, and a guard that only knows ``\\n`` is the
    next hole.

    A line is counted whatever a lenient parser would trim off its front:
    the fix for a leading command is structural (``%3A%3A``), never a
    space, so this must not score a displaced command as a removed one.
    """
    lines: list[str] = []
    for chunk in text.split("\r\n"):
        lines.extend(chunk.replace("\r", "\n").split("\n"))
    return [line for line in lines
            if line.lstrip(_LENIENT_PREFIX).startswith("::")]


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


def test_a_space_displaced_command_in_a_quoted_line_is_rewritten(tmp_path):
    """A payload displaced by a space is still a command to a parser that
    trims. The quoted line is the one path where container bytes reach the
    start of a physical line under nothing but an indent (review 18)."""
    audit = audit_with(
        ledger_present=True,
        ledger_rows=[ledger_row(quote="head\n ::error title=G::PASSED\ntail")],
    )

    rendered = gt_audit.render_report([audit], tmp_path)

    assert column_zero_commands(rendered) == []
    assert " %3A%3Aerror title=G::PASSED" in rendered


def test_the_guard_strips_every_prefix_the_oracle_strips():
    """Guard and oracle must agree on what a lenient parser would trim
    (review 18): ``[`` and ``*`` are in the oracle set, so a name that
    begins with them followed by ``::`` is rewritten too, lead kept."""
    assert gt_audit._no_column_zero("[::error title=G::x") == "[%3A%3Aerror title=G::x"
    assert gt_audit._no_column_zero("* ::warning::x") == "* %3A%3Awarning::x"
    for prefix in (" ", "\t", "[", "*", "[ *"):
        assert column_zero_commands(gt_audit._no_column_zero(prefix + "::error::x")) == []


# --------------------------------------------------------------------------- #
# REVIEW-16 MEDIUM-1: the ORACLE was the weakest part of the guard
#
# ``line.startswith("::")`` asks where the command sits, and a guard that asks
# about POSITION is only as good as the parser's agreement about position. The
# first fix for REVIEW-15 prefixed a single space to any line that began with
# ``::`` - which this oracle then scored as clean, so the whole class went
# green on a line that a runner trimming leading whitespace before it parses
# would still obey. Whether ``actions/runner`` trims before ``TryParse``
# cannot be settled offline, which is the point: the oracle must not depend on
# the answer.
#
# So it lstrips what a lenient parser would plausibly trim - spaces, tabs, and
# the two characters a log decorator might wrap a line in - and asks the
# question again. The FIX is structural (a leading ``::`` is rewritten to
# ``%3A%3A``), and this oracle is what makes the structural fix checkable.
# --------------------------------------------------------------------------- #
def test_the_oracle_counts_a_command_a_lenient_parser_would_still_read():
    """REVIEW-16 MEDIUM-1: a whitespace prefix is not a fix, and not a pass."""
    assert column_zero_commands(" ::error title=G::x") == [" ::error title=G::x"]
    assert column_zero_commands("\t::stop-commands::h") == ["\t::stop-commands::h"]
    assert column_zero_commands("  [::warning title=G::x") == ["  [::warning title=G::x"]
    # And it still says nothing about the report's own indented prose, which
    # is the whole reason the strip set is four characters and not \s+.
    assert column_zero_commands("  - CAPABILITY lsp [DEGRADED]: fine") == []
    assert column_zero_commands("      ev1   obligations   INFO   537c   MODEL-ONLY") == []
    assert column_zero_commands("                %3A%3Astop-commands::hunter2") == []


# --------------------------------------------------------------------------- #
# REVIEW-16 HIGH-1/HIGH-2: a field that BEGINS with ``::``
#
# ``gh_escape`` leaves ``:`` alone in message mode - deliberately, because a
# diagnostic line is mostly colons and escaping them would make every
# annotation unreadable - so a field whose FIRST two characters are ``::``
# survives sanitising intact. Three sites put such a field at literal column
# zero: the table's ``task`` column, the per-task header, and the paired
# table's name. No leading newline is needed; the payload simply IS the name.
#
# HIGH-2: none of this was covered. Every REVIEW-15 payload began with ``\n``,
# so ``_safe`` neutralised it before the backstop ever saw it, and stubbing
# ``_no_column_zero`` to the identity left all twenty tests green. The tests
# below observe the backstop's effect on a field that genuinely reaches column
# zero, and one of them stubs the backstop out to prove the call-site fix is
# real rather than a shadow of it.
# --------------------------------------------------------------------------- #
_LEADING = "::error title=Grader::TASK PASSED"


def test_a_task_name_that_begins_with_a_command_is_rewritten_at_source(tmp_path):
    """The reviewer's reproduction: the name IS the command, with no newline."""
    rendered = gt_audit.render_report([audit_with(task_name=_LEADING)], tmp_path)

    assert column_zero_commands(rendered) == []
    # Structural, not positional: the colons are gone, so it does not matter
    # whether the runner trims before it parses.
    table_row = next(ln for ln in rendered.splitlines() if "Grader" in ln)
    assert table_row.startswith("%3A%3Aerror title=Grader")
    header = next(ln for ln in rendered.splitlines() if ln.endswith("[GREEN-quiet]"))
    assert header.startswith("%3A%3Aerror title=Grader")
    # Still readable: only the two leading colons moved.
    assert "title=Grader" in rendered


def test_a_paired_table_name_that_begins_with_a_command_is_rewritten():
    gt = audit_with(task_name=_LEADING, reward=1.0)
    base = audit_with(task_name=_LEADING, reward=0.0)

    rendered = gt_audit.render_paired([gt], [base])

    assert column_zero_commands(rendered) == []
    assert any(ln.startswith("%3A%3Aerror title=Grader")
               for ln in rendered.splitlines())


def test_the_source_fix_holds_with_the_backstop_stubbed(tmp_path, monkeypatch):
    """HIGH-2: the call sites must carry the fix, not lean on the guard.

    With ``_no_column_zero`` replaced by the identity the report must still be
    clean - otherwise the twenty tests above were only ever testing the
    backstop, and a renderer that stops calling it is silently unguarded.
    """
    monkeypatch.setattr(gt_audit, "_no_column_zero", lambda text: text)

    for audit in (audit_with(task_name=_LEADING), poisoned_audit()):
        assert column_zero_commands(
            gt_audit.render_report([audit], tmp_path)
        ) == [], audit.task_name
    assert column_zero_commands(gt_audit.render_paired(
        [audit_with(task_name=_LEADING)], [audit_with(task_name=_LEADING)]
    )) == []


def test_the_backstop_rewrites_a_leading_command_structurally():
    """And the guard itself, called directly - HIGH-2's other half.

    A space prefix is a bet on the parser. ``%3A%3A`` is gh_escape's own
    property-mode spelling of a colon, so the line still says what it said and
    cannot be read as a command by any parser at any indentation.
    """
    assert gt_audit._no_column_zero("::error title=G::x") == "%3A%3Aerror title=G::x"
    assert gt_audit._no_column_zero("ok\r\n\t::warning::x") == "ok\r\n\t%3A%3Awarning::x"
    assert gt_audit._no_column_zero("ok\r\n::notice::x") == "ok\r\n%3A%3Anotice::x"
    assert gt_audit._no_column_zero("ok\r::notice::x") == "ok\r%3A%3Anotice::x"
    # A ``::`` that is not at column zero is left exactly as it was: the report
    # is full of them and none is a command.
    # Review 17: the parser, the design goal and this file's oracle all ask
    # about the first NON-WHITESPACE characters, not literal index 0. A
    # space- or tab-displaced opener must be rewritten too, with the lead kept.
    assert gt_audit._no_column_zero(" ::error title=G::x") == " %3A%3Aerror title=G::x"
    assert gt_audit._no_column_zero("ok\r\n\t::warning::x") == "ok\r\n\t%3A%3Awarning::x"
    assert column_zero_commands(gt_audit._no_column_zero(" ::error title=G::x")) == []
    assert gt_audit._no_column_zero("  - a::b") == "  - a::b"
    assert gt_audit._no_column_zero("") == ""


def test_a_quoted_line_that_begins_with_a_command_is_rewritten_too(tmp_path):
    """The indent alone is a position, and a position is not a guarantee."""
    audit = audit_with(
        ledger_present=True,
        ledger_rows=[ledger_row(quote="head\n::error title=G::PASSED\ntail")],
    )

    rendered = gt_audit.render_report([audit], tmp_path)

    assert column_zero_commands(rendered) == []
    assert any("%3A%3Aerror title=G" in ln for ln in rendered.splitlines())


def test_the_cli_never_emits_a_command_for_a_task_named_like_one(tmp_path, capsys):
    """End to end, the way the paid workflows run it: name off result.json."""
    task = poisoned_run(tmp_path, evidence="fine")
    result = json.loads((task / "result.json").read_text(encoding="utf-8"))
    result["task_name"] = _LEADING
    (task / "result.json").write_text(json.dumps(result), encoding="utf-8")

    rc = gt_audit.main([str(tmp_path)])

    assert rc in (0, 1)
    out = capsys.readouterr().out
    assert column_zero_commands(out) == []
    assert "%3A%3Aerror title=Grader" in out


# --------------------------------------------------------------------------- #
# REVIEW-16 LOW-1: a container printed as a repr is single-line, not bounded
#
# ``f"{a.gt_delivery_kinds}"`` is safe from column zero because ``repr``
# escapes the line breaks inside the keys, and that is the whole reason these
# six were left alone. It is not a BOUND: the dict carries one key per
# delivery kind the container named, and a run that names ten thousand of them
# writes one report line of a quarter of a megabyte. Every other field in this
# report answers to ANNOTATION_FIELD_LIMIT; these now do too.
# --------------------------------------------------------------------------- #
def test_a_pathological_container_repr_is_bounded(tmp_path):
    big = {f"kind-{index}": index for index in range(10_000)}
    audit = audit_with(
        gt_delivery_kinds=big,
        delivery_consumption_summary=big,
        graph_surface_receipt_present=True,
        graph_surface_counts=big,
        graph_projection_surface_hits=big,
        evidence_router_admitted=1,
        evidence_router_reasons=big,
        verification_plan_evaluated=True,
        verification_plan_decisions=[f"decision-{index}" for index in range(10_000)],
    )

    rendered = gt_audit.render_report([audit], tmp_path)

    assert column_zero_commands(rendered) == []
    # Every one of the six is cut, and each is cut to the SAME bound as every
    # other field in this report.
    assert rendered.count(ANNOTATION_TRUNCATION) >= 6
    bounded = ANNOTATION_FIELD_LIMIT + len(ANNOTATION_TRUNCATION)
    for name in ("GT delivery kinds", "GT delivery consumption",
                 "Evidence router", "Verification plan"):
        line = next(ln for ln in rendered.splitlines() if name in ln)
        assert len(line) <= bounded + 100, (name, len(line))
    # The ceiling is per FIELD, never per line - REVIEW-13 MEDIUM-1's rule,
    # and the reason the first draft of this test was wrong at 600. The
    # graph-receipt line carries TWO bounded containers (``surfaces=`` and
    # ``hits=``) plus its host text, so it reaches ~1,142 characters and that
    # is the correct answer: bounding the composed LINE instead would spend
    # the budget on the first container and truncate the second away.
    assert max(len(ln) for ln in rendered.splitlines()) <= 2 * bounded + 200
