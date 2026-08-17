from __future__ import annotations

import hashlib

from gt_engine.decisive_derivation import (
    WorkspaceEntry,
    derive_decisive_facts,
)
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


def test_source_less_binary_gets_call_one_semantic_context_without_graph():
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
    assert "[obligation]" in frame.rendered_text
    assert "Task-decisive context" not in frame.rendered_text
    assert "ELF 64-bit LSB x86-64" in frame.rendered_text
    assert "extract.js" in frame.rendered_text


def test_semantic_substrate_exposes_changed_deliverable_state_once():
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
    assert absent is not None and "absent" in absent.rendered_text
    substrate.mark_dispatched(absent)

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

    assert present is not None
    assert "present" in present.rendered_text
    assert present.claim_ids != absent.claim_ids
    substrate.mark_dispatched(present)
    assert (
        substrate.compile_context(
            current_source_revision="source-2",
            current_call=3,
            provider_messages=(),
            max_chars=1_200,
        )
        is None
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
