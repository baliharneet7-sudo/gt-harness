from scripts.observe_gt_runs import feature_coverage


def _task(**overrides):
    base = {"tool_calls_by_name": {}, "augment_features": {}, "action_features": {},
            "treatment_valid": True}
    return {**base, **overrides}


def test_a_grep_hit_credits_only_the_features_it_carried():
    coverage = feature_coverage([_task(augment_features={"F2": 3, "F3": 1, "F12": 3})])
    assert coverage["F3 references"]["reached"] is True
    assert coverage["F3 references"]["via"] == {"augment": 1}
    assert coverage["F7 receiver/inheritance/overload"]["reached"] is False
    assert coverage["F10 communities"]["reached"] is False


def test_edit_and_failure_features_and_tool_calls_are_counted():
    coverage = feature_coverage([
        _task(action_features={"F13": 2, "F17": 1}),
        _task(tool_calls_by_name={"gt-taint": 1}),
    ])
    assert coverage["F13 patch impact / co-change"]["via"] == {"action-augment": 2}
    assert coverage["F17 PDG / slice"]["reached"] is True
    assert coverage["F19 taint"]["via"] == {"gt-taint": 1}
    assert coverage["F11 hybrid retrieval"]["reached"] is False
    assert coverage["F21 freshness / amend"]["reached"] is True
