from pathlib import Path


def test_arb_and_live_share_one_frozen_retrieval_profile():
    from gt_engine.retrieval_profile import FINAL_RETRIEVAL_PROFILE
    from scripts.arb_adapter import ARB_RETRIEVAL_PROFILE

    assert ARB_RETRIEVAL_PROFILE is FINAL_RETRIEVAL_PROFILE
    assert FINAL_RETRIEVAL_PROFILE.channel_limit == 100
    assert FINAL_RETRIEVAL_PROFILE.top_k == 20
    assert FINAL_RETRIEVAL_PROFILE.selection_limit == 8
    assert FINAL_RETRIEVAL_PROFILE.token_budget == 1_200
    assert FINAL_RETRIEVAL_PROFILE.dense_candidate_limit == 32
    assert FINAL_RETRIEVAL_PROFILE.cold_start_timeout_sec >= 25.0
    assert FINAL_RETRIEVAL_PROFILE.steady_state_timeout_sec == 2.0


def test_live_agent_defaults_match_the_frozen_retrieval_profile(tmp_path):
    from eval.gt_central_agent import MiniSweCentralAgent
    from gt_engine.retrieval_profile import FINAL_RETRIEVAL_PROFILE

    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")

    assert (
        agent.preemptive_retrieval_token_budget
        == FINAL_RETRIEVAL_PROFILE.token_budget
    )
    assert (
        agent.preemptive_retrieval_dense_candidate_limit
        == FINAL_RETRIEVAL_PROFILE.dense_candidate_limit
    )
    assert (
        agent.preemptive_retrieval_selection_limit
        == FINAL_RETRIEVAL_PROFILE.selection_limit
    )
    assert (
        agent.preemptive_retrieval_cold_start_timeout_sec
        == FINAL_RETRIEVAL_PROFILE.cold_start_timeout_sec
    )
    assert (
        agent.preemptive_retrieval_timeout_sec
        == FINAL_RETRIEVAL_PROFILE.steady_state_timeout_sec
    )


def test_paid_context_arms_enable_the_pinned_live_retriever():
    root = Path(__file__).resolve().parents[1]
    for name in ("tb2_miniswe_engine.yml", "tb2_miniswe_central.yml"):
        workflow = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "python -m pip install -e '.[retrieval]'" in workflow
        assert "GH_TOKEN: ${{ github.token }}" in workflow
        assert "SNOWFLAKE_MODEL_SHA256:" in workflow
        assert "SNOWFLAKE_TOKENIZER_SHA256:" in workflow
        assert "tokenizer.json\" | sha256sum -c -" in workflow
        assert "Provision pinned Snowflake ONNX runtime asset" in workflow
        assert (
            "if: ${{ inputs.arm == 'certified_context' || inputs.arm == 'certified_full' }}"
            in workflow
        )
        assert workflow.count("--ak enable_preemptive_retrieval=true") == 2
        assert workflow.count(
            '--ak preemptive_retrieval_model_dir="$RUNNER_TEMP/snowflake-arctic-embed-m"'
        ) == 2
        assert "--ak enable_preemptive_retrieval=false" in workflow
