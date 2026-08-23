from __future__ import annotations

from gt_engine.hybrid_repository import HybridRepository
from gt_engine.hybrid_retrieval import (
    EvidenceOrigin,
    RepositoryDocument,
    RetrievalIntent,
    StructuralLink,
)
from gt_engine.repository_context_compiler import (
    ContextCompileRequest,
    ContextStatus,
    RepositoryContextCompiler,
)


def _document(path: str, symbol: str, text: str) -> RepositoryDocument:
    return RepositoryDocument(
        path=path,
        symbol=symbol,
        text=text,
        start_line=1,
        end_line=max(1, len(text.splitlines())),
        provenance=("graph_node",),
        origin=EvidenceOrigin.PREEXISTING_REPOSITORY,
        origin_revision="source-1",
    )


def _repository(*links: StructuralLink) -> HybridRepository:
    return HybridRepository(
        documents=(
            _document(
                "gt_engine/hybrid_retrieval.py",
                "HybridRetriever",
                "class HybridRetriever:\n    def retrieve(self, state): ...",
            ),
            _document(
                "src/groundtruth/pretask/hybrid.py",
                "lexical_file_search",
                "def lexical_file_search(query): ...",
            ),
            _document(
                ".github/workflows/arb_gt_retrieval.yml",
                "arb_gt_retrieval",
                "name: retrieval benchmark",
            ),
            _document(
                "gt_harness/treatments.py",
                "GroundTruthTreatment",
                "class GroundTruthTreatment: ...",
            ),
            _document(
                "tests/test_product_treatments.py",
                "test_groundtruth_treatment",
                "def test_groundtruth_treatment(): ...",
            ),
        ),
        structural_links=links,
        source_revision="source-1",
        complete=True,
        reason_codes=(),
        source_file_count=5,
        document_chars=500,
    )


def _request(task: str) -> ContextCompileRequest:
    return ContextCompileRequest(
        task=task,
        source_revision="source-1",
        graph_revision="graph-1",
        intent=RetrievalIntent.IMPLEMENTATION_CONTEXT,
        token_budget=1_000,
        character_budget=4_000,
    )


def test_compiler_prefers_exact_production_symbol_over_legacy_and_workflow() -> None:
    packet = RepositoryContextCompiler().compile(
        _repository(),
        _request("Wire HybridRetriever into GroundTruthTreatment"),
    )

    assert packet.status is ContextStatus.READY
    assert packet.primary_edit_targets[0].path == "gt_engine/hybrid_retrieval.py"
    assert packet.primary_edit_targets[0].symbol == "HybridRetriever"
    assert all(
        target.path != "src/groundtruth/pretask/hybrid.py"
        for target in packet.primary_edit_targets
    )
    assert all(".github/workflows" not in target.path for target in packet.primary_edit_targets)


def test_compiler_does_not_treat_issue_verbs_as_symbol_anchors() -> None:
    repository = _repository()
    repository = HybridRepository(
        documents=(
            *_repository().documents,
            _document("noise.py", "Change", "class Change: ..."),
            _document("app.py", "answer", "def answer(): return 42"),
        ),
        structural_links=repository.structural_links,
        source_revision=repository.source_revision,
        complete=repository.complete,
        reason_codes=repository.reason_codes,
        source_file_count=repository.source_file_count + 2,
        document_chars=repository.document_chars + 64,
    )

    packet = RepositoryContextCompiler().compile(
        repository,
        _request("Change answer without breaking callers"),
    )

    assert packet.primary_edit_targets[0].symbol == "answer"
    assert all(item.symbol != "Change" for item in packet.primary_edit_targets)


def test_compiler_rejects_unverified_full_confidence_relationship() -> None:
    unsafe = StructuralLink(
        source_path="gt_harness/treatments.py",
        target_path="gt_engine/hybrid_retrieval.py",
        relation="CALLS",
        confidence=1.0,
        certified=True,
        verification_status="unverified",
        source_symbol="GroundTruthTreatment",
        target_symbol="HybridRetriever",
        source_start_line=1,
        target_start_line=1,
        source_content_sha256="a" * 64,
        target_content_sha256="b" * 64,
        source_evidence_origin="preexisting_repository",
        target_evidence_origin="preexisting_repository",
        origin="program",
        resolution_outcome="exact",
        resolution_method="exact_symbol",
        candidate_count=1,
    )

    packet = RepositoryContextCompiler().compile(
        _repository(unsafe),
        _request("Wire HybridRetriever into GroundTruthTreatment"),
    )

    assert packet.execution_paths == ()
    assert packet.change_surface == ()
    assert "unverified_edge_rejected" in packet.uncertainties
    assert all(item.verification_status == "verified" for item in packet.evidence_items)


def test_compiler_ignores_relationships_for_unrelated_symbols_in_anchor_file() -> None:
    unrelated = StructuralLink(
        source_path="gt_engine/hybrid_retrieval.py",
        target_path="gt_harness/treatments.py",
        relation="CALLS",
        confidence=1.0,
        certified=True,
        verification_status="verified",
        source_symbol="retrieval_query_terms",
        target_symbol="BareTreatment",
        source_start_line=10,
        target_start_line=10,
        source_content_sha256="a" * 64,
        target_content_sha256="b" * 64,
        source_evidence_origin="preexisting_repository",
        target_evidence_origin="preexisting_repository",
        origin="program",
        resolution_outcome="exact",
        resolution_method="exact_symbol",
        candidate_count=1,
    )

    packet = RepositoryContextCompiler().compile(
        _repository(unrelated),
        _request("Wire HybridRetriever into GroundTruthTreatment"),
    )

    assert all(item.symbol != "BareTreatment" for item in packet.evidence_items)
    assert packet.execution_paths == ()
    assert packet.change_surface == ()
    assert "unverified_edge_rejected" not in packet.uncertainties


def test_compiler_emits_certified_process_impact_and_affected_test() -> None:
    call = StructuralLink(
        source_path="gt_harness/treatments.py",
        target_path="gt_engine/hybrid_retrieval.py",
        relation="CALLS",
        confidence=1.0,
        certified=True,
        verification_status="verified",
        source_symbol="GroundTruthTreatment",
        target_symbol="HybridRetriever",
        source_start_line=1,
        target_start_line=1,
        source_content_sha256="a" * 64,
        target_content_sha256="b" * 64,
        source_evidence_origin="preexisting_repository",
        target_evidence_origin="preexisting_repository",
        origin="program",
        resolution_outcome="exact",
        resolution_method="exact_symbol",
        candidate_count=1,
    )
    tested_by = StructuralLink(
        source_path="gt_engine/hybrid_retrieval.py",
        target_path="tests/test_product_treatments.py",
        relation="TESTED_BY",
        confidence=1.0,
        certified=True,
        verification_status="verified",
        source_symbol="HybridRetriever",
        target_symbol="test_groundtruth_treatment",
        source_start_line=1,
        target_start_line=1,
        source_content_sha256="b" * 64,
        target_content_sha256="c" * 64,
        source_evidence_origin="preexisting_repository",
        target_evidence_origin="preexisting_repository",
        origin="program",
        resolution_outcome="exact",
        resolution_method="exact_symbol",
        candidate_count=1,
    )

    packet = RepositoryContextCompiler().compile(
        _repository(call, tested_by),
        _request("Wire HybridRetriever into GroundTruthTreatment"),
    )

    assert packet.execution_paths
    assert packet.change_surface
    assert packet.affected_tests == ("tests/test_product_treatments.py",)
    assert all(item.source_revision == "source-1" for item in packet.evidence_items)
    assert all(item.graph_revision == "graph-1" for item in packet.evidence_items)


def test_compiler_deduplicates_transitive_copy_of_direct_relationship() -> None:
    common = {
        "source_path": "gt_harness/treatments.py",
        "target_path": "gt_engine/hybrid_retrieval.py",
        "confidence": 1.0,
        "certified": True,
        "verification_status": "verified",
        "source_symbol": "GroundTruthTreatment",
        "target_symbol": "HybridRetriever",
        "source_start_line": 1,
        "target_start_line": 1,
        "source_content_sha256": "a" * 64,
        "target_content_sha256": "b" * 64,
        "source_evidence_origin": "preexisting_repository",
        "target_evidence_origin": "preexisting_repository",
        "origin": "program",
        "resolution_outcome": "exact",
        "resolution_method": "exact_symbol",
        "candidate_count": 1,
    }
    direct = StructuralLink(relation="CALLS", **common)
    transitive = StructuralLink(relation="CALLS_TRANSITIVE", **common)

    packet = RepositoryContextCompiler().compile(
        _repository(transitive, direct),
        _request("Wire HybridRetriever into GroundTruthTreatment"),
    )

    relationships = [
        item for item in packet.evidence_items if item.kind == "relationship"
    ]
    assert len(relationships) == 1
    assert relationships[0].relation == "CALLS"
