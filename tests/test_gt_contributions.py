import pytest


def _contribution(**overrides):
    from gt_engine.contributions import ContributionKind, GTContribution

    values = {
        "surface": "preemptive_retrieval",
        "kind": ContributionKind.EVIDENCE,
        "payload": "src/a.py:10 — definition A",
        "claim_ids": ("claim-a",),
        "fact_ids": ("fact-a",),
        "evidence_action": 1,
        "eligible_call": 2,
        "source_revision": "rev-1",
        "priority": 10,
    }
    values.update(overrides)
    if "claim_metadata" not in overrides:
        authority_ids = values["claim_ids"] or values["fact_ids"]
        values["claim_metadata"] = tuple(
            {
                "claim_id": authority_id,
                "origin": "preexisting_repository",
                "authority": "certified_structural",
                "materiality_reason": "decision_relevant_repository_context",
            }
            for authority_id in authority_ids
        )
    return GTContribution.create(**values)


def test_contribution_compiler_accounts_every_candidate_once():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    result = compile_contributions(
        (
            _contribution(),
            _contribution(
                surface="graph_frontier",
                payload="src/b.py:20 — caller B",
                claim_ids=("claim-b",),
                fact_ids=("fact-b",),
                priority=20,
            ),
        ),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=1_000,
    )

    assert result.candidate_count == 2
    assert result.accounted_count == 2
    assert result.payload == "src/a.py:10 — definition A\n\nsrc/b.py:20 — caller B"
    assert all(row.disposition is ContributionDisposition.SELECTED for row in result.accounting)


def test_contribution_compiler_accepts_current_raw_and_graph_revisions():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    result = compile_contributions(
        (
            _contribution(source_revision="raw-rev"),
            _contribution(
                surface="graph_frontier",
                payload="src/b.py:20 — caller B",
                claim_ids=("claim-b",),
                fact_ids=("fact-b",),
                source_revision="graph-rev",
                priority=20,
            ),
        ),
        current_source_revision=("raw-rev", "graph-rev"),
        current_call=2,
        budget_chars=1_000,
    )

    assert result.payload
    assert all(row.disposition is ContributionDisposition.SELECTED for row in result.accounting)


def test_contribution_compiler_deduplicates_claims_across_surfaces():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    kept = _contribution(priority=10)
    duplicate = _contribution(
        surface="graph_frontier",
        payload="a differently formatted rendering of the same claim",
        fact_ids=("frontier-fact",),
        priority=20,
    )
    result = compile_contributions(
        (duplicate, kept),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=1_000,
    )

    assert result.selected_ids == (kept.contribution_id,)
    disposition = {row.contribution_id: row.disposition for row in result.accounting}
    assert disposition[duplicate.contribution_id] is ContributionDisposition.DUPLICATE_CLAIM


def test_contribution_compiler_rejects_stale_late_and_over_budget_whole_facts():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    stale = _contribution(source_revision="old")
    late = _contribution(surface="feature_fact", claim_ids=("late",), eligible_call=1)
    too_large = _contribution(
        surface="progress_frame",
        claim_ids=("large",),
        payload="x" * 200,
    )
    result = compile_contributions(
        (stale, late, too_large),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=50,
    )

    assert result.payload == ""
    dispositions = {row.disposition for row in result.accounting}
    assert dispositions == {
        ContributionDisposition.STALE_SOURCE_REVISION,
        ContributionDisposition.EXPIRED_WINDOW,
        ContributionDisposition.BUDGET,
    }


def test_controller_only_contribution_is_accounted_but_never_rendered():
    from gt_engine.contributions import (
        ContributionDisposition,
        ContributionKind,
        compile_contributions,
    )

    controller = _contribution(
        kind=ContributionKind.CONTROLLER_STATE,
        payload="",
        claim_ids=(),
        fact_ids=("validation-debt",),
    )
    result = compile_contributions(
        (controller,),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=1_000,
    )

    assert result.payload == ""
    assert result.accounting[0].disposition is ContributionDisposition.CONTROLLER_ONLY


def test_invalid_evidence_contribution_fails_closed():
    with pytest.raises(ValueError, match="grounded evidence"):
        _contribution(payload="", claim_ids=(), fact_ids=())


def test_contribution_compiler_rejects_model_authored_provider_authority():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    unsafe = _contribution(
        surface="persistent_execution_state",
        claim_metadata=(
            {
                "claim_id": "claim-a",
                "origin": "model_authored",
                "authority": "certified_relation",
            },
        ),
    )

    result = compile_contributions(
        (unsafe,),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=1_000,
    )

    assert result.payload == ""
    assert result.accounting[0].disposition is ContributionDisposition.UNSAFE_PROVENANCE
    assert result.accounting[0].reason_codes == ("model_authored_provider_authority",)


def test_contribution_compiler_rejects_missing_provider_provenance():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    missing = _contribution(claim_metadata=())

    result = compile_contributions(
        (missing,),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=1_000,
    )

    assert result.payload == ""
    assert result.accounting[0].disposition is ContributionDisposition.UNSAFE_PROVENANCE
    assert result.accounting[0].reason_codes == ("unknown_provider_authority",)


def test_contribution_compiler_enforces_one_combined_token_budget():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    first = _contribution(
        surface="persistent_execution_state",
        payload=" ".join(["state"] * 8),
        claim_ids=("state",),
        fact_ids=(),
        priority=10,
    )
    second = _contribution(
        surface="preemptive_retrieval",
        payload=" ".join(["source"] * 8),
        claim_ids=("source",),
        fact_ids=(),
        priority=20,
    )
    third = _contribution(
        surface="feature_fact",
        payload=" ".join(["failure"] * 8),
        claim_ids=("failure",),
        fact_ids=(),
        priority=30,
    )

    result = compile_contributions(
        (third, second, first),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=10_000,
        budget_tokens=17,
    )

    assert result.token_count <= 17
    assert result.selected_ids == (first.contribution_id, second.contribution_id)
    dispositions = {row.contribution_id: row.disposition for row in result.accounting}
    assert dispositions[third.contribution_id] is ContributionDisposition.BUDGET


def test_persistent_core_is_selected_before_large_diagnostic_retrieval():
    from eval.gt_central_agent import PERSISTENT_STATE_CONTRIBUTION_PRIORITY
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    persistent = _contribution(
        surface="persistent_execution_state",
        payload="current phase and open obligation",
        claim_ids=("state-core",),
        fact_ids=(),
        priority=PERSISTENT_STATE_CONTRIBUTION_PRIORITY,
    )
    diagnostic = _contribution(
        surface="preemptive_retrieval",
        payload=" ".join(["diagnostic"] * 1_200),
        claim_ids=("diagnostic",),
        fact_ids=(),
        priority=5,
    )

    result = compile_contributions(
        (diagnostic, persistent),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=100_000,
        budget_tokens=1_200,
    )

    assert persistent.contribution_id in result.selected_ids
    dispositions = {row.contribution_id: row.disposition for row in result.accounting}
    assert dispositions[diagnostic.contribution_id] is ContributionDisposition.BUDGET


def test_task_budget_is_cumulative_and_reserves_only_critical_evidence():
    from gt_engine.contributions import ContributionTaskBudget

    budget = ContributionTaskBudget(token_budget=100, critical_reserve_tokens=20)
    assert budget.available_tokens(critical=False) == 80
    budget.commit(75, critical=False)
    assert budget.available_tokens(critical=False) == 5
    assert budget.available_tokens(critical=True) == 25
    budget.commit(5, critical=False)
    assert budget.available_tokens(critical=False) == 0
    assert budget.available_tokens(critical=True) == 20
    budget.commit(20, critical=True)
    assert budget.available_tokens(critical=True) == 0
    assert budget.exhausted is True


def test_lifecycle_required_context_survives_closed_discretionary_task_budget():
    from gt_engine.contributions import ContributionDisposition, compile_contributions

    persistent = _contribution(
        surface="persistent_execution_state",
        lifecycle_required=True,
    )
    optional = _contribution(
        surface="repository_context",
        payload="optional repository evidence",
        claim_ids=("claim-b",),
        fact_ids=("fact-b",),
        claim_metadata=(
            {
                "claim_id": "claim-b",
                "origin": "preexisting_repository",
                "authority": "certified_structural",
                "materiality_reason": "decision_relevant_repository_context",
            },
        ),
    )

    result = compile_contributions(
        (persistent, optional),
        current_source_revision="rev-1",
        current_call=2,
        budget_chars=1_000,
        budget_tokens=1_000,
        task_budget_tokens=0,
        allow_noncritical=False,
    )

    assert result.selected_ids == (persistent.contribution_id,)
    assert result.task_budget_token_count == 0
    dispositions = {row.contribution_id: row.disposition for row in result.accounting}
    assert dispositions[optional.contribution_id] is ContributionDisposition.BUDGET


def test_mixed_materiality_contribution_cannot_spend_critical_reserve():
    mixed = _contribution(
        claim_ids=("failure", "ordinary"),
        fact_ids=(),
        claim_metadata=(
            {
                "claim_id": "failure",
                "origin": "execution_observation",
                "authority": "execution_observation",
                "materiality_reason": "current_attributable_failure",
            },
            {
                "claim_id": "ordinary",
                "origin": "preexisting_repository",
                "authority": "certified_structural",
                "materiality_reason": "decision_relevant_repository_context",
            },
        ),
    )

    assert mixed.critical is False
