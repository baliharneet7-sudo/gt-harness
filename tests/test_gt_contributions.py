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
    assert all(
        row.disposition is ContributionDisposition.SELECTED for row in result.accounting
    )


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
    assert all(
        row.disposition is ContributionDisposition.SELECTED
        for row in result.accounting
    )


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
