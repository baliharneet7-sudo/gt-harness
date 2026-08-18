from __future__ import annotations

from gt_engine.repository_intelligence import RepositoryEvidence
from gt_engine.semantic_evidence import (
    SemanticEvidenceBridge,
    SemanticEvidenceStatus,
)


def _healthy(**overrides: object) -> RepositoryEvidence:
    values: dict[str, object] = {
        "available": True,
        "graph_revision": "graph-1",
        "source_revision": "source-1",
        "status": "source_backed",
        "index_current": True,
        "intelligence_valid": True,
        "substrate_ready": True,
        "definitions": (
            {
                "path": "src/service.py",
                "line": 10,
                "symbol": "save_user",
                "qualified_symbol": "service.save_user",
                "signature": "def save_user(user: User) -> None",
                "language": "python",
                "origin": "program",
                "resolution_outcome": "exact",
                "provenance": ("graph_node:1", "checkout_source"),
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
        ),
        "callers": (
            {
                "caller": "handle_request",
                "caller_path": "src/api.py",
                "caller_line": 22,
                "target": "save_user",
                "target_path": "src/service.py",
                "target_line": 10,
                "resolution_method": "lsp_verified",
                "confidence": 1.0,
                "trust_tier": "CERTIFIED",
                "candidate_count": 1,
                "semantics": "graph_recorded",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
                "language": "python",
                "target_language": "python",
                "origin": "program",
                "resolution_outcome": "exact",
            },
        ),
        "references": (
            {
                "path": "tests/test_service.py",
                "line": 18,
                "symbol": "save_user",
                "target": "save_user",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
                "is_test": True,
                "language": "python",
                "origin": "program",
                "resolution_outcome": "exact",
                "provenance": ("graph_edge:1", "lsp_verified"),
            },
        ),
    }
    values.update(overrides)
    return RepositoryEvidence(**values)


def test_bridge_composes_definition_signature_caller_and_test_without_extra_query() -> None:
    result = SemanticEvidenceBridge(max_items=8, max_tokens=160).compose(
        _healthy(), source_revision="source-1", graph_revision="graph-1"
    )

    assert result.status is SemanticEvidenceStatus.DELIVER
    assert "Definition src/service.py:10 save_user" in result.rendered_text
    assert "def save_user(user: User) -> None" in result.rendered_text
    assert "Caller src/api.py:22 handle_request calls save_user" in result.rendered_text
    assert "Test tests/test_service.py:18 save_user" in result.rendered_text
    assert len(result.claim_ids) == len(set(result.claim_ids))
    assert result.item_count == 3


def test_bridge_refuses_stale_or_unhealthy_repository_evidence() -> None:
    stale = SemanticEvidenceBridge().compose(
        _healthy(), source_revision="source-2", graph_revision="graph-1"
    )
    unavailable = SemanticEvidenceBridge().compose(
        _healthy(substrate_ready=False), source_revision="source-1", graph_revision="graph-1"
    )

    assert stale.status is SemanticEvidenceStatus.ABSTAIN
    assert "source_revision_mismatch" in stale.reason_codes
    assert unavailable.status is SemanticEvidenceStatus.ABSTAIN
    assert "repository_substrate_unavailable" in unavailable.reason_codes


def test_bridge_drops_ambiguous_callers_but_keeps_certified_definition() -> None:
    result = SemanticEvidenceBridge().compose(
        _healthy(
            callers=(
                {
                    "caller": "maybe",
                    "caller_path": "src/api.py",
                    "caller_line": 22,
                    "target": "save_user",
                    "target_path": "src/service.py",
                    "target_line": 10,
                    "confidence": 0.85,
                    "trust_tier": "HEURISTIC",
                    "candidate_count": 2,
                    "semantics": "graph_recorded",
                },
            )
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert result.status is SemanticEvidenceStatus.DELIVER
    assert "Definition src/service.py:10 save_user" in result.rendered_text
    assert "maybe" not in result.rendered_text
    assert "ambiguous_caller_rejected" in result.reason_codes


def test_bridge_abstains_when_only_weak_or_incomplete_facts_exist() -> None:
    result = SemanticEvidenceBridge().compose(
        _healthy(
            definitions=({"path": "src/service.py", "symbol": "save_user"},),
            callers=(),
            references=(),
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert result.status is SemanticEvidenceStatus.ABSTAIN
    assert "no_certified_semantic_evidence" in result.reason_codes


def test_malformed_numeric_evidence_abstains_instead_of_raising() -> None:
    result = SemanticEvidenceBridge().compose(
        _healthy(
            definitions=({"path": "src/a.py", "line": "bad", "symbol": "A"},),
            callers=(
                {
                    "caller_path": "src/b.py",
                    "caller_line": "bad",
                    "caller": "b",
                    "target": "A",
                    "trust_tier": "CERTIFIED",
                    "candidate_count": "bad",
                    "semantics": "graph_recorded",
                    "semantic_certainty": "bad",
                    "retrieval_relevance": "bad",
                },
            ),
            references=(),
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert result.status is SemanticEvidenceStatus.ABSTAIN
    assert result.items == ()


def test_bridge_budget_is_whole_item_and_deterministic() -> None:
    bridge = SemanticEvidenceBridge(max_items=1, max_tokens=32)
    first = bridge.compose(_healthy(), source_revision="source-1", graph_revision="graph-1")
    second = bridge.compose(_healthy(), source_revision="source-1", graph_revision="graph-1")

    assert first == second
    assert first.status is SemanticEvidenceStatus.DELIVER
    assert first.item_count == 1
    assert first.truncated_count == 2
    assert "Definition" in first.rendered_text


def test_semantic_claim_identity_is_stable_across_unrelated_source_revisions() -> None:
    bridge = SemanticEvidenceBridge()
    first = bridge.compose(_healthy(), source_revision="source-1", graph_revision="graph-1")
    second = bridge.compose(
        _healthy(source_revision="source-2", graph_revision="graph-2"),
        source_revision="source-2",
        graph_revision="graph-2",
    )

    assert first.claim_ids == second.claim_ids


def test_bridge_does_not_redeliver_previously_delivered_claims() -> None:
    bridge = SemanticEvidenceBridge()
    first = bridge.compose(_healthy(), source_revision="source-1", graph_revision="graph-1")
    second = bridge.compose(
        _healthy(),
        source_revision="source-1",
        graph_revision="graph-1",
        delivered_claim_ids=frozenset(first.claim_ids),
    )

    assert second.status is SemanticEvidenceStatus.ABSTAIN
    assert second.items == ()
    assert "semantic_evidence_already_delivered" in second.reason_codes


def test_reference_path_substring_does_not_invent_test_role() -> None:
    result = SemanticEvidenceBridge().compose(
        _healthy(
            references=(
                {
                    "path": "src/contest.py",
                    "line": 18,
                    "symbol": "save_user",
                    "target": "save_user",
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                    "is_test": False,
                    "origin": "program",
                    "resolution_outcome": "exact",
                    "provenance": ("graph_edge:1", "lsp_verified"),
                },
            )
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert "Reference src/contest.py:18 save_user" in result.rendered_text
    assert "Test src/contest.py" not in result.rendered_text


def test_bridge_preserves_return_type_and_certified_property_provenance() -> None:
    result = SemanticEvidenceBridge(max_items=8, max_tokens=240).compose(
        _healthy(
            definitions=(
                {
                    "path": "src/service.py",
                    "line": 10,
                    "symbol": "save_user",
                    "signature": "def save_user(user)",
                    "return_type": "User",
                    "origin": "program",
                    "resolution_outcome": "exact",
                    "provenance": ("graph_node:1", "checkout_source"),
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                },
            ),
            semantic_properties=(
                {
                    "path": "src/service.py",
                    "line": 10,
                    "symbol": "save_user",
                    "kind": "param",
                    "value": "user: User [required]",
                    "confidence": 1.0,
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                    "trust_tier": "CERTIFIED",
                    "evidence_method": "tree_sitter_exact",
                    "verification_status": "verified",
                    "property_id": "property-1",
                    "origin": "program",
                    "resolution_outcome": "exact",
                },
            ),
            callers=(),
            references=(),
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert "def save_user(user) -> User" in result.rendered_text
    assert "Param src/service.py:10 save_user: user: User [required]" in result.rendered_text
    property_item = next(item for item in result.items if item.kind == "property")
    assert "evidence_method:tree_sitter_exact" in property_item.provenance


def test_bridge_rejects_property_without_certified_origin() -> None:
    result = SemanticEvidenceBridge().compose(
        _healthy(
            definitions=(),
            callers=(),
            references=(),
            semantic_properties=(
                {
                    "path": "src/service.py",
                    "line": 10,
                    "symbol": "save_user",
                    "kind": "param",
                    "value": "user: MaybeUser",
                    "confidence": 1.0,
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                    "trust_tier": "HEURISTIC",
                    "evidence_method": "global_guess",
                    "origin": "program",
                    "resolution_outcome": "ambiguous",
                },
            ),
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert result.status is SemanticEvidenceStatus.ABSTAIN
    assert "weak_semantic_property_rejected" in result.reason_codes


def test_bridge_rejects_ambiguous_definition_and_reference_origins() -> None:
    result = SemanticEvidenceBridge().compose(
        _healthy(
            definitions=(
                {
                    "path": "src/service.py",
                    "line": 10,
                    "symbol": "save_user",
                    "origin": "program",
                    "resolution_outcome": "ambiguous",
                    "provenance": ("name_match",),
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                },
            ),
            callers=(),
            references=(
                {
                    "path": "src/api.py",
                    "line": 22,
                    "symbol": "save_user",
                    "origin": "unknown",
                    "resolution_outcome": "unknown",
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                },
            ),
        ),
        source_revision="source-1",
        graph_revision="graph-1",
    )

    assert result.status is SemanticEvidenceStatus.ABSTAIN
    assert "ambiguous_definition_rejected" in result.reason_codes
    assert "ambiguous_reference_rejected" in result.reason_codes
