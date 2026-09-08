from scripts.swebench.live_lite_readiness import audit


def test_live_lite_openrouter_route_is_provider_free_ready() -> None:
    receipt = audit()
    assert receipt["status"] == "READY", receipt["errors"]
    assert receipt["provider_calls"] == 0
    assert receipt["task_count"] == 300
    assert receipt["unique_task_count"] == 300
    assert receipt["control_treatment_limits"]["control"] == (
        receipt["control_treatment_limits"]["treatment"]
    )
