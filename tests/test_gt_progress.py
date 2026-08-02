from gt_engine.progress import ProgressLedger


def test_repeated_failure_transitions_before_budget_exhaustion():
    ledger = ProgressLedger(stall_threshold=3)
    assert ledger.observe(
        "same", information_gain=True, changed=False, is_error=True
    ) is None
    assert ledger.observe(
        "same", information_gain=False, changed=False, is_error=True
    ) is None
    transition = ledger.observe(
        "same", information_gain=False, changed=False, is_error=True
    )
    assert transition is not None
    assert transition.current == "CONTRADICTED"


def test_material_change_recovers_stall():
    ledger = ProgressLedger(stall_threshold=2)
    ledger.observe("same", information_gain=True, changed=False, is_error=False)
    stalled = ledger.observe(
        "same", information_gain=False, changed=False, is_error=False
    )
    assert stalled is not None and stalled.current == "STALLED"
    recovered = ledger.observe(
        "new", information_gain=True, changed=True, is_error=False
    )
    assert recovered is not None and recovered.current == "RECOVERED"


def test_budget_risk_only_for_unresolved_stall():
    ledger = ProgressLedger(stall_threshold=2)
    assert ledger.budget_risk(iteration=80, limit=100) is None
    ledger.observe("same", information_gain=True, changed=False, is_error=False)
    ledger.observe("same", information_gain=False, changed=False, is_error=False)
    transition = ledger.budget_risk(iteration=80, limit=100)
    assert transition is not None
    assert transition.current == "BUDGET_RISK"


def test_unresolved_contract_triggers_budget_risk_without_exact_loop():
    ledger = ProgressLedger(stall_threshold=3)
    transition = ledger.budget_risk(
        iteration=80, limit=100, unresolved=True
    )
    assert transition is not None
    assert transition.current == "BUDGET_RISK"
    assert transition.reason == "unresolved_contract_near_iteration_limit"


def test_nonconsecutive_repetition_stalls_within_unchanged_epoch():
    ledger = ProgressLedger(stall_threshold=3)
    ledger.observe("same", information_gain=True, changed=False, is_error=False)
    ledger.observe("other", information_gain=True, changed=False, is_error=False)
    ledger.observe("same", information_gain=False, changed=False, is_error=False)
    ledger.observe("third", information_gain=True, changed=False, is_error=False)
    transition = ledger.observe(
        "same", information_gain=False, changed=False, is_error=False
    )
    assert transition is not None
    assert transition.current == "STALLED"


def test_environment_error_stalls_without_source_contradiction():
    ledger = ProgressLedger(stall_threshold=2)
    ledger.observe("missing-dep", information_gain=True, changed=False, is_error=True)
    transition = ledger.observe(
        "missing-dep",
        information_gain=False,
        changed=False,
        is_error=True,
        contradictory=False,
    )
    assert transition is not None
    assert transition.current == "STALLED"
