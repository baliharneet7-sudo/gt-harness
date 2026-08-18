from __future__ import annotations

import pytest

from gt_engine.hybrid_retrieval import StructuralLink
from gt_engine.repository_context import (
    DecisionOpportunity,
    RepositoryContextEngine,
    RepositoryContextStatus,
    RepositorySnapshot,
)
from gt_engine.repository_intelligence import RepositoryEvidence


@pytest.mark.parametrize(
    ("historical_substitution", "origin", "outcome", "candidate_count"),
    (
        ("Counter -> Count", "builtin", "external", 1),
        ("Node -> Code", "program", "ambiguous", 2),
        ("Engine -> engines", "third_party", "external", 1),
        ("OSError -> Error", "stdlib", "external", 1),
        ("framework class -> project class", "framework", "external", 1),
        ("dynamic module -> global name", "program", "dynamic", 1),
        ("unverified re-export -> local symbol", "program", "reexport_unproven", 1),
        ("unresolved receiver -> global method", "program", "unresolved", 0),
        ("incomplete index -> guessed symbol", "unknown", "unknown", None),
    ),
)
def test_historical_destructive_corrections_are_terminal_abstentions(
    historical_substitution: str,
    origin: str,
    outcome: str,
    candidate_count: int | None,
) -> None:
    link = StructuralLink(
        "src/caller.py",
        "src/candidate.py",
        "CALLS",
        confidence=1.0,
        certified=False,
        source_symbol="caller",
        target_symbol=historical_substitution.split(" -> ")[-1],
        source_start_line=1,
        target_start_line=1,
        source_content_sha256="a" * 64,
        target_content_sha256="b" * 64,
        origin=origin,
        resolution_outcome=outcome,
        candidate_count=candidate_count,
    )
    evidence = RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        source_revision="source-1",
        status="source_backed",
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
    )

    result = RepositoryContextEngine().project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=1,
            eligible_call=2,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/caller.py",),
        ),
        RepositorySnapshot("source-1", "graph-1", evidence, (link,)),
    )

    assert result.status is RepositoryContextStatus.ABSTAIN
    assert result.rendered_text == ""
    assert result.rejected_edge_count == 1


def test_low_confidence_exact_receiver_is_not_laundered_into_a_call_chain() -> None:
    exact_but_weak = StructuralLink(
        "src/a.py",
        "src/b.py",
        "CALLS",
        confidence=0.94,
        certified=True,
        source_symbol="a",
        target_symbol="b",
        source_start_line=1,
        target_start_line=1,
        source_content_sha256="a" * 64,
        target_content_sha256="b" * 64,
        origin="program",
        resolution_outcome="exact",
        resolution_method="return_type",
        candidate_count=1,
        receiver_type="Service",
    )
    evidence = RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        source_revision="source-1",
        status="source_backed",
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
    )
    result = RepositoryContextEngine().project(
        DecisionOpportunity(
            "post_read_search", 1, 2, "source-1", "graph-1", anchors=("src/a.py",)
        ),
        RepositorySnapshot("source-1", "graph-1", evidence, (exact_but_weak,)),
    )

    assert result.status is RepositoryContextStatus.ABSTAIN
    assert result.rejected_edge_count == 1
