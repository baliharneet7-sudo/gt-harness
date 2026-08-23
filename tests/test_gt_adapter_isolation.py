from eval.tb_agent import _GT_STAGED_SOURCE_CLEANUP, GTNanoAgent


def test_gt_adapter_version_does_not_require_staged_checkout():
    command = GTNanoAgent.get_version_command(GTNanoAgent)

    assert command is not None
    assert "/installed-agent/nano-harness" not in command
    assert "$HOME/.local/share/uv/tools/gt-harness/bin/python" in command


def test_gt_staged_source_cleanup_is_exact_and_guarded():
    assert _GT_STAGED_SOURCE_CLEANUP == (
        "test \"$(readlink -f /installed-agent/gt-harness)\" = "
        "\"/installed-agent/gt-harness\" && "
        "rm -rf -- /installed-agent/gt-harness"
    )


def test_gt_run_uses_external_private_state_directory(monkeypatch, tmp_path):
    class _Environment:
        environment_name = "fixture-task"

    captured = {}

    async def fake_exec(_self, _environment, command, env):
        captured["command"] = command
        captured["env"] = env

    monkeypatch.setattr(GTNanoAgent, "exec_as_agent", fake_exec)
    agent = GTNanoAgent(logs_dir=tmp_path)
    agent.model_name = "deepseek-v4-flash"
    agent.gt_profile = "2"

    import asyncio

    asyncio.run(agent.run("task", _Environment(), object()))

    assert captured["env"]["GT_STATE_DIR"] == "/tmp/.nano-gt-state"
    assert '--treatment groundtruth --root "$PWD"' in captured["command"]
    assert "--output /logs/agent/gt-run.json" in captured["command"]
    assert "--task-id fixture-task" in captured["command"]
    assert "--trial-id 1" in captured["command"]


def test_gateway_base_url_reaches_the_official_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example.invalid/v1")
    agent = GTNanoAgent(logs_dir=tmp_path)

    command = agent._run_command("task", "provider/model")

    assert '--base-url "$OPENAI_BASE_URL"' in command
