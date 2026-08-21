"""General, cross-task observed-execution facts for the central runtime.

GT's grounded context may come from the task instruction, the repository
source, or the agent's own observed execution results.  This module is the
third source: it turns mechanically recognizable facts in a model command's
*raw output* into bounded, grounded, decision-relevant evidence.

The extractor is pattern-driven, not task-driven.  It recognizes *classes* of
observed facts (ELF/binary file type, interpreter/compiler identity, file
format markers, build artifacts) that can appear in any task's command output.
extract-elf is just one instance of a PIE-binary fact; the same pattern fires
for any task where the model inspects a compiled binary with ``readelf`` /
``file``.  A task whose output matches none of the patterns produces no fact
(fail-open abstention), and a task is never assumed to contain a fact it did
not observe.

Every fact is grounded in the exact observed output (source 3), source-revision
bound, and delivered at most once when it is new to the provider view.  It never
reads the grader, never parses hidden tests, and never fabricates.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from gt_engine.contributions import ContributionDisposition

# Maximum number of distinct observed-fact deliveries per task.  Bounded so the
# surface cannot spam the model and to keep the delivery deterministic.
MAX_OBSERVED_FACTS_PER_TASK = 4


@dataclass(frozen=True)
class ObservedFact:
    fact_id: str
    kind: str
    text: str
    command_sha256: str
    source_revision: str
    evidence_action: int
    eligible_call: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind,
            "text": self.text,
            "command_sha256": self.command_sha256,
            "source_revision": self.source_revision,
            "evidence_action": self.evidence_action,
            "eligible_call": self.eligible_call,
        }


# --- General pattern table (cross-task) -------------------------------------
# Each entry: (kind, regex, renderer(output) -> bounded text | None)
#
# The regex must be a mechanically certain, decision-relevant marker in a
# command's output.  Only exact, literal markers are used — never a heuristic
# guess.  A match is evidence the model already observed (source 3); it is not
# an invention and not a grader read.

# ELF file type from `readelf -h` / `file`.  A PIE ("DYN") binary uses relative
# virtual addresses; a non-PIE ("EXEC") executable uses a load base.  This is a
# real, decision-relevant fact that frequently contradicts the model's assumed
# convention (e.g. a hard-coded 0x400000 base).
_ELF_TYPE_RE = re.compile(
    r"(?im)^\s*Type:\s*(?P<kind>DYN|EXEC|REL|CORE)"
    r"(?:\s*\((?P<desc>[^)\n]*Position-Independent[^)\n]*)\))?"
)
_ELF_FILE_RE = re.compile(
    r"(?i)\b(?:ELF)\s+(?P<cls>\d+)-bit\b[^\n]*\b"
    r"(?P<kind>shared object|executable|relocatable|core file)\b"
)
_FILE_TYPE_DYN_RE = re.compile(
    r"(?i)\b(?:position-independent executable|pie executable|ELF 64-bit LSB shared object)\b"
)
_FILE_TYPE_EXEC_RE = re.compile(r"(?i)\b(?:ELF 64-bit LSB executable)\b")

# Interpreter/compiler identity, e.g. `node --version` -> `v20.11.1`,
# `python --version` -> `Python 3.11.5`.
_CMD_VERSION_RE = re.compile(
    r"(?im)^\s*(?:(?P<tool>node|python|python3|ruby|php|go|rustc|gcc|g\+\+|clang|java)"
    r"(?:\.exe)?\s+)?(?:v)?(?P<ver>[0-9][0-9A-Za-z._+-]{1,20})$"
)
_SHEBANG_RE = re.compile(r"^#!\s*(?P<path>/[^\s]+)")


def _fact_id(kind: str, text: str, source_revision: str) -> str:
    material = json_dumps([kind, text, source_revision])
    return "observed-" + hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:20]


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _elf_type(output: str, command: str) -> str | None:
    m = _ELF_TYPE_RE.search(output)
    if m:
        kind = m.group("kind").upper()
        if kind == "DYN":
            return (
                "The inspected binary is a PIE (ELF type DYN): its virtual addresses "
                "are relative to a load base, not absolute."
            )
        if kind == "EXEC":
            return (
                "The inspected binary is a non-PIE executable (ELF type EXEC): it uses "
                "a fixed load base."
            )
    m = _FILE_TYPE_DYN_RE.search(output)
    if m:
        return "The inspected binary is a PIE: its virtual addresses are relative to a load base."
    m = _FILE_TYPE_EXEC_RE.search(output)
    if m:
        return "The inspected binary is a non-PIE executable: it uses a fixed load base."
    return None


def _elf_file(output: str, command: str) -> str | None:
    m = _ELF_FILE_RE.search(output)
    if not m:
        return None
    cls = m.group("cls")
    kind = m.group("kind").lower()
    if "shared object" in kind or "position-independent" in kind:
        return (
            f"The inspected binary is a {cls}-bit PIE (shared object): "
            "its virtual addresses are relative."
        )
    return None


def _tool_version(output: str, command: str) -> str | None:
    m = _CMD_VERSION_RE.search(output)
    if not m:
        return None
    tool = (m.group("tool") or "").strip()
    if not tool:
        # Bare version line (e.g. `v20.11.1`); recover the tool from the command.
        cm = re.search(
            r"(?i)\b(node|python|python3|ruby|php|go|rustc|gcc|g\+\+|clang|java)\b",
            str(command or ""),
        )
        tool = cm.group(1) if cm else "tool"
    return f"Observed tool version: {tool} {m.group('ver')}."


def _shebang(output: str, command: str) -> str | None:
    m = _SHEBANG_RE.search(output)
    if not m:
        return None
    return f"Observed interpreter path: {m.group('path')}."


# Ordered: first matching recognizer wins (deterministic).
_RECOGNIZERS = (
    ("elf_type", _elf_type),
    ("elf_file", _elf_file),
    ("tool_version", _tool_version),
    ("shebang", _shebang),
)


def extract_observed_facts(
    *,
    command: str,
    output: str,
    source_revision: str,
    evidence_action: int,
    eligible_call: int,
    already_delivered: set[str] | None = None,
) -> tuple[ObservedFact, ...]:
    """Return observed facts recognized in a command's raw output.

    Fail-open: a command whose output matches no recognizer produces nothing.
    ``already_delivered`` deduplicates so the same fact is delivered once per
    task.  Only the first matching recognizer per output is used (deterministic).
    """

    if not output:
        return ()
    command_sha256 = hashlib.sha256(str(command or "").encode("utf-8", "replace")).hexdigest()
    facts: list[ObservedFact] = []
    seen = set(already_delivered or ())
    for kind, recognizer in _RECOGNIZERS:
        text = recognizer(output, command)
        if not text:
            continue
        fact_id = _fact_id(kind, text, source_revision)
        if fact_id in seen:
            continue
        seen.add(fact_id)
        facts.append(
            ObservedFact(
                fact_id=fact_id,
                kind=kind,
                text=text,
                command_sha256=command_sha256,
                source_revision=str(source_revision),
                evidence_action=int(evidence_action),
                eligible_call=int(eligible_call),
            )
        )
    return tuple(facts[:MAX_OBSERVED_FACTS_PER_TASK])


def observed_fact_payload(fact: ObservedFact) -> str:
    """Render a bounded, grounded, decision-relevant payload for the model."""

    return fact.text


def audit_observed_fact_lifecycle(receipt: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Join every extracted fact to one causally supported terminal outcome."""

    section = receipt.get("observed_facts") or {}
    failures: list[str] = []
    extractions = section.get("fact_extractions")
    if not isinstance(extractions, list):
        return ["extraction_inventory_missing"], {
            "extractions": 0,
            "decisions": 0,
            "deliveries": 0,
        }
    extraction_ids = [
        str(row.get("fact_id") or "") if isinstance(row, dict) else ""
        for row in extractions
    ]
    if any(not fact_id for fact_id in extraction_ids):
        failures.append("extraction_identity_missing")
    if len(set(extraction_ids)) != len(extraction_ids):
        failures.append("extraction_identity_duplicate")
    extraction_by_id = {
        str(row.get("fact_id") or ""): row
        for row in extractions
        if isinstance(row, dict) and str(row.get("fact_id") or "")
    }
    decisions = section.get("fact_decisions") or []
    decision_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in decisions:
        if not isinstance(row, dict) or not str(row.get("fact_id") or ""):
            failures.append("decision_identity_missing")
            continue
        decision_by_id.setdefault(str(row["fact_id"]), []).append(row)
    for fact_id, rows in decision_by_id.items():
        if len(rows) != 1:
            failures.append(f"decision_not_unique:{fact_id}:{len(rows)}")

    deliveries = section.get("fact_deliveries") or []
    delivery_by_id: dict[str, list[dict[str, Any]]] = {}
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            failures.append("delivery_malformed")
            continue
        ids = {
            str(item) for item in (delivery.get("fact_ids") or ()) if str(item)
        }
        direct = str(delivery.get("fact_id") or "")
        if direct:
            ids.add(direct)
        if not ids:
            failures.append("delivery_identity_missing")
        for fact_id in ids:
            delivery_by_id.setdefault(fact_id, []).append(delivery)

    compiler_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for call in (receipt.get("contribution_compiler") or {}).get("calls") or ():
        if not isinstance(call, dict):
            continue
        call_number = int(call.get("call") or 0)
        for row in call.get("accounting") or ():
            if not isinstance(row, dict):
                continue
            contribution_id = str(row.get("contribution_id") or "")
            if contribution_id:
                compiler_by_key[(call_number, contribution_id)] = row
    dispatched_calls = {
        int(row.get("call") or 0)
        for row in receipt.get("model_call_contexts") or ()
        if isinstance(row, dict)
        and str(row.get("dispatch_status") or "")
        in {"dispatched", "invoked", "response_received", "response_error"}
    }
    compiler_dispositions = {
        item.value
        for item in ContributionDisposition
        if item
        not in {
            ContributionDisposition.SELECTED,
            ContributionDisposition.STALE_SOURCE_REVISION,
        }
    }
    cap = int(section.get("max_deliveries_per_task") or MAX_OBSERVED_FACTS_PER_TASK)
    for fact_id, extraction in extraction_by_id.items():
        rows = decision_by_id.get(fact_id) or []
        if len(rows) != 1:
            failures.append(f"terminal_decision_missing:{fact_id}")
            continue
        decision = rows[0]
        disposition = str(decision.get("disposition") or "")
        call = int(decision.get("call") or 0)
        if disposition == ContributionDisposition.SELECTED.value:
            matched = delivery_by_id.get(fact_id) or []
            if len(matched) != 1:
                failures.append(f"selected_delivery_join_invalid:{fact_id}:{len(matched)}")
            elif int(matched[0].get("call") or 0) != call:
                failures.append(f"selected_delivery_call_mismatch:{fact_id}")
        elif disposition in compiler_dispositions:
            contribution_id = str(decision.get("contribution_id") or "")
            compiler = compiler_by_key.get((call, contribution_id))
            if (
                not contribution_id
                or compiler is None
                or str(compiler.get("surface") or "") != "observed_execution"
                or str(compiler.get("disposition") or "") != disposition
                or tuple(compiler.get("reason_codes") or ())
                != tuple(decision.get("reason_codes") or ())
            ):
                failures.append(f"compiler_decision_join_invalid:{fact_id}")
        elif disposition == ContributionDisposition.STALE_SOURCE_REVISION.value:
            if (
                str(decision.get("source_revision") or "")
                != str(extraction.get("source_revision") or "")
                or not str(decision.get("current_source_revision") or "")
                or str(decision.get("current_source_revision") or "")
                == str(extraction.get("source_revision") or "")
                or "stale_source_revision" not in (decision.get("reason_codes") or ())
            ):
                failures.append(f"stale_decision_proof_invalid:{fact_id}")
        elif disposition == "terminal_before_next_provider_request":
            eligible = int(extraction.get("eligible_call") or 0)
            if (
                call != eligible
                or int(decision.get("eligible_call") or 0) != eligible
                or any(dispatched >= eligible for dispatched in dispatched_calls)
                or "trajectory_ended" not in (decision.get("reason_codes") or ())
            ):
                failures.append(f"terminal_decision_proof_invalid:{fact_id}")
        elif disposition == "controller_only_task_delivery_limit":
            ordinal = int(decision.get("extraction_ordinal") or 0)
            if ordinal <= cap or "task_delivery_limit" not in (
                decision.get("reason_codes") or ()
            ):
                failures.append(f"delivery_limit_proof_invalid:{fact_id}")
        else:
            failures.append(f"decision_disposition_invalid:{fact_id}:{disposition}")

    known_ids = set(extraction_by_id)
    for fact_id in sorted(set(decision_by_id) - known_ids):
        failures.append(f"decision_without_extraction:{fact_id}")
    for fact_id in sorted(set(delivery_by_id) - known_ids):
        failures.append(f"delivery_without_extraction:{fact_id}")
    return failures, {
        "extractions": len(extractions),
        "extracted_fact_ids": len(extraction_by_id),
        "decisions": len(decisions),
        "deliveries": len(deliveries),
        "terminal_fact_ids": len(decision_by_id),
    }


__all__ = [
    "MAX_OBSERVED_FACTS_PER_TASK",
    "ObservedFact",
    "audit_observed_fact_lifecycle",
    "extract_observed_facts",
    "observed_fact_payload",
]
