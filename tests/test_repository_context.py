from __future__ import annotations

from dataclasses import replace

from gt_engine.hybrid_retrieval import StructuralLink
from gt_engine.repository_context import (
    DecisionOpportunity,
    RepositoryContextEngine,
    RepositoryContextStatus,
    RepositorySnapshot,
    RetrievalRankHint,
    SymbolRef,
)
from gt_engine.repository_intelligence import RepositoryEvidence


def _link(
    source_path: str,
    target_path: str,
    relation: str,
    source_symbol: str,
    target_symbol: str,
    **metadata,
) -> StructuralLink:
    return StructuralLink(
        source_path=source_path,
        target_path=target_path,
        relation=relation,
        confidence=1.0,
        certified=True,
        source_symbol=source_symbol,
        target_symbol=target_symbol,
        source_start_line=1,
        target_start_line=1,
        source_content_sha256="a" * 64,
        target_content_sha256="b" * 64,
        source_evidence_origin="preexisting_repository",
        target_evidence_origin="preexisting_repository",
        origin="program",
        resolution_outcome="exact",
        provenance=("resolution_method:lsp_verified", "candidate_count:1"),
        resolution_method=str(metadata.pop("resolution_method", "lsp_verified")),
        candidate_count=metadata.pop("candidate_count", 1),
        **metadata,
    )


def _evidence() -> RepositoryEvidence:
    return RepositoryEvidence(
        available=True,
        graph_revision="graph-1",
        source_revision="source-1",
        status="source_backed",
        index_current=True,
        intelligence_valid=True,
        substrate_ready=True,
        definitions=(
            {
                "path": "src/core.py",
                "line": 1,
                "symbol": "work",
                "signature": "def work() -> int",
                "origin": "program",
                "resolution_outcome": "exact",
                "provenance": ("graph_node:1", "checkout_source"),
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
        ),
        callers=(),
        references=(),
    )


def _snapshot(*links: StructuralLink) -> RepositorySnapshot:
    return RepositorySnapshot(
        source_revision="source-1",
        graph_revision="graph-1",
        repository_evidence=_evidence(),
        structural_links=links,
        path_origins=(
            ("src/core.py", "preexisting_repository"),
            ("src/entry.py", "preexisting_repository"),
            ("src/helper.py", "preexisting_repository"),
            ("tests/test_core.py", "preexisting_repository"),
        ),
    )


def test_semantic_call_evidence_requires_preexisting_source_and_target() -> None:
    evidence = replace(
        _evidence(),
        callers=(
            {
                "caller": "run",
                "caller_path": "src/entry.py",
                "target": "work",
                "target_path": "src/core.py",
            },
        ),
        references=(
            {
                "path": "src/entry.py",
                "symbol": "work",
                "target": "work",
                "target_path": "src/core.py",
            },
        ),
    )
    origins = (
        ("src/entry.py", "preexisting_repository"),
        ("src/core.py", "preexisting_repository"),
    )

    accepted = RepositoryContextEngine._preexisting_semantic_evidence(
        evidence, origins
    )
    rejected = RepositoryContextEngine._preexisting_semantic_evidence(
        evidence,
        (
            ("src/entry.py", "preexisting_repository"),
            ("src/core.py", "model_authored"),
        ),
    )

    assert len(accepted.callers) == 1
    assert len(accepted.references) == 1
    assert rejected.callers == ()
    assert rejected.references == ()


def test_semantic_filter_supports_independent_path_and_symbol_anchors() -> None:
    evidence = replace(
        _evidence(),
        definitions=(
            *_evidence().definitions,
            {
                "path": "src/core.py",
                "line": 8,
                "symbol": "other",
                "signature": "def other() -> int",
            },
            {
                "path": "src/secondary.py",
                "line": 1,
                "symbol": "work",
                "signature": "def work() -> int",
            },
        ),
    )
    origins = (
        ("src/core.py", "preexisting_repository"),
        ("src/secondary.py", "preexisting_repository"),
    )

    path_only = RepositoryContextEngine._preexisting_semantic_evidence(
        evidence,
        origins,
        anchor_paths=frozenset({"src/core.py"}),
    )
    symbol_only = RepositoryContextEngine._preexisting_semantic_evidence(
        evidence,
        origins,
        anchor_symbols=frozenset({"work"}),
    )

    assert {(row["path"], row["symbol"]) for row in path_only.definitions} == {
        ("src/core.py", "work"),
        ("src/core.py", "other"),
    }
    assert {(row["path"], row["symbol"]) for row in symbol_only.definitions} == {
        ("src/core.py", "work"),
        ("src/secondary.py", "work"),
    }


def test_project_returns_directed_execution_view_and_diff_impact_bundle() -> None:
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        _snapshot(
            _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
            _link("src/core.py", "src/helper.py", "CALLS", "work", "helper"),
            _link(
                "src/core.py",
                "tests/test_core.py",
                "ASSERTED_BY",
                "work",
                "test_work",
            ),
        ),
    )

    assert result.status is RepositoryContextStatus.DELIVER
    assert {item.surface for item in result.contributions} == {
        "repository_semantic",
        "repository_process",
    }
    assert "src/entry.py#run -> src/core.py#work -> src/helper.py#helper" in result.rendered_text
    assert "caller depth 1: src/entry.py#run calls src/core.py#work" in result.rendered_text
    assert "test: tests/test_core.py#test_work asserts src/core.py#work" in result.rendered_text
    assert result.execution_views[0].steps[0].source.symbol == "run"
    assert result.execution_views[0].steps[0].target.symbol == "work"
    metadata = result.contributions[0].claim_metadata
    assert metadata
    assert {row["origin"] for row in metadata} == {"preexisting_repository"}
    assert result.contributions[0].unsafe_provider_origins == ()


def test_process_composition_is_anchor_centered_and_globally_bounded() -> None:
    unrelated = tuple(
        _link(
            f"src/root_{root}.py" if depth == 0 else f"src/n_{root}_{depth}.py",
            f"src/n_{root}_{depth + 1}.py",
            "CALLS",
            f"f_{root}_{depth}",
            f"f_{root}_{depth + 1}",
        )
        for root in range(80)
        for depth in range(20)
    )
    relevant = (
        _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
        _link("src/core.py", "tests/test_core.py", "CALLS", "work", "test_work"),
    )
    engine = RepositoryContextEngine(
        max_tokens=320,
        max_depth=4,
        max_edge_expansions=64,
    )

    result = engine.project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        _snapshot(*unrelated, *relevant),
    )

    assert result.process_coverage["paths_considered"] <= 64
    assert result.process_coverage["anchor_nodes_considered"] == 1
    assert result.execution_views
    assert "src/entry.py#run -> src/core.py#work -> tests/test_core.py#test_work" in (
        result.execution_views[0].rendered
    )


def test_post_read_search_suppresses_same_file_process_and_impact_echoes() -> None:
    """A read already exposes local bytes; local graph facts add no information."""

    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_read_search",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_symbols=("work",),
        ),
        _snapshot(
            _link("src/core.py", "src/core.py", "CALLS", "run", "work"),
        ),
    )

    assert result.execution_views == ()
    assert result.impact_facts == ()
    assert "Execution" not in result.rendered_text
    assert "caller depth" not in result.rendered_text
    assert "local_observation_already_represented" in result.reason_codes


def test_resolved_convention_requires_agreeing_type_caller_and_test_evidence() -> None:
    evidence = replace(
        _evidence(),
        definitions=(
            {
                **_evidence().definitions[0],
                "signature": "def work(value: int) -> int",
                "return_type": "int",
            },
        ),
    )
    snapshot = replace(
        _snapshot(
            _link(
                "src/entry.py",
                "src/core.py",
                "CALLS",
                "run",
                "work",
                target_return_type="int",
            ),
            _link(
                "src/core.py",
                "tests/test_core.py",
                "ASSERTED_BY",
                "work",
                "test_work",
            ),
        ),
        repository_evidence=evidence,
    )

    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_read_search",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_symbols=("work",),
        ),
        snapshot,
    )

    assert len(result.resolved_conventions) == 1
    convention = result.resolved_conventions[0]
    assert convention.resolved_type == "int"
    assert convention.callers == ("src/entry.py#run",)
    assert convention.tests == ("tests/test_core.py#test_work",)
    assert "Resolved convention (exact)" in result.rendered_text

    conflicting_snapshot = replace(
        snapshot,
        structural_links=(
            replace(snapshot.structural_links[0], target_return_type="str"),
            snapshot.structural_links[1],
        ),
    )
    conflicting = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_read_search",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_symbols=("work",),
        ),
        conflicting_snapshot,
    )
    assert conflicting.resolved_conventions == ()
    assert conflicting.convention_coverage["conflicting_type_evidence"] == 1


def test_retrieval_rank_only_reorders_certified_process_facts() -> None:
    snapshot = replace(
        _snapshot(
            _link("src/a.py", "src/core.py", "CALLS", "run_a", "work"),
            _link("src/b.py", "src/core.py", "CALLS", "run_b", "work"),
        ),
        path_origins=(
            ("src/a.py", "preexisting_repository"),
            ("src/b.py", "preexisting_repository"),
            ("src/core.py", "preexisting_repository"),
        ),
        retrieval_rank_hints=(
            RetrievalRankHint("src/b.py", 0.9, ("dense", "bm25")),
            RetrievalRankHint("src/a.py", 0.1, ("lexical",)),
        ),
    )

    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        snapshot,
    )

    process = next(
        contribution
        for contribution in result.contributions
        if contribution.surface == "repository_process"
    )
    assert process.payload.index("src/b.py#run_b") < process.payload.index("src/a.py#run_a")
    assert result.process_coverage["retrieval_rank_hints"] == 2


def test_retrieval_rank_hint_never_creates_delivery_authority() -> None:
    snapshot = replace(
        _snapshot(),
        retrieval_rank_hints=(
            RetrievalRankHint("src/unproven.py", 1.0, ("dense", "lexical")),
        ),
    )

    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/unproven.py",),
        ),
        snapshot,
    )

    assert all(item.surface != "repository_process" for item in result.contributions)


def test_project_preserves_authority_when_packing_semantic_and_process_surfaces() -> None:
    snapshot = replace(
        _snapshot(
            _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
            _link("src/core.py", "src/helper.py", "CALLS", "work", "helper"),
            _link(
                "src/core.py",
                "tests/test_core.py",
                "ASSERTED_BY",
                "work",
                "test_work",
            ),
        ),
        diagnostics=("src/core.py:4: expected int, got str",),
        validation_checks=("pytest tests/test_core.py -q",),
    )
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_diagnostic",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        snapshot,
    )

    by_surface = {item.surface: item for item in result.contributions}
    assert set(by_surface) == {
        "repository_context",
        "repository_semantic",
        "repository_process",
    }
    assert by_surface["repository_context"].priority == 4
    assert by_surface["repository_semantic"].priority == 6
    assert by_surface["repository_process"].priority == 18
    assert by_surface["repository_context"].critical
    assert "Observed diagnostic" in by_surface["repository_context"].payload
    assert "declared check" in by_surface["repository_context"].payload
    assert "Execution" in by_surface["repository_process"].payload
    assert result.process_coverage["returned_views"] == len(result.execution_views)
    assert result.process_coverage["profile_id"] == "gt.certified_process.v1"
    assert result.process_coverage["max_depth"] > 0


def test_process_surface_cannot_displace_critical_diagnostic_under_budget() -> None:
    snapshot = replace(
        _snapshot(
            _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
            _link("src/core.py", "src/helper.py", "CALLS", "work", "helper"),
            _link(
                "src/core.py",
                "tests/test_core.py",
                "ASSERTED_BY",
                "work",
                "test_work",
            ),
        ),
        diagnostics=("src/core.py:4: concrete failure",),
        validation_checks=("pytest tests/test_core.py -q",),
    )
    result = RepositoryContextEngine(max_tokens=30).project(
        DecisionOpportunity(
            kind="post_diagnostic",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        snapshot,
    )

    assert "Observed diagnostic" in result.rendered_text
    assert "Execution (lower bound" not in result.rendered_text
    assert result.process_coverage["omitted_for_budget"] > 0


def test_project_never_turns_reverse_traversal_into_an_execution_path() -> None:
    result = RepositoryContextEngine(max_tokens=256).project(
        DecisionOpportunity(
            kind="post_read_search",
            evidence_action=1,
            eligible_call=2,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
        ),
        _snapshot(
            _link("src/core.py", "src/left.py", "CALLS", "work", "left"),
            _link("src/core.py", "src/right.py", "CALLS", "work", "right"),
        ),
    )

    assert "src/left.py#left -> src/core.py#work" not in result.rendered_text
    assert "src/right.py#right -> src/core.py#work" not in result.rendered_text


def test_project_abstains_when_only_unknown_or_ambiguous_links_exist() -> None:
    ambiguous = _link("src/a.py", "src/core.py", "CALLS", "a", "work")
    ambiguous = replace(
        ambiguous,
        certified=False,
        resolution_outcome="ambiguous",
    )
    result = RepositoryContextEngine().project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=1,
            eligible_call=2,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=RepositoryEvidence(
                available=True,
                graph_revision="graph-1",
                source_revision="source-1",
                status="source_backed",
                index_current=True,
                intelligence_valid=True,
                substrate_ready=True,
            ),
            structural_links=(ambiguous,),
        ),
    )

    assert result.status is RepositoryContextStatus.ABSTAIN
    assert result.contributions == ()
    assert "no_certified_repository_context" in result.reason_codes
    assert result.rejected_edge_count == 1


def test_model_authored_endpoints_remain_controller_only() -> None:
    link = replace(
        _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
        target_evidence_origin="model_authored",
    )
    result = RepositoryContextEngine().project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=1,
            eligible_call=2,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=_evidence(),
            structural_links=(link,),
            path_origins=(("src/core.py", "model_authored"),),
        ),
    )

    assert result.status is RepositoryContextStatus.ABSTAIN
    assert result.claim_ids == ()
    assert result.rejected_edge_count == 1


def test_rejected_non_call_impact_edges_are_accounted() -> None:
    ambiguous_test = replace(
        _link(
            "src/core.py",
            "tests/test_core.py",
            "ASSERTED_BY",
            "work",
            "test_work",
        ),
        certified=False,
        resolution_outcome="ambiguous",
    )
    result = RepositoryContextEngine().project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=1,
            eligible_call=2,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        _snapshot(ambiguous_test),
    )

    assert result.status is RepositoryContextStatus.DELIVER
    assert result.rejected_edge_count == 1
    assert "test_core.py" not in result.rendered_text


def test_project_deduplicates_semantic_and_relational_claims_across_calls() -> None:
    engine = RepositoryContextEngine(max_tokens=256)
    opportunity = DecisionOpportunity(
        kind="post_read_search",
        evidence_action=1,
        eligible_call=2,
        source_revision="source-1",
        graph_revision="graph-1",
        anchors=("src/core.py",),
    )
    snapshot = _snapshot(
        _link("src/entry.py", "src/core.py", "CALLS", "run", "work")
    )
    first = engine.project(opportunity, snapshot)
    second = engine.project(
        opportunity,
        snapshot,
        delivered_claim_ids=frozenset(first.claim_ids),
    )

    assert first.status is RepositoryContextStatus.DELIVER
    assert second.status is RepositoryContextStatus.ABSTAIN
    assert "repository_context_already_delivered" in second.reason_codes


def test_project_classifies_certified_route_entry_and_preserves_receiver_chain() -> None:
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_read_search",
            evidence_action=1,
            eligible_call=2,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/routes.py",),
        ),
        _snapshot(
            _link(
                "src/routes.py",
                "src/routes.py",
                "HANDLES_ROUTE",
                "get_user",
                "routes",
                route="/users/{id}",
            ),
            _link(
                "src/routes.py",
                "src/service.py",
                "CALLS",
                "get_user",
                "load_user",
                receiver_type="UserService",
                target_return_type="User",
            ),
        ),
    )

    assert result.status is RepositoryContextStatus.DELIVER
    assert result.execution_views[0].entry_kind == "route_entry"
    assert result.execution_views[0].route == "/users/{id}"
    assert "receiver=UserService" in result.rendered_text
    assert "route=/users/{id}" in result.rendered_text


def test_project_binds_changed_path_to_exact_symbols_and_selects_impacted_check() -> None:
    evidence = replace(
        _evidence(),
        project_checks=("pytest tests/test_core.py -q",),
    )
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/core.py",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=evidence,
            structural_links=(
                _link(
                    "src/core.py",
                    "tests/test_core.py",
                    "ASSERTED_BY",
                    "work",
                    "test_work",
                ),
            ),
            validation_checks=evidence.project_checks,
        ),
    )

    assert result.impact_facts[0].source.symbol == "work"
    assert result.validation_facts[0].impacted_path == "tests/test_core.py"
    assert "pytest tests/test_core.py -q" in result.rendered_text


def test_changed_symbol_composes_advisory_caller_test_and_declared_check() -> None:
    evidence = replace(
        _evidence(), project_checks=("pytest tests/test_core.py -q",)
    )
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=evidence,
            structural_links=(
                _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
                _link(
                    "src/core.py",
                    "tests/test_core.py",
                    "ASSERTED_BY",
                    "work",
                    "test_work",
                ),
            ),
            validation_checks=evidence.project_checks,
        ),
    )

    assert len(result.coupled_obligations) == 1
    coupled = result.coupled_obligations[0]
    assert coupled.blocking is False
    assert coupled.changed == SymbolRef("src/core.py", "work", 1)
    assert coupled.dependent_paths == ("src/entry.py",)
    assert coupled.test_paths == ("tests/test_core.py",)
    assert coupled.declared_check == "pytest tests/test_core.py -q"
    projected_constituents = {
        *(fact.claim_id for fact in result.impact_facts),
        *(fact.claim_id for fact in result.validation_facts),
    }
    assert set(coupled.constituent_claim_ids) <= projected_constituents
    assert "Coupled verification surface" in result.rendered_text
    assert "must edit" not in result.rendered_text.lower()
    assert "Impact caller" not in result.rendered_text
    assert "Validate impacted path" not in result.rendered_text


def test_project_delivers_only_concrete_observed_diagnostic_for_current_anchor() -> None:
    result = RepositoryContextEngine(max_tokens=256).project(
        DecisionOpportunity(
            kind="post_diagnostic",
            evidence_action=3,
            eligible_call=4,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=replace(_evidence(), definitions=()),
            structural_links=(),
            diagnostics=(
                "src/core.py:12:5: error: incompatible return type",
                "src/other.py:4: error: unrelated",
            ),
        ),
    )

    assert len(result.diagnostic_facts) == 1
    assert result.diagnostic_facts[0].path == "src/core.py"
    diagnostic_id = result.diagnostic_facts[0].claim_id
    diagnostic_metadata = next(
        row
        for row in result.contributions[0].claim_metadata
        if row["claim_id"] == diagnostic_id
    )
    assert diagnostic_metadata["origin"] == "execution_observation"
    assert diagnostic_metadata["authority"] == "execution_observation"
    assert "incompatible return type" in result.rendered_text
    assert "unrelated" not in result.rendered_text


def test_project_matches_absolute_diagnostic_to_repository_relative_anchor() -> None:
    result = RepositoryContextEngine(max_tokens=256).project(
        DecisionOpportunity(
            kind="post_diagnostic",
            evidence_action=3,
            eligible_call=4,
            source_revision="source-1",
            graph_revision="graph-1",
            anchors=("src/core.py",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=replace(_evidence(), definitions=()),
            structural_links=(),
            diagnostics=("/app/src/core.py:12:5: error: incompatible return type",),
        ),
    )

    assert len(result.diagnostic_facts) == 1
    assert result.diagnostic_facts[0].path == "src/core.py"


def test_project_computes_reverse_dependency_impact_from_changed_target() -> None:
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/service.py",),
            changed_symbols=("get_user",),
        ),
        _snapshot(
            _link(
                "src/client.py",
                "src/service.py",
                "API_CALL",
                "fetch_user",
                "get_user",
            ),
            _link(
                "src/__init__.py",
                "src/service.py",
                "RE_EXPORTS",
                "service_exports",
                "get_user",
            ),
        ),
    )

    assert "API consumer: src/client.py#fetch_user consumes src/service.py#get_user" in (
        result.rendered_text
    )
    assert "re-export: src/__init__.py#service_exports exports src/service.py#get_user" in (
        result.rendered_text
    )


def test_projection_receipts_only_facts_that_fit_the_visible_budget() -> None:
    result = RepositoryContextEngine(max_tokens=28).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        _snapshot(
            _link("src/entry.py", "src/core.py", "CALLS", "run", "work"),
            _link(
                "src/core.py",
                "tests/test_core.py",
                "ASSERTED_BY",
                "work",
                "test_work",
            ),
        ),
    )

    assert result.status is RepositoryContextStatus.DELIVER
    assert result.truncated_count > 0
    semantic_items = (
        result.semantic_evidence.items if result.semantic_evidence else ()
    )
    assert set(result.claim_ids) == {
        *(item.claim_id for item in semantic_items),
        *(view.view_id for view in result.execution_views),
        *(fact.claim_id for fact in result.impact_facts),
        *(fact.claim_id for fact in result.diagnostic_facts),
        *(fact.claim_id for fact in result.validation_facts),
    }


def test_exact_changed_symbol_does_not_seed_unrelated_nodes_in_same_file() -> None:
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        _snapshot(
            _link("src/work_caller.py", "src/core.py", "CALLS", "use_work", "work"),
            _link(
                "src/other_caller.py",
                "src/core.py",
                "CALLS",
                "use_other",
                "other",
            ),
        ),
    )

    assert "use_work" in result.rendered_text
    assert "use_other" not in result.rendered_text


def test_post_mutation_semantics_exclude_unrelated_catalog_rows() -> None:
    evidence = replace(
        _evidence(),
        definitions=(
            {
                "path": "src/aaa.py",
                "line": 1,
                "symbol": "unrelated",
                "signature": "def unrelated()",
                "origin": "program",
                "resolution_outcome": "exact",
                "provenance": ("graph_node:2", "checkout_source"),
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
            *_evidence().definitions,
        ),
    )
    result = RepositoryContextEngine(max_tokens=320).project(
        DecisionOpportunity(
            kind="post_mutation",
            evidence_action=2,
            eligible_call=3,
            source_revision="source-1",
            graph_revision="graph-1",
            changed_paths=("src/core.py",),
            changed_symbols=("work",),
        ),
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=evidence,
            structural_links=(),
            path_origins=(
                ("src/aaa.py", "preexisting_repository"),
                ("src/core.py", "preexisting_repository"),
            ),
        ),
    )

    assert result.status is RepositoryContextStatus.DELIVER
    assert "src/core.py" in result.rendered_text
    assert "unrelated" not in result.rendered_text


def test_validation_selects_broad_discovered_check_and_dedupes_observed_check() -> None:
    evidence = replace(_evidence(), project_checks=("pytest",))
    opportunity = DecisionOpportunity(
        kind="post_mutation",
        evidence_action=2,
        eligible_call=3,
        source_revision="source-1",
        graph_revision="graph-1",
        changed_paths=("src/core.py",),
        changed_symbols=("work",),
    )
    link = _link(
        "src/core.py",
        "tests/test_core.py",
        "ASSERTED_BY",
        "work",
        "test_work",
    )

    selected = RepositoryContextEngine(max_tokens=320).project(
        opportunity,
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=evidence,
            structural_links=(link,),
            validation_checks=evidence.project_checks,
        ),
    )
    represented = RepositoryContextEngine(max_tokens=320).project(
        opportunity,
        RepositorySnapshot(
            source_revision="source-1",
            graph_revision="graph-1",
            repository_evidence=evidence,
            structural_links=(link,),
            validation_checks=evidence.project_checks,
            represented_checks=frozenset({"pytest"}),
        ),
    )

    assert selected.validation_facts[0].command == "pytest"
    assert represented.validation_facts == ()
