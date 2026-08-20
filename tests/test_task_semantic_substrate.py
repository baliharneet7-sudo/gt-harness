from __future__ import annotations

import hashlib

from gt_engine.decisive_derivation import (
    WorkspaceEntry,
    derive_decisive_facts,
)
from gt_engine.hybrid_retrieval import EvidenceOrigin
from gt_engine.task_semantic_substrate import TaskSemanticSubstrate

ELF_64 = (
    b"\x7fELF\x02\x01\x01\x00"
    + b"\x00" * 10
    + b"\x3e\x00"
    + b"\x00" * 44
)


def _entry(path: str, text: str) -> WorkspaceEntry:
    payload = text.encode("utf-8")
    return WorkspaceEntry(
        path=path,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        head=payload,
        text=text,
    )


def test_source_less_binary_gets_only_novel_structural_context_without_graph():
    derivation = derive_decisive_facts(
        instruction=(
            "I have provided /app/a.out, a compiled C binary. "
            "Write /app/extract.js and produce /app/out.json."
        ),
        workspace=(
            WorkspaceEntry(
                path="a.out",
                size=len(ELF_64),
                sha256=hashlib.sha256(ELF_64).hexdigest(),
                head=ELF_64,
            ),
        ),
        deliverables=("extract.js", "out.json"),
        source_revision="source-1",
    )
    substrate = TaskSemanticSubstrate.from_derivation(
        derivation,
        evidence_action=0,
        eligible_call=1,
    )

    frame = substrate.compile_context(
        current_source_revision="source-1",
        current_call=1,
        provider_messages=(),
        max_chars=1_200,
    )

    assert frame is not None
    assert frame.eligible_call == 1
    assert "Current task evidence:" in frame.rendered_text
    assert "[structural]" in frame.rendered_text
    assert "[obligation]" not in frame.rendered_text
    assert "Task-decisive context" not in frame.rendered_text
    assert "ELF 64-bit LSB x86-64" in frame.rendered_text
    assert "extract.js" not in frame.rendered_text


def test_semantic_substrate_keeps_instruction_entailed_deliverable_state_private():
    instruction = "Create /app/out.json."
    initial = derive_decisive_facts(
        instruction=instruction,
        workspace=(_entry("README.md", "task\n"),),
        deliverables=("out.json",),
        source_revision="source-1",
    )
    substrate = TaskSemanticSubstrate.from_derivation(
        initial,
        evidence_action=0,
        eligible_call=1,
    )
    absent = substrate.compile_context(
        current_source_revision="source-1",
        current_call=1,
        provider_messages=(),
        max_chars=1_200,
    )
    assert absent is None
    assert substrate.as_dict()["compilations"][-1]["accounting"][0]["disposition"] == (
        "instruction_entailed_controller_only"
    )

    current = derive_decisive_facts(
        instruction=instruction,
        workspace=(
            _entry("README.md", "task\n"),
            _entry("out.json", '{"ok": true}\n'),
        ),
        deliverables=("out.json",),
        source_revision="source-2",
    )
    substrate.refresh(current, evidence_action=1, eligible_call=2)
    present = substrate.compile_context(
        current_source_revision="source-2",
        current_call=2,
        provider_messages=(),
        max_chars=1_200,
    )

    assert present is None
    assert substrate.as_dict()["compilations"][-1]["accounting"][0]["disposition"] == (
        "instruction_entailed_controller_only"
    )


def test_source_less_instruction_only_deliverable_does_not_change_call_one():
    derivation = derive_decisive_facts(
        instruction="Create /app/parallel_linear.py.",
        workspace=(_entry("README.md", "task\n"),),
        deliverables=("parallel_linear.py",),
        source_revision="source-0",
    )
    substrate = TaskSemanticSubstrate.from_derivation(
        derivation,
        evidence_action=0,
        eligible_call=1,
    )

    frame = substrate.compile_context(
        current_source_revision="source-0",
        current_call=1,
        provider_messages=(
            {"role": "user", "content": "Create /app/parallel_linear.py."},
        ),
        max_chars=1_200,
    )

    assert frame is None
    receipt = substrate.as_dict()["compilations"][-1]
    assert receipt["selected_count"] == 0
    assert receipt["accounting"][0]["disposition"] == (
        "instruction_entailed_controller_only"
    )


def test_provider_represented_fact_is_accounted_without_duplicate_text():
    derivation = derive_decisive_facts(
        instruction="Run pytest -q.",
        workspace=(_entry("README.md", "task\n"),),
        validation_commands=("pytest -q",),
        source_revision="source-1",
    )
    substrate = TaskSemanticSubstrate.from_derivation(
        derivation,
        evidence_action=0,
        eligible_call=1,
    )
    frame = substrate.compile_context(
        current_source_revision="source-1",
        current_call=1,
        provider_messages=({"role": "user", "content": "Create out.json, then run pytest -q."},),
        max_chars=1_200,
    )

    assert frame is None
    receipt = substrate.as_dict()
    assert receipt["represented_claim_count"] == 1


def test_model_authored_structural_fact_remains_controller_only():
    payload = ELF_64
    derivation = derive_decisive_facts(
        instruction="Inspect the supplied binary.",
        workspace=(
            WorkspaceEntry(
                path="agent-probe",
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                head=payload,
                origin=EvidenceOrigin.MODEL_AUTHORED.value,
            ),
        ),
        source_revision="source-2",
    )
    substrate = TaskSemanticSubstrate.from_derivation(
        derivation,
        evidence_action=4,
        eligible_call=3,
    )

    frame = substrate.compile_context(
        current_source_revision="source-2",
        current_call=3,
        provider_messages=(),
        max_chars=1_200,
    )

    assert frame is None
    accounting = substrate.as_dict()["compilations"][-1]["accounting"]
    assert accounting == [
        {
            "fact_id": derivation.facts[0].fact_id,
            "claim_id": derivation.facts[0].claim_id,
            "kind": "binary_format",
            "disposition": "model_authored_controller_only",
        }
    ]


def test_delivery_timing_compares_action_ordinals_with_completed_actions():
    derivation = derive_decisive_facts(
        instruction="Run pytest -q.",
        workspace=(_entry("README.md", "task\n"),),
        validation_commands=("pytest -q",),
        source_revision="source-1",
    )
    substrate = TaskSemanticSubstrate.from_derivation(
        derivation,
        evidence_action=34,
        eligible_call=27,
    )
    frame = substrate.compile_context(
        current_source_revision="source-1",
        current_call=27,
        provider_messages=(),
        max_chars=1_200,
    )
    assert frame is not None

    substrate.mark_dispatched(
        frame,
        call=27,
        completed_action_count_before_call=34,
    )

    delivery = substrate.as_dict()["deliveries"][-1]
    assert delivery["not_predictive"] is True
    assert delivery["completed_action_count_before_call"] == 34
