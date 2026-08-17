from eval.gt_central_agent import _account_preemptive_contribution_result


def test_contribution_rejection_turns_retrieval_selection_into_abstention():
    decision = {
        "status": "selected",
        "reason_codes": ["selected_bounded_context"],
        "selected_evidence": [{"claim_hash": "claim-1"}],
    }
    compilation = {
        "accounting": [
            {
                "surface": "preemptive_retrieval",
                "disposition": "expired_window",
                "reason_codes": ["first_eligible_request_passed"],
            }
        ]
    }

    _account_preemptive_contribution_result(
        decision,
        compilation=compilation,
        contribution_selected=False,
    )

    assert decision["status"] == "abstained"
    assert decision["retriever_status_before_contribution_compiler"] == "selected"
    assert decision["contribution_compiler_disposition"] == "expired_window"
    assert decision["contribution_compiler_selected"] is False
    assert "contribution_expired_window" in decision["reason_codes"]
    assert "first_eligible_request_passed" in decision["reason_codes"]


def test_selected_contribution_remains_selected_until_request_preparation():
    decision = {
        "status": "selected",
        "reason_codes": ["selected_bounded_context"],
    }

    _account_preemptive_contribution_result(
        decision,
        compilation={"accounting": []},
        contribution_selected=True,
    )

    assert decision["status"] == "selected"
