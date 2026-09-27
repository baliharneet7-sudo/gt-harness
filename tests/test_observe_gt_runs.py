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


def test_live_matrix_separates_delivered_available_and_gap(tmp_path):
    import json

    from scripts.live_feature_matrix import _rows_from, matrix

    receipt = {"tasks": [{"task": "t1", "reward": 1, "gt_delivery": {
        "features_reached": {"F2": 3, "F18": 1}, "feature_inventory": {"F2": 10, "F18": 4, "F6": 2}}}]}
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "progress.json").write_text(json.dumps(receipt), encoding="utf-8")
    table = matrix(_rows_from(tmp_path))
    assert "| F2 | 1 | 1 | 0 |" in table
    assert "| F18 | 1 | 1 | 0 |" in table
    assert "| F6 | 0 | 1 | 1 |" in table
