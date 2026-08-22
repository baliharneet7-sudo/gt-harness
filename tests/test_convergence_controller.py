from __future__ import annotations

from gt_engine.convergence_controller import convergence_preflight
from gt_engine.preflight import (
    ActionDisposition,
    adapt_proposed_action,
)


def _proposal(command: str):
    return adapt_proposed_action(
        {"command": command, "tool_call_id": "call-1"},
        source_revision="source-1",
        workspace_revision="workspace-1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )


def test_forbidden_grader_and_harness_paths_return_before_execution():
    for command in (
        "cat /logs/verifier/output.txt",
        "find / -iname '*solution*'",
        "cat /app/reward.txt",
    ):
        decision = convergence_preflight(
            _proposal(command),
            cwd="/app",
            source_revision="source-1",
        )
        assert decision.disposition is ActionDisposition.RETURN_TO_MODEL
        assert "forbidden_benchmark_artifact_path" in decision.reason_codes
        assert decision.confidence == 1.0


def test_explicit_task_runtime_log_path_is_not_blocked():
    for command in (
        "tail -n 50 /var/log/nginx/error.log",
        "cat /app/ref",
    ):
        decision = convergence_preflight(
            _proposal(command),
            cwd="/app",
            source_revision="source-1",
        )

        assert decision.disposition is ActionDisposition.PASS


def test_repository_root_is_not_itself_a_forbidden_artifact_path():
    for command in (
        "find / -name 'python*'",
        "find / -name extract.js",
    ):
        decision = convergence_preflight(
            _proposal(command),
            cwd="/app",
            source_revision="source-1",
        )

        assert decision.disposition is ActionDisposition.PASS
        assert "forbidden_benchmark_artifact_path" not in decision.reason_codes


def test_broad_find_selectors_do_not_imply_grader_artifact_intent():
    for command in (
        'find /app -type f -name "*.py"',
        'find / -maxdepth 3 -name "*.js" -o -name "*.json"',
        'find . -iname "*.txt"',
        'find / -maxdepth 4 -type d -name "*test*"',
        'find / -name "*.json" -path "*report*"',
        'find . -name "*.jsonl" -o -name "*.json"',
        'find / -name "*terminal*" -o -name "*test*"',
        'find / -name "*.py" -path "*test*"',
        'find . -name "*.py" -o -name "*.sh" | grep -i test',
        'find / -maxdepth 3 -name "*test*" -o -name "*grade*" -o -name "*eval*"',
        'find . -iname "*.txt" -o -iname "*.doc"',
    ):
        decision = convergence_preflight(
            _proposal(command),
            cwd="/app",
            source_revision="source-1",
        )

        assert decision.disposition is ActionDisposition.PASS
        assert "forbidden_benchmark_artifact_path" not in decision.reason_codes


def test_nested_forbidden_find_selectors_return_before_execution():
    for command in (
        "find / -path '*/logs/verifier/*'",
        "find / -ipath '*/solution/subdir/*'",
        "find / -path '*/nested/reward.txt'",
        "find / -regex '.*reward[.]txt'",
        "find /tmp -regex '^/tmp/private/.*/reward\\.txt$'",
        "busybox find / -iname '*solution*'",
    ):
        decision = convergence_preflight(
            _proposal(command),
            cwd="/app",
            source_revision="source-1",
        )

        assert decision.disposition is ActionDisposition.RETURN_TO_MODEL
        assert "forbidden_benchmark_artifact_path" in decision.reason_codes


def test_forbidden_path_evidence_uses_neutral_task_language():
    decision = convergence_preflight(
        _proposal("cat /logs/verifier/output.txt"),
        cwd="/app",
        source_revision="source-1",
    )

    rendered = " ".join(decision.evidence).lower()
    assert "task evidence boundary" in rendered
    assert "benchmark" not in rendered
    assert "harness" not in rendered
    assert "grader" not in rendered


def test_forbidden_paths_cannot_hide_behind_relative_or_static_shell_syntax():
    for command in (
        "cat ../solution/answer.txt",
        'p=/solution; cat "$p"/answer.txt',
        'python -c "open(\'/solution/answer.txt\').read()"',
        "cat $(printf /solution/answer.txt)",
    ):
        decision = convergence_preflight(
            _proposal(command),
            cwd="/app",
            source_revision="source-1",
        )

        assert decision.disposition is ActionDisposition.RETURN_TO_MODEL
        assert "forbidden_benchmark_artifact_path" in decision.reason_codes


def test_budget_risk_never_adds_a_provider_reasoning_loop():
    broad = convergence_preflight(
        _proposal("find /app -type f"),
        cwd="/app",
        source_revision="source-1",
        progress_state="BUDGET_RISK",
        unresolved_anchors=("pytest -q", "out.json"),
    )
    focused = convergence_preflight(
        _proposal("pytest -q"),
        cwd="/app",
        source_revision="source-1",
        progress_state="BUDGET_RISK",
        unresolved_anchors=("pytest -q", "out.json"),
    )

    assert broad.disposition is ActionDisposition.PASS
    assert focused.disposition is ActionDisposition.PASS


def test_budget_risk_does_not_return_mixed_result_checks_or_prose_anchors():
    mixed_check = convergence_preflight(
        _proposal(
            'grep "Posterior mean" /tmp/final_run.log; '
            'cat posterior_alpha_mean.txt; ls -la /app'
        ),
        cwd="/app",
        source_revision="source-1",
        progress_state="BUDGET_RISK",
        unresolved_anchors=(
            "Install the required package and load the dataset from /app/data.csv.",
        ),
    )
    prose_only_search = convergence_preflight(
        _proposal("find /app -type f"),
        cwd="/app",
        source_revision="source-1",
        progress_state="BUDGET_RISK",
        unresolved_anchors=(
            "Figure out how to detect the jump and output the exact TOML structure.",
        ),
    )
    one_word_prose = convergence_preflight(
        _proposal("find /app -type f"),
        cwd="/app",
        source_revision="source-1",
        progress_state="BUDGET_RISK",
        unresolved_anchors=("Optimize",),
    )

    assert mixed_check.disposition is ActionDisposition.PASS
    assert prose_only_search.disposition is ActionDisposition.PASS
    assert one_word_prose.disposition is ActionDisposition.PASS
