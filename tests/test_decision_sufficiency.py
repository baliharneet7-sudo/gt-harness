from __future__ import annotations

from dataclasses import replace

import pytest

from gt_engine.decision_sufficiency import (
    DecisionSufficiencyDisposition,
    ProviderVisibleState,
    compile_decision_sufficiency,
)
from gt_engine.hybrid_retrieval import (
    HybridRetrievalResult,
    HybridRetriever,
    RepositoryDocument,
    RetrievalActionState,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalIntent,
    RetrievalState,
    StructuralLink,
)
from gt_engine.preflight import (
    ActionOperation,
    ActionTarget,
    MutationCertainty,
    ProposedAction,
)


def _proposal(
    operation: ActionOperation = ActionOperation.EDIT,
    *,
    targets: tuple[str, ...] = ("src/app.py",),
    source_revision: str = "source-1",
    mutates_workspace: bool = True,
) -> ProposedAction:
    return ProposedAction(
        action_id="action-1",
        raw_command="sed -i s/old/new/ src/app.py",
        operation=operation,
        targets=tuple(ActionTarget(path) for path in targets),
        mutates_workspace=mutates_workspace,
        validation_kind=None,
        source_revision=source_revision,
        workspace_revision="workspace-1",
        model_call=2,
        batch_index=0,
        batch_size=1,
        parser_confidence=1.0,
        mutation_certainty=(
            MutationCertainty.PROVEN_MUTATING
            if mutates_workspace
            else MutationCertainty.PROVEN_READ_ONLY
        ),
        parse_coverage=1.0,
    )


def _candidate(
    *,
    path: str = "src/app.py",
    source_revision: str = "source-1",
    relation: str | None = None,
    provenance: tuple[str, ...] = (
        "exact_path",
        "delivery_support:certified",
        "support_channel:exact",
    ),
    text: str = "def update_contract():\n    return 'mechanical fact'",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        path=path,
        start_line=4,
        end_line=5,
        symbol="update_contract",
        text=text,
        channel=(
            RetrievalChannel.STRUCTURAL
            if "support_channel:structural" in provenance
            else RetrievalChannel.EXACT
        ),
        channel_rank=1,
        relation=relation,
        provenance=provenance,
        source_revision=source_revision,
        channel_score=1.0,
    )


def _retrieval(
    candidates: tuple[RetrievalCandidate, ...] | None = None,
    *,
    selected_tokens: int = 40,
    token_budget: int = 200,
    reason_codes: tuple[str, ...] = ("selected_bounded_context",),
) -> HybridRetrievalResult:
    selected = candidates if candidates is not None else (_candidate(),)
    return HybridRetrievalResult(
        ranked_files=(),
        ranked_spans=selected,
        selected_context=selected,
        abstained=not selected,
        reason_codes=reason_codes,
        channel_receipts=(),
        latency_ms=1.0,
        query_hash="query-1",
        token_budget=token_budget,
        selected_token_count=selected_tokens,
    )


def _visible(
    *,
    request_claims: tuple[str, ...] = (),
    history_claims: tuple[str, ...] = (),
    source_revision: str = "source-1",
    graph_revision: str = "source-1",
    complete: bool = True,
) -> ProviderVisibleState:
    return ProviderVisibleState(
        selecting_request_hash="request-1",
        source_revision=source_revision,
        graph_revision=graph_revision,
        selecting_request_claim_ids=request_claims,
        retained_history_claim_ids=history_claims,
        complete=complete,
    )


def _compile(
    proposal: ProposedAction | None = None,
    retrieval: HybridRetrievalResult | None = None,
    visible: ProviderVisibleState | None = None,
):
    return compile_decision_sufficiency(
        proposal or _proposal(),
        retrieval or _retrieval(),
        visible or _visible(),
        current_source_revision="source-1",
        max_evidence_tokens=200,
        max_evidence_chars=480,
        max_evidence_claims=1,
    )


@pytest.mark.parametrize(
    "operation",
    (ActionOperation.READ, ActionOperation.SEARCH, ActionOperation.OTHER),
)
def test_read_search_and_other_always_pass(operation: ActionOperation) -> None:
    result = _compile(_proposal(operation, mutates_workspace=False))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert result.return_eligible is False
    assert "non_mutation_operation" in result.reason_codes


@pytest.mark.parametrize(
    "operation",
    (ActionOperation.VALIDATE, ActionOperation.SUBMIT, ActionOperation.INSTALL),
)
def test_other_non_workspace_mutations_pass(operation: ActionOperation) -> None:
    result = _compile(_proposal(operation, mutates_workspace=False))

    assert result.disposition is DecisionSufficiencyDisposition.PASS


def test_certified_exact_target_absent_from_request_is_return_eligible() -> None:
    result = _compile()

    assert result.disposition is DecisionSufficiencyDisposition.RETURN_ELIGIBLE
    assert result.return_eligible is True
    assert result.bundle is not None
    assert result.bundle.action_id == "action-1"
    assert result.bundle.target_path == "src/app.py"
    assert result.bundle.selecting_request_hash == "request-1"
    assert result.bundle.claims[0].support_kind == "mechanical_exact"
    assert result.bundle.claims[0].claim_id == _candidate().claim_hash


def test_claim_already_visible_in_selecting_request_passes() -> None:
    claim_id = _candidate().claim_hash
    result = _compile(visible=_visible(request_claims=(claim_id,)))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "evidence_already_provider_visible" in result.reason_codes


def test_claim_retained_in_provider_history_passes() -> None:
    claim_id = _candidate().claim_hash
    result = _compile(visible=_visible(history_claims=(claim_id,)))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "evidence_already_provider_visible" in result.reason_codes


@pytest.mark.parametrize(
    ("proposal_revision", "candidate_revision", "visible_revision", "reason"),
    (
        ("old", "source-1", "source-1", "source_revision_mismatch"),
        ("source-1", "old", "source-1", "graph_revision_mismatch"),
        ("source-1", "source-1", "old", "source_revision_mismatch"),
    ),
)
def test_every_revision_boundary_must_be_current(
    proposal_revision: str,
    candidate_revision: str,
    visible_revision: str,
    reason: str,
) -> None:
    result = _compile(
        _proposal(source_revision=proposal_revision),
        _retrieval((_candidate(source_revision=candidate_revision),)),
        _visible(source_revision=visible_revision),
    )

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert reason in result.reason_codes


def test_semantic_source_and_graph_revisions_are_checked_independently() -> None:
    proposal = _proposal(source_revision="semantic-1")
    candidate = _candidate(source_revision="graph-1")
    visible = _visible(source_revision="semantic-1", graph_revision="graph-1")

    result = compile_decision_sufficiency(
        proposal,
        _retrieval((candidate,)),
        visible,
        current_source_revision="semantic-1",
        current_graph_revision="graph-1",
        max_evidence_tokens=200,
        max_evidence_chars=480,
    )

    assert result.disposition is DecisionSufficiencyDisposition.RETURN_ELIGIBLE
    assert result.bundle is not None
    assert result.bundle.source_revision == "semantic-1"
    assert result.bundle.graph_revision == "graph-1"


def test_multiple_or_missing_action_targets_fail_closed() -> None:
    multiple = _compile(_proposal(targets=("src/app.py", "src/other.py")))
    missing = _compile(_proposal(targets=()))

    assert multiple.disposition is DecisionSufficiencyDisposition.PASS
    assert missing.disposition is DecisionSufficiencyDisposition.PASS
    assert multiple.reason_codes == ("non_unique_action_target",)
    assert missing.reason_codes == ("non_unique_action_target",)


def test_target_mismatch_is_not_material() -> None:
    result = _compile(retrieval=_retrieval((_candidate(path="src/other.py"),)))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "no_exact_target_material" in result.reason_codes


def test_certified_structural_claim_requires_explicit_action_target_anchor() -> None:
    provenance = (
        "graph_edge:7",
        "trust:CERTIFIED",
        "structural_certified",
        "delivery_support:certified",
        "support_channel:structural",
        "action_target:src/app.py",
    )
    candidate = _candidate(
        path="src/caller.py",
        relation="CALLS",
        provenance=provenance,
    )

    result = _compile(retrieval=_retrieval((candidate,)))

    assert result.disposition is DecisionSufficiencyDisposition.RETURN_ELIGIBLE
    assert result.bundle is not None
    assert result.bundle.claims[0].support_kind == "certified_structural"


def test_real_structural_channel_emits_action_target_and_becomes_return_eligible() -> None:
    documents = (
        RepositoryDocument("src/app.py", "def update_contract(): pass"),
        RepositoryDocument("src/caller.py", "def caller(): update_contract()"),
    )
    retrieval = HybridRetriever(
        documents,
        structural_links=(
            StructuralLink(
                "src/app.py",
                "src/caller.py",
                "CALLS",
                confidence=0.99,
                provenance=("graph_edge:7", "trust:CERTIFIED"),
                certified=True,
            ),
        ),
    ).retrieve(
        RetrievalState(
            task_text="modify src/app.py",
            intent=RetrievalIntent.CHANGE_IMPACT,
            active_paths=("src/app.py",),
            source_revision="source-1",
        ),
        selection_limit=1,
        token_budget=200,
    )

    result = _compile(retrieval=retrieval)

    assert retrieval.selected_context
    assert "action_target:src/app.py" in retrieval.selected_context[0].provenance
    assert result.disposition is DecisionSufficiencyDisposition.RETURN_ELIGIBLE


def test_structural_channel_seeds_from_typed_action_target_without_hiding_exact_file() -> None:
    documents = (
        RepositoryDocument("src/app.py", "def update_contract(): pass"),
        RepositoryDocument("src/caller.py", "def caller(): update_contract()"),
    )
    retrieval = HybridRetriever(
        documents,
        structural_links=(
            StructuralLink(
                "src/app.py",
                "src/caller.py",
                "CALLS",
                confidence=0.99,
                provenance=("graph_edge:7", "trust:CERTIFIED"),
                certified=True,
            ),
        ),
    ).retrieve(
        RetrievalState(
            task_text="modify implementation",
            intent=RetrievalIntent.CHANGE_IMPACT,
            action=RetrievalActionState(
                operation="edit",
                executable="sed",
                targets=("src/app.py",),
            ),
            source_revision="source-1",
        ),
        selection_limit=2,
        token_budget=200,
    )

    paths = {row.path for row in retrieval.ranked_files}
    assert paths == {"src/app.py", "src/caller.py"}
    structural = next(
        row for row in retrieval.ranked_spans if row.path == "src/caller.py"
    )
    assert "action_target:src/app.py" in structural.provenance


def test_real_structural_cochange_cannot_certify_even_if_link_is_marked_certified() -> None:
    documents = (
        RepositoryDocument("src/app.py", "def update_contract(): pass"),
        RepositoryDocument("src/neighbor.py", "def historical_neighbor(): pass"),
    )
    retrieval = HybridRetriever(
        documents,
        structural_links=(
            StructuralLink(
                "src/app.py",
                "src/neighbor.py",
                "COCHANGE",
                confidence=1.0,
                provenance=("graph_cochange:count=100",),
                certified=True,
            ),
        ),
    ).retrieve(
        RetrievalState(
            task_text="modify src/app.py",
            intent=RetrievalIntent.CHANGE_IMPACT,
            active_paths=("src/app.py",),
            source_revision="source-1",
        ),
        selection_limit=1,
        token_budget=200,
    )

    result = _compile(retrieval=retrieval)

    assert retrieval.selected_context
    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "no_certified_mechanical_evidence" in result.reason_codes


def test_structural_claim_without_exact_target_anchor_passes() -> None:
    candidate = _candidate(
        path="src/caller.py",
        relation="CALLS",
        provenance=(
            "structural_certified",
            "delivery_support:certified",
            "support_channel:structural",
        ),
    )

    result = _compile(retrieval=_retrieval((candidate,)))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "no_exact_target_material" in result.reason_codes


@pytest.mark.parametrize(
    "candidate",
    (
        _candidate(
            provenance=("lexical", "bm25", "delivery_support:corroborated"),
        ),
        _candidate(
            provenance=("dense_cosine", "delivery_support:validation_candidate"),
        ),
        _candidate(
            path="src/other.py",
            relation="COCHANGE",
            provenance=(
                "graph_cochange:count=20",
                "structural_certified",
                "delivery_support:certified",
                "support_channel:structural",
                "action_target:src/app.py",
            ),
        ),
    ),
)
def test_sparse_dense_and_cochange_never_certify_alone(
    candidate: RetrievalCandidate,
) -> None:
    result = _compile(retrieval=_retrieval((candidate,)))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "no_certified_mechanical_evidence" in result.reason_codes


def test_duplicate_certified_claims_fail_closed() -> None:
    candidate = _candidate()
    result = _compile(retrieval=_retrieval((candidate, candidate)))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "duplicate_evidence_claim" in result.reason_codes


def test_two_distinct_certified_claims_exceed_unique_claim_policy() -> None:
    first = _candidate()
    second = _candidate(text="def second_contract(): return 2")

    result = _compile(retrieval=_retrieval((first, second), selected_tokens=80))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert "evidence_claim_limit" in result.reason_codes


@pytest.mark.parametrize(
    "retrieval",
    (
        _retrieval((), selected_tokens=0),
        _retrieval((_candidate(text=""),)),
        _retrieval((_candidate(),), reason_codes=("context_budget",)),
        _retrieval((_candidate(),), selected_tokens=201, token_budget=300),
        _retrieval((_candidate(),), selected_tokens=201, token_budget=200),
    ),
)
def test_incomplete_or_over_budget_evidence_passes(
    retrieval: HybridRetrievalResult,
) -> None:
    result = _compile(retrieval=retrieval)

    assert result.disposition is DecisionSufficiencyDisposition.PASS


def test_incomplete_provider_visibility_state_passes() -> None:
    result = _compile(visible=_visible(complete=False))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert result.reason_codes == ("provider_visibility_incomplete",)


def test_low_confidence_or_ambiguous_action_parser_passes() -> None:
    low_confidence = replace(_proposal(), parser_confidence=0.7)
    unknown = replace(_proposal(), has_unknown_segments=True)
    opaque = replace(_proposal(), has_opaque_segments=True)

    assert _compile(low_confidence).disposition is DecisionSufficiencyDisposition.PASS
    assert _compile(unknown).disposition is DecisionSufficiencyDisposition.PASS
    assert _compile(opaque).disposition is DecisionSufficiencyDisposition.PASS


def test_bundle_is_replayable_and_contains_no_raw_command() -> None:
    result = _compile()

    assert result.bundle is not None
    receipt = result.as_dict()
    assert receipt["bundle"]["claims"][0]["text"] == _candidate().text
    assert receipt["bundle"]["char_count"] == len(_candidate().text)
    assert "sed -i" not in repr(receipt)
    assert receipt["disposition"] == "return_eligible"


def test_complete_evidence_over_character_budget_passes_without_truncation() -> None:
    candidate = _candidate(text="x" * 481)

    result = _compile(retrieval=_retrieval((candidate,), selected_tokens=40))

    assert result.disposition is DecisionSufficiencyDisposition.PASS
    assert result.reason_codes == ("evidence_character_budget",)
