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


def test_budget_risk_returns_only_broad_non_progress_exploration():
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

    assert broad.disposition is ActionDisposition.RETURN_TO_MODEL
    assert "convergence_budget_requires_verification" in broad.reason_codes
    assert "pytest -q" in " ".join(broad.evidence)
    assert focused.disposition is ActionDisposition.PASS
