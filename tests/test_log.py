import json

import pytest

from eval.log import RunLog, TaskRecord


def test_run_log_writes_manifest_and_transcripts(tmp_path):
    rl = RunLog(
        results_root=tmp_path,
        benchmark="terminal-bench",
        benchmark_version="v0.1.5",
        model="claude-opus-4-7",
        provider="anthropic",
        harness_commit="abc123",
        command="python -m eval.terminal_bench_adapter --model claude-opus-4-7",
    )
    rl.start()
    rl.add_task(TaskRecord(
        task_id="task-001", passed=True, iterations=4, wall_seconds=12.0,
        input_tokens=1000, output_tokens=200, cache_read_tokens=800,
        cost_usd=0.05,
        transcript=[{"type": "user", "content": "do x"}],
        failure_reason=None,
    ))
    rl.add_task(TaskRecord(
        task_id="task-002", passed=False, iterations=30, wall_seconds=180.0,
        input_tokens=20000, output_tokens=4000, cache_read_tokens=15000,
        cost_usd=1.50,
        transcript=[{"type": "user", "content": "do y"}],
        failure_reason="max_iterations",
    ))
    manifest_path = rl.finish(grader_output_path=tmp_path / "grader.txt")

    manifest = json.loads(manifest_path.read_text())
    assert manifest["benchmark"] == "terminal-bench"
    assert manifest["score"] == pytest.approx(0.5)
    assert manifest["model"] == "claude-opus-4-7"
    assert manifest["harness_commit"] == "abc123"
    assert len(manifest["tasks"]) == 2
    assert "task-002" in manifest["failed_task_samples"]

    t1 = manifest["tasks"][0]
    transcript_path = manifest_path.parent / t1["transcript_path"]
    lines = transcript_path.read_text().strip().splitlines()
    assert json.loads(lines[0]) == {"type": "user", "content": "do x"}
