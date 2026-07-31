from eval.tb_agent import _GT_STAGED_SOURCE_CLEANUP, GTNanoAgent


def test_gt_adapter_version_does_not_require_staged_checkout():
    command = GTNanoAgent.get_version_command(GTNanoAgent)

    assert command is not None
    assert "/installed-agent/nano-harness" not in command
    assert "$HOME/.local/share/uv/tools/nano-harness/bin/python" in command


def test_gt_staged_source_cleanup_is_exact_and_guarded():
    assert _GT_STAGED_SOURCE_CLEANUP == (
        "test \"$(readlink -f /installed-agent/nano-harness)\" = "
        "\"/installed-agent/nano-harness\" && "
        "rm -rf -- /installed-agent/nano-harness"
    )
