from __future__ import annotations

import hashlib
import json
import os
import tempfile

import pytest

from gt_engine.decisive_derivation import (
    DecisiveKind,
    DecisiveStatus,
    WorkspaceEntry,
    build_workspace_scan,
    derive_decisive_facts,
)
from gt_engine.hybrid_retrieval import EvidenceAuthority, EvidenceOrigin, StructuralLink
from gt_engine.persistent_execution_state import (
    BootstrapSelection,
    ContextFrameKind,
    PersistentExecutionStateEngine,
    build_bootstrap_catalog,
)
from gt_engine.repository_intelligence import RepositoryEvidence

# ---------------------------------------------------------------------------
# deterministic re-derivation: context-dominance candidate facts
# ---------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text_entry(path: str, text: str, size: int | None = None) -> WorkspaceEntry:
    return WorkspaceEntry(
        path=path,
        size=len(text) if size is None else size,
        sha256=_sha(text),
        text=text,
    )


ELF_64 = (
    b"\x7fELF"
    + bytes([2, 1, 1, 0])  # 64-bit, little-endian
    + bytes(8)  # e_ident padding (offsets 8-15)
    + bytes([2, 0])  # e_type: ET_EXEC
    + bytes([0x3E, 0])  # e_machine: x86-64
    + bytes(28)
)


def _evidence(
    source_revision: str = "source-1", anchors: tuple[dict, ...] = ()
) -> RepositoryEvidence:
    return RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        anchors=anchors,
        definitions=(),
        references=(),
        callers=(),
        project_checks=(),
        source_revision=source_revision,
        substrate_ready=True,
        index_current=True,
        status="healthy",
    )


def _engine(instruction: str, workspace: tuple[WorkspaceEntry, ...], **kwargs):
    catalog = build_bootstrap_catalog(
        instruction=instruction,
        evidence=_evidence(
            anchors=kwargs.pop(
                "evidence_anchors",
                ({"path": "main.py", "line": 1, "symbol": "main"},),
            )
        ),
        documents=(),
        structural_links=(),
        source_revision="source-1",
        graph_revision="graph-1",
        repository_complete=True,
        explicit_checks=kwargs.pop("explicit_checks", ()),
        task_deliverables=kwargs.pop("task_deliverables", ()),
    )
    decisive = derive_decisive_facts(
        instruction=instruction,
        workspace=workspace,
        validation_commands=tuple(
            item.anchors[0]
            for item in catalog.items
            if item.kind.value == "validation" and item.required and item.anchors
        ),
        deliverables=tuple(
            item.path
            for item in catalog.items
            if item.kind.value == "deliverable" and item.required and item.path
        ),
        source_revision="source-1",
    )
    engine = PersistentExecutionStateEngine.initialize_from_graph(
        task=instruction,
        catalog=catalog,
        structural_links=(),
        present_paths=tuple(entry.path for entry in workspace),
        decisive=decisive,
    )
    engine.apply_bootstrap(BootstrapSelection(valid=True), current_source_revision="source-1")
    return engine


class TestDecisiveDerivationDeterminism:
    def test_identical_inputs_produce_identical_facts(self):
        instruction = (
            "Please solve this issue: Please help sanitize my github repository "
            "dclm of all API keys. If an AWS_ACCESS_KEY_ID is found replace the "
            "actual value with the placeholder."
        )
        workspace = (
            _text_entry(
                "config.py",
                'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\nAWS_SECRET_ACCESS_KEY = "x"\n',
            ),
            _text_entry("main.py", "print('ok')\n"),
        )
        first = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            validation_commands=("pytest -q",),
            source_revision="r1",
        )
        second = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            validation_commands=("pytest -q",),
            source_revision="r1",
        )
        assert first.as_dict() == second.as_dict()
        assert first.status is DecisiveStatus.DERIVED

    def test_ordering_does_not_change_facts(self):
        instruction = "Solve the a.out binary task."
        workspace = (
            _text_entry("main.c", "int main(void) { return 0; }\n"),
            WorkspaceEntry("a.out", len(ELF_64), _sha("a.out"), ELF_64),
        )
        reversed_ws = workspace[::-1]
        first = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            source_revision="r1",
        )
        second = derive_decisive_facts(
            instruction=instruction,
            workspace=reversed_ws,
            source_revision="r1",
        )
        assert first.as_dict() == second.as_dict()

    def test_revision_change_only_changes_revision_field(self):
        instruction = "Solve the a.out binary task."
        workspace = (
            WorkspaceEntry("a.out", len(ELF_64), _sha("a.out"), ELF_64),
        )
        first = derive_decisive_facts(
            instruction=instruction, workspace=workspace, source_revision="r1"
        )
        second = derive_decisive_facts(
            instruction=instruction, workspace=workspace, source_revision="r2"
        )
        first_facts = [
            {k: v for k, v in fact.items() if k not in ("fact_id", "source_revision")}
            for fact in first.as_dict()["facts"]
        ]
        second_facts = [
            {k: v for k, v in fact.items() if k not in ("fact_id", "source_revision")}
            for fact in second.as_dict()["facts"]
        ]
        assert first_facts == second_facts
        assert first.facts[0].claim_id == second.facts[0].claim_id
        assert first.facts[0].fact_id != second.facts[0].fact_id
        assert first.facts[0].source_revision != second.facts[0].source_revision


class TestDecisiveDerivationDetectors:
    def test_secret_location_reports_class_not_value(self):
        instruction = (
            "Please help sanitize my github repository dclm of all API keys. "
            "If an AWS_ACCESS_KEY_ID is found replace the actual value with the placeholder."
        )
        workspace = (
            _text_entry(
                "config.py",
                'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n',
            ),
            _text_entry("README.md", "# docs\n"),
        )
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            source_revision="r1",
        ).facts
        secret = next(
            (f for f in facts if f.kind is DecisiveKind.SECRET_LOCATION), None
        )
        assert secret is not None
        assert secret.path == "config.py"
        assert "AKIAIOSFODNN7EXAMPLE" not in secret.gap_text
        assert "AWS_ACCESS_KEY_ID" in secret.gap_text
        assert "1 file(s) contaminated" in secret.gap_text

    def test_secret_clean_workspace_abstains(self):
        instruction = (
            "Please help sanitize my github repository dclm of all API keys. "
            "If an AWS_ACCESS_KEY_ID is found replace the actual value with the placeholder."
        )
        workspace = (_text_entry("config.py", "X = 1\n"),)
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            source_revision="r1",
        ).facts
        assert not any(f.kind is DecisiveKind.SECRET_LOCATION for f in facts)

    def test_binary_format_reports_elf_description(self):
        instruction = (
            "I have provided a file a.out that is a compiled C binary. "
            "Write me a program extract.js that when run with node extract.js "
            "/app/a.out > out.json extracts memory values."
        )
        workspace = (
            WorkspaceEntry("a.out", len(ELF_64), _sha("a.out"), ELF_64),
            _text_entry("main.c", "int main(void) { return 0; }\n"),
        )
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            deliverables=("extract.js",),
            source_revision="r1",
        ).facts
        binary = next((f for f in facts if f.kind is DecisiveKind.BINARY_FORMAT), None)
        assert binary is not None
        assert "ELF 64-bit LSB" in binary.gap_text
        assert "x86-64" in binary.gap_text

    def test_binary_format_absent_file_abstains(self):
        instruction = "Write a program extract.js that reads /app/a.out and outputs out.json."
        workspace = (_text_entry("main.c", "int main(void) { return 0; }\n"),)
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            source_revision="r1",
        ).facts
        assert not any(f.kind is DecisiveKind.BINARY_FORMAT for f in facts)

    def test_required_check_emitted_for_declared_validation(self):
        instruction = "Fix the failing tests in this repository."
        workspace = (_text_entry("main.py", "print('ok')\n"),)
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            validation_commands=("pytest -q",),
            source_revision="r1",
        ).facts
        check = next((f for f in facts if f.kind is DecisiveKind.REQUIRED_CHECK), None)
        assert check is not None
        assert "pytest -q" in check.gap_text

    def test_required_check_abstains_without_declared_validation(self):
        instruction = "Fix the failing tests in this repository."
        workspace = (_text_entry("main.py", "print('ok')\n"),)
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            source_revision="r1",
        ).facts
        assert not any(f.kind is DecisiveKind.REQUIRED_CHECK for f in facts)

    def test_deliverable_presence_and_absence(self):
        instruction = (
            "Write the file /app/pipeline_parallel.py that implements "
            "the parallel pipeline."
        )
        absent = derive_decisive_facts(
            instruction=instruction,
            workspace=(_text_entry("README.md", "docs\n"),),
            deliverables=("pipeline_parallel.py",),
            source_revision="r1",
        ).facts
        absent_fact = next(
            (f for f in absent if f.kind is DecisiveKind.DELIVERABLE_STATE), None
        )
        assert absent_fact is not None
        assert "absent" in absent_fact.gap_text

        present = derive_decisive_facts(
            instruction=instruction,
            workspace=(_text_entry("pipeline_parallel.py", "import torch\n"),),
            deliverables=("pipeline_parallel.py",),
            source_revision="r1",
        ).facts
        assert not any(f.kind is DecisiveKind.DELIVERABLE_STATE for f in present)


class TestDecisiveDerivationBoundedness:
    def test_fact_cap_is_enforced(self):
        instruction = "Solve the a.out binary task with extract.js."
        workspace = tuple(
            _text_entry(f"f{i}.c", f"int f{i}(void) {{ return {i}; }}\n") for i in range(40)
        ) + (
            WorkspaceEntry("a.out", len(ELF_64), _sha("a.out"), ELF_64),
        )
        facts = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            source_revision="r1",
        ).facts
        assert len(facts) <= 6
        assert sum(len(f.gap_text) for f in facts) <= 6 * 280 + 1000

    def test_secret_values_never_leak(self):
        instruction = (
            "Please help sanitize my github repository dclm of all API keys. "
            "If an AWS_ACCESS_KEY_ID is found replace the actual value with the placeholder."
        )
        secret_value = "AKIAIOSFODNN7EXAMPLE"
        workspace = (
            _text_entry("config.py", f'AWS_ACCESS_KEY_ID = "{secret_value}"\n'),
            _text_entry("other.py", f'GITHUB_TOKEN = "{secret_value}"\n'),
        )
        rendered = json.dumps(
            derive_decisive_facts(
                instruction=instruction,
                workspace=workspace,
                source_revision="r1",
            ).as_dict()
        )
        assert secret_value not in rendered

    def test_workspace_scan_respects_skip_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "node_modules"), exist_ok=True)
            os.makedirs(os.path.join(tmp, ".git"), exist_ok=True)
            with open(os.path.join(tmp, "node_modules", "big.js"), "w", encoding="utf-8") as fh:
                fh.write("x" * 100000)
            with open(os.path.join(tmp, ".git", "config"), "w", encoding="utf-8") as fh:
                fh.write("y" * 100000)
            with open(os.path.join(tmp, "main.py"), "w", encoding="utf-8") as fh:
                fh.write("print('ok')\n")
            with open(os.path.join(tmp, "reward.txt"), "w", encoding="utf-8") as fh:
                fh.write("reward=1\n")
            entries = build_workspace_scan(tmp)
            paths = {entry.path for entry in entries}
            assert "main.py" in paths
            assert not any("node_modules" in p for p in paths)
            assert not any(".git" in p for p in paths)
            assert not any("reward.txt" in p for p in paths)

    def test_workspace_scan_caps_file_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(700):
                with open(os.path.join(tmp, f"f{i}.py"), "w", encoding="utf-8") as fh:
                    fh.write("# x\n")
            entries = build_workspace_scan(tmp)
            assert len(entries) <= 512

    def test_scan_missing_directory_abstains(self):
        derivation = derive_decisive_facts(
            instruction="Solve the a.out binary task.",
            workspace=(),
            source_revision="r1",
        )
        assert derivation.status is DecisiveStatus.ABSTAINED
        assert "workspace_scan_empty" in derivation.reason_codes


class TestDecisiveDerivationNoGraderContact:
    def test_derivation_never_reads_grader_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "tests"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "solution"), exist_ok=True)
            with open(os.path.join(tmp, "tests", "hidden_test.py"), "w", encoding="utf-8") as fh:
                fh.write("def test_secret():\n    assert False\n")
            with open(os.path.join(tmp, "test_outputs.py"), "w", encoding="utf-8") as fh:
                fh.write("# grader\n")
            with open(os.path.join(tmp, "solution", "ref.py"), "w", encoding="utf-8") as fh:
                fh.write("print('reference')\n")
            with open(os.path.join(tmp, "main.py"), "w", encoding="utf-8") as fh:
                fh.write("print('ok')\n")
            entries = build_workspace_scan(tmp)
            paths = {entry.path for entry in entries}
            assert "main.py" in paths
            assert "test_outputs.py" not in paths
            assert not any("solution" in path for path in paths)

    def test_derivation_is_pure_no_io(self):
        instruction = "Solve the a.out binary task with extract.js."
        workspace = (
            WorkspaceEntry("a.out", len(ELF_64), _sha("a.out"), ELF_64),
            _text_entry("main.c", "int main(void) { return 0; }\n"),
        )
        first = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            deliverables=("extract.js",),
            source_revision="r1",
        ).as_dict()
        second = derive_decisive_facts(
            instruction=instruction,
            workspace=workspace,
            deliverables=("extract.js",),
            source_revision="r1",
        ).as_dict()
        assert first == second


class TestDecisiveDerivationEngineIntegration:
    def test_initial_frame_carries_decisive_header(self):
        instruction = (
            "Please help sanitize my github repository dclm of all API keys. "
            "If an AWS_ACCESS_KEY_ID is found replace the actual value with the placeholder."
        )
        workspace = (
            _text_entry("config.py", 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'),
            _text_entry("main.py", "print('ok')\n"),
        )
        engine = _engine(instruction, workspace, explicit_checks=("pytest -q",))
        frame = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=512
        )
        assert frame.kind is ContextFrameKind.INITIAL
        assert "Task-decisive context:" in frame.rendered_text
        assert "Credential class AWS_ACCESS_KEY_ID" in frame.rendered_text
        assert "config.py" in frame.rendered_text
        assert "pytest -q" in frame.rendered_text
        assert "AKIAIOSFODNN7EXAMPLE" not in frame.rendered_text

    def test_initial_frame_without_decisive_facts_keeps_default_header(self):
        instruction = "Fix the failing tests in this repository."
        workspace = (_text_entry("main.py", "print('ok')\n"),)
        engine = _engine(instruction, workspace)
        frame = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=512
        )
        assert "Task-decisive context:" not in frame.rendered_text

    def test_claims_carry_deterministic_derived_authority(self):
        instruction = (
            "I have provided a file a.out that is a compiled C binary. "
            "Write me a program extract.js that when run with node extract.js "
            "/app/a.out > out.json extracts memory values."
        )
        workspace = (
            WorkspaceEntry("a.out", len(ELF_64), _sha("a.out"), ELF_64),
            _text_entry("main.c", "int main(void) { return 0; }\n"),
        )
        engine = _engine(instruction, workspace, task_deliverables=("extract.js",))
        frame = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=512
        )
        assert frame.claim_ids
        by_claim = {m["claim_id"]: m for m in frame.claim_metadata}
        decisive_claims = [
            by_claim[cid]
            for cid in frame.claim_ids
            if by_claim.get(cid, {}).get("decisive")
        ]
        assert decisive_claims
        for claim in decisive_claims:
            assert claim["authority"] == EvidenceAuthority.DETERMINISTIC_DERIVED.value
            assert claim["materiality_reason"] == "task_decisive_evidence"
            assert claim["origin"] in {
                EvidenceOrigin.TASK_DELIVERABLE.value,
                EvidenceOrigin.PREEXISTING_REPOSITORY.value,
            }
        assert any(
            claim["origin"] == EvidenceOrigin.TASK_DELIVERABLE.value
            for claim in decisive_claims
        )
        assert any(
            claim["origin"] == EvidenceOrigin.PREEXISTING_REPOSITORY.value
            for claim in decisive_claims
        )

    def test_frame_fits_512_token_ceiling(self):
        instruction = (
            "Please help sanitize my github repository dclm of all API keys. "
            "If an AWS_ACCESS_KEY_ID is found replace the actual value with the placeholder."
        )
        workspace = tuple(
            _text_entry(f"f{i}.py", f'GITHUB_TOKEN = "x{i}"\n') for i in range(10)
        ) + (_text_entry("main.py", "print('ok')\n"),)
        engine = _engine(instruction, workspace, explicit_checks=("pytest -q",))
        frame = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=512
        )
        assert len(frame.rendered_text.split()) <= 512

    def test_decisive_facts_not_repeated_after_first_call(self):
        instruction = (
            "Please help sanitize my github repository dclm of all API keys. "
            "If an AWS_ACCESS_KEY_ID is found replace the actual value with the placeholder."
        )
        workspace = (
            _text_entry("config.py", 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'),
            _text_entry("main.py", "print('ok')\n"),
        )
        engine = _engine(instruction, workspace, explicit_checks=("pytest -q",))
        first = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=512
        )
        assert first.claim_ids
        assert engine.mark_context_dispatched(first)
        second = engine.compile_context(
            current_source_revision="source-1", provider_call=2, max_tokens=512
        )
        assert first.claim_ids != second.claim_ids
        decisive_claims = [
            m
            for m in second.claim_metadata
            if m.get("authority")
            == EvidenceAuthority.DETERMINISTIC_DERIVED.value
        ]
        assert not decisive_claims

    def test_derivation_error_degrades_to_abstention(self):
        engine = PersistentExecutionStateEngine.initialize_from_graph(
            task="Solve a task.",
            catalog=build_bootstrap_catalog(
                instruction="Solve a task.",
                evidence=_evidence(anchors=({"path": "main.py", "line": 1, "symbol": "main"},)),
                documents=(),
                structural_links=(),
                source_revision="source-1",
                graph_revision="graph-1",
                repository_complete=True,
            ),
            structural_links=(),
            present_paths=("main.py",),
            decisive=None,
        )
        engine.apply_bootstrap(
            BootstrapSelection(valid=True), current_source_revision="source-1"
        )
        frame = engine.compile_context(
            current_source_revision="source-1", provider_call=1, max_tokens=512
        )
        assert "Task-decisive context:" not in frame.rendered_text