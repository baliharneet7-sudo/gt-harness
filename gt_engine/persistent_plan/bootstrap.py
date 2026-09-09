"""The single planning provider call, and the validation of what comes back.

One call, before the first edit, against a graph that is complete and current.
It is modelled on ``miniswe_runtime.bootstrap_select_catalog``: a real provider
request that creates no Mini-SWE action, counted at the transport so receipt
reconciliation stays exact, and advisory throughout -- a failure degrades the
plan to ABSTAINED and the run proceeds exactly as stock Mini-SWE would.

Validation is the part that keeps the plan factual. The model may only cite ids
this module offered it. An unknown row, a node the graph does not contain, or a
mode member that was never on the menu is DROPPED and recorded as an
abstention, never repaired into something plausible. A plan that quietly invents
an anchor is the confident-and-wrong failure this whole design exists to avoid.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import (
    STATUS_PARTIAL,
    STATUS_READY,
    InteractionCell,
    PersistentPlan,
    PlanInputs,
    PlanRow,
)

PLAN_TOOL_NAME = "write_persistent_plan"
MAX_ROWS_OFFERED = 60
MAX_MODES_OFFERED = 16
MAX_CALLERS_SHOWN = 6
MAX_DERIVED_ROWS = 24
MAX_COMMAND_CHARS = 300

VERIFICATION_KINDS = ("existing_test", "new_test", "command", "none")

# A verification command must run inside the repository. These name the
# benchmark's own machinery, which the plan may never reach into: reading the
# verifier would invalidate every number the run produces.
_FORBIDDEN_COMMAND_RE = re.compile(
    r"(?i)(?:^|[\s/])(?:/logs|/app/tests/config\.json|test\.patch|solution\.patch|"
    r"solve\.sh|grader\.py|task\.toml|fail_to_pass|pass_to_pass|f2p|p2p)\b"
)
_ABSOLUTE_OR_PARENT_RE = re.compile(r"(?:^|\s)(?:/|[A-Za-z]:[\\/]|\.\.[\\/])")


PLANNING_SYSTEM_PROMPT = (
    "You are planning a code change before any edit is made.\n"
    "\n"
    "You are given: every normative line of the task statement as a numbered "
    "requirement row, the definitions each row resolves to in a verified code "
    "graph, the callers of those definitions, the configuration modes and enums "
    "already present near them, and the repository's current test result.\n"
    "\n"
    "Produce a plan by calling the write_persistent_plan tool exactly once.\n"
    "\n"
    "Rules:\n"
    "1. Cite only ids that appear in the input. Never invent a node id, a row "
    "id, a mode symbol or a member name. If something is not in the input, say "
    "so in abstentions instead.\n"
    "2. For every requirement row, give the anchors it will touch and the "
    "command that would demonstrate it. A requirement with no way to check it "
    "is a comment, not a requirement.\n"
    "3. Work through the interaction matrix honestly. For each requirement and "
    "each mode member offered, decide whether the requirement has to behave "
    "differently under that member. Most cells will not apply; say why in one "
    "short clause. The cells that DO apply are the behaviours a reader of the "
    "task statement alone would never enumerate.\n"
    "4. When an interaction applies and needs its own proof, add a derived row "
    "stating the required behaviour under that specific member.\n"
    "5. Do not write implementation code, and do not restate the task. Plan "
    "only what must be true when the work is finished.\n"
)


def plan_tool_schema(inputs: PlanInputs) -> dict:
    """The single tool the planning call may invoke."""
    row_ids = [row.row_id for row in inputs.ledger.rows][:MAX_ROWS_OFFERED]
    return {
        "type": "function",
        "function": {
            "name": PLAN_TOOL_NAME,
            "description": (
                "Record the implementation plan. Cite only ids given in the "
                "message; anything else is dropped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "description": "One entry per requirement row you can anchor.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "row_id": {"type": "string", "enum": row_ids},
                                "anchors": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "description": "node_id values from the input only.",
                                },
                                "verification_kind": {
                                    "type": "string",
                                    "enum": list(VERIFICATION_KINDS),
                                },
                                "verification_command": {
                                    "type": "string",
                                    "description": (
                                        "Repository-relative command that would "
                                        "demonstrate this row."
                                    ),
                                },
                            },
                            "required": ["row_id"],
                        },
                    },
                    "interactions": {
                        "type": "array",
                        "description": (
                            "Requirement x existing mode member. Include the "
                            "cells you considered, applying or not."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "row_id": {"type": "string"},
                                "mode_symbol": {"type": "string"},
                                "member": {"type": "string"},
                                "applies": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["row_id", "mode_symbol", "member", "applies"],
                        },
                    },
                    "derived_rows": {
                        "type": "array",
                        "description": (
                            "Behaviours implied by an applying interaction that "
                            "need their own proof."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "from_row_id": {"type": "string"},
                                "mode_symbol": {"type": "string"},
                                "member": {"type": "string"},
                                "verification_command": {"type": "string"},
                            },
                            "required": ["text", "from_row_id"],
                        },
                    },
                    "edit_order": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "row_id values, the order you would edit in.",
                    },
                    "abstentions": {
                        "type": "array",
                        "description": "Anything the input could not settle.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "row_id": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["reason"],
                        },
                    },
                },
                "required": ["rows"],
            },
        },
    }


def _render_inputs(inputs: PlanInputs) -> str:
    """The planning message: requirements, graph facts, modes, baseline, gaps."""
    lines: list[str] = ["REQUIREMENTS (verbatim, one per line of the task statement)"]
    anchors_by_row = inputs.anchors.anchors
    for row in inputs.ledger.rows[:MAX_ROWS_OFFERED]:
        section = f" [{row.section}]" if row.section else ""
        lines.append(f"{row.row_id}{section} {row.text}")
        for anchor in anchors_by_row.get(row.row_id, ())[:4]:
            signature = anchor.signature.replace("\n", " ")[:160]
            lines.append(
                f"    anchor node_id={anchor.node_id} {anchor.label} {anchor.name} "
                f"@ {anchor.file_path}:{anchor.start_line} ({anchor.basis})"
            )
            if signature:
                lines.append(f"      signature: {signature}")
            callers = inputs.anchors.callers.get(anchor.node_id, ())
            if callers:
                shown = ", ".join(
                    f"{caller.name} @ {caller.file_path}"
                    for caller in callers[:MAX_CALLERS_SHOWN]
                )
                more = len(callers) - MAX_CALLERS_SHOWN
                suffix = f" (+{more} more)" if more > 0 else ""
                lines.append(f"      callers: {shown}{suffix}")
        if not anchors_by_row.get(row.row_id):
            lines.append("    anchor: NONE - the graph resolved nothing for this row")

    if inputs.anchors.modes:
        lines.append("")
        lines.append(
            "EXISTING MODES near those definitions. Each member is a path the "
            "code already takes. Decide, per requirement, whether it must "
            "behave differently under each one."
        )
        for mode in inputs.anchors.modes[:MAX_MODES_OFFERED]:
            members = ", ".join(mode.members[:12])
            lines.append(
                f"  {mode.symbol} ({mode.kind}) @ {mode.file_path}: {members}"
            )
    else:
        lines.append("")
        lines.append("EXISTING MODES: none reachable from these anchors.")

    lines.append("")
    lines.append(f"REPOSITORY TEST BASELINE: {inputs.baseline.summary()}")
    if inputs.baseline.captured and inputs.baseline.failing_names:
        lines.append(
            "  already failing before any edit: "
            + ", ".join(inputs.baseline.failing_names[:8])
        )
        lines.append(
            "  those are pre-existing; every OTHER test passing now must still pass."
        )

    if inputs.anchors.edit_order:
        lines.append("")
        lines.append(
            "SUGGESTED EDIT ORDER (callee before caller): "
            + " -> ".join(inputs.anchors.edit_order[:20])
        )

    if inputs.abstentions:
        lines.append("")
        lines.append("KNOWN GAPS in this input:")
        for target, reason in inputs.abstentions[:20]:
            lines.append(f"  {target}: {reason}")
    return "\n".join(lines)


def build_planning_messages(inputs: PlanInputs, issue_text: str) -> tuple[dict, ...]:
    return (
        {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "TASK STATEMENT\n"
                f"{issue_text}\n\n"
                f"{_render_inputs(inputs)}\n\n"
                "Call write_persistent_plan once."
            ),
        },
    )


def command_is_admissible(command: str) -> tuple[bool, str]:
    """A verification command must stay inside the repository."""
    text = (command or "").strip()
    if not text:
        return False, "empty"
    if len(text) > MAX_COMMAND_CHARS:
        return False, "too_long"
    if _FORBIDDEN_COMMAND_RE.search(text):
        return False, "names_benchmark_harness"
    if _ABSOLUTE_OR_PARENT_RE.search(text):
        return False, "escapes_repository"
    return True, ""


def validate_plan(
    payload: Any, inputs: PlanInputs
) -> tuple[tuple[PlanRow, ...], tuple[InteractionCell, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Keep only what the input actually offered; drop and record the rest."""
    abstentions: list[tuple[str, str]] = []
    if not isinstance(payload, dict):
        return (), (), (), (("*", "plan_payload_not_an_object"),)

    known_rows = {row.row_id: row for row in inputs.ledger.rows}
    known_nodes = set(inputs.anchors.all_node_ids())
    modes_by_symbol = {mode.symbol: mode for mode in inputs.anchors.modes}

    rows: list[PlanRow] = []
    seen_rows: set[str] = set()
    for item in payload.get("rows") or ():
        if not isinstance(item, dict):
            abstentions.append(("*", "plan_row_not_an_object"))
            continue
        row_id = str(item.get("row_id") or "")
        ledger_row = known_rows.get(row_id)
        if ledger_row is None:
            abstentions.append((row_id or "?", "phantom_row_id"))
            continue
        if row_id in seen_rows:
            continue
        seen_rows.add(row_id)
        anchors: list[int] = []
        for value in item.get("anchors") or ():
            try:
                node_id = int(value)
            except (TypeError, ValueError):
                abstentions.append((row_id, "phantom_node_id"))
                continue
            if node_id in known_nodes:
                anchors.append(node_id)
            else:
                abstentions.append((row_id, "phantom_node_id"))
        kind = str(item.get("verification_kind") or "")
        if kind not in VERIFICATION_KINDS:
            kind = ""
        command = str(item.get("verification_command") or "").strip()
        if command:
            admissible, reason = command_is_admissible(command)
            if not admissible:
                abstentions.append((row_id, f"verification_command_{reason}"))
                command = ""
        rows.append(
            PlanRow(
                row_id=row_id,
                text=ledger_row.text,
                anchors=tuple(dict.fromkeys(anchors)),
                verification_kind=kind,
                verification_command=command,
            )
        )

    interactions: list[InteractionCell] = []
    for item in payload.get("interactions") or ():
        if not isinstance(item, dict):
            continue
        row_id = str(item.get("row_id") or "")
        symbol = str(item.get("mode_symbol") or "")
        member = str(item.get("member") or "")
        if row_id not in known_rows:
            abstentions.append((row_id or "?", "phantom_row_id"))
            continue
        mode = modes_by_symbol.get(symbol)
        if mode is None:
            abstentions.append((row_id, "phantom_mode_symbol"))
            continue
        if member not in mode.members:
            abstentions.append((row_id, "phantom_mode_member"))
            continue
        interactions.append(
            InteractionCell(
                row_id=row_id,
                mode_symbol=symbol,
                member=member,
                applies=bool(item.get("applies")),
                reason=str(item.get("reason") or "")[:200],
            )
        )

    applying = {
        (cell.row_id, cell.mode_symbol, cell.member)
        for cell in interactions
        if cell.applies
    }
    for item in (payload.get("derived_rows") or ())[:MAX_DERIVED_ROWS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:500]
        parent = str(item.get("from_row_id") or "")
        symbol = str(item.get("mode_symbol") or "")
        member = str(item.get("member") or "")
        if not text or parent not in known_rows:
            abstentions.append((parent or "?", "phantom_derived_parent"))
            continue
        if symbol and (parent, symbol, member) not in applying:
            # A derived row must come from a cell the plan itself marked as
            # applying. Otherwise it is a new requirement with no provenance.
            abstentions.append((parent, "derived_row_without_applying_cell"))
            continue
        command = str(item.get("verification_command") or "").strip()
        if command:
            admissible, reason = command_is_admissible(command)
            if not admissible:
                abstentions.append((parent, f"verification_command_{reason}"))
                command = ""
        digest = hashlib.sha256(
            f"{parent}|{symbol}|{member}|{text}".encode("utf-8", "surrogatepass")
        ).hexdigest()[:12]
        rows.append(
            PlanRow(
                row_id=f"drv-{digest}",
                text=text,
                anchors=(),
                verification_kind=str(item.get("verification_kind") or "") or "new_test",
                verification_command=command,
                derived_from=parent,
                mode_symbol=symbol,
                mode_member=member,
            )
        )

    order = tuple(
        row_id
        for row_id in (payload.get("edit_order") or ())
        if isinstance(row_id, str) and row_id in seen_rows
    )
    for item in payload.get("abstentions") or ():
        if isinstance(item, dict) and item.get("reason"):
            abstentions.append(
                (str(item.get("row_id") or "*"), str(item["reason"])[:120])
            )
    return tuple(rows), tuple(interactions), order, tuple(abstentions)


def build_plan(payload: Any, inputs: PlanInputs, note: str = "") -> PersistentPlan:
    """Turn a validated tool payload into the immutable plan artifact.

    ``note`` records why the payload was unusable when it is, so the journal
    alone distinguishes "the model refused" from "the model never finished".
    """
    from .deterministic import build_deterministic_plan

    base = build_deterministic_plan(inputs)
    rows, interactions, order, abstentions = validate_plan(payload, inputs)
    combined = tuple(dict.fromkeys(tuple(inputs.abstentions) + tuple(abstentions)))
    if note:
        combined = tuple(dict.fromkeys(combined + (("*", note),)))
    if not rows:
        # Keep the floor. Every requirement, anchor, caller and covering-test
        # check was computed before the call and does not stop being true
        # because the response was unusable. The note records that the
        # enrichment did not happen.
        base.abstentions = combined or base.abstentions
        if base.abstentions:
            base.status = STATUS_PARTIAL
        base.process_id = _process_id(base)
        base.planning_receipt = _planning_receipt(base)
        return base
    rows = _merge_rows(base.rows, rows)
    order = order or base.edit_order
    if not order:
        order = tuple(
            row_id
            for row_id in inputs.anchors.edit_order
            if any(row.row_id == row_id for row in rows)
        ) or tuple(row.row_id for row in rows)
    status = STATUS_PARTIAL if combined else STATUS_READY
    plan = PersistentPlan(
        status=status,
        inputs=inputs,
        rows=rows,
        interactions=interactions,
        edit_order=order,
        abstentions=combined,
        origin="enriched",
    )
    plan.process_id = hashlib.sha256(
        plan.canonical_json().encode("utf-8", "surrogatepass")
    ).hexdigest()
    plan.planning_receipt = _planning_receipt(plan)
    return plan


def _merge_rows(
    base: tuple[PlanRow, ...], enriched: tuple[PlanRow, ...]
) -> tuple[PlanRow, ...]:
    """Enrichment may sharpen a row or add one; it may never remove one.

    A requirement the prompt states does not stop existing because the planning
    call omitted it, so the deterministic row survives with its own anchors and
    its covering-test check. Where the call supplied a value, the call wins.
    """
    by_id = {row.row_id: row for row in base}
    for row in enriched:
        current = by_id.get(row.row_id)
        if current is None:
            by_id[row.row_id] = row
            continue
        by_id[row.row_id] = PlanRow(
            row_id=current.row_id,
            text=current.text,
            anchors=row.anchors or current.anchors,
            verification_kind=row.verification_kind or current.verification_kind,
            verification_command=(
                row.verification_command or current.verification_command
            ),
            derived_from=row.derived_from,
            mode_symbol=row.mode_symbol,
            mode_member=row.mode_member,
        )
    return tuple(by_id.values())


def _process_id(plan: PersistentPlan) -> str:
    return hashlib.sha256(
        plan.canonical_json().encode("utf-8", "surrogatepass")
    ).hexdigest()


def _planning_receipt(plan: PersistentPlan) -> dict:
    """A ``gt.planning_process.v1`` receipt over graph-backed citations only."""
    citations = [
        {
            "row_id": row.row_id,
            "node_id": node_id,
            "source_revision": plan.inputs.source_revision,
            "graph_revision": plan.inputs.graph_revision,
        }
        for row in plan.rows
        for node_id in row.anchors
    ]
    return {
        "schema": "gt.planning_process.v1",
        "status": plan.status,
        "process_id": plan.process_id,
        "source_revision": plan.inputs.source_revision,
        "graph_revision": plan.inputs.graph_revision,
        "steps": [row.row_id for row in plan.rows],
        "citations": citations,
        "gaps": [reason for _target, reason in plan.abstentions],
    }


def response_finish_reason(response: Any) -> str:
    """Why the provider stopped. ``length`` means the plan never got written.

    Measured in production: the planning call returned finish_reason=length with
    4,096 completion tokens, all of them reasoning, no content and no tool call.
    A reasoning model spends its output budget thinking first, so a budget sized
    for the answer alone buys nothing but a truncated turn.
    """
    choices = (
        list(response.get("choices") or ())
        if isinstance(response, dict)
        else list(getattr(response, "choices", ()) or ())
    )
    if not choices:
        return ""
    first = choices[0]
    value = (
        first.get("finish_reason")
        if isinstance(first, dict)
        else getattr(first, "finish_reason", "")
    )
    return str(value or "")


def parse_tool_arguments(response: Any) -> dict | None:
    """Extract the plan tool's arguments from a provider response."""
    choices = (
        list(response.get("choices") or ())
        if isinstance(response, dict)
        else list(getattr(response, "choices", ()) or ())
    )
    if not choices:
        return None
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    calls = (
        list(message.get("tool_calls") or ())
        if isinstance(message, dict)
        else list(getattr(message, "tool_calls", ()) or ())
    )
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else getattr(call, "function", None)
        name = (
            function.get("name")
            if isinstance(function, dict)
            else getattr(function, "name", "")
        )
        if name != PLAN_TOOL_NAME:
            continue
        raw = (
            function.get("arguments")
            if isinstance(function, dict)
            else getattr(function, "arguments", "")
        )
        try:
            parsed = json.loads(str(raw or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
