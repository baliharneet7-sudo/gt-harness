from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from gt_engine.repository_graph_service import GraphStatus
from gt_harness.treatments import BareTreatment, GroundTruthTreatment
from nano.agent import Agent
from nano.providers import StepResult, ToolCall, Usage


class Provider:
    def __init__(self) -> None:
        self.messages = []
        self.calls = 0

    def step(self, messages, tools, system):
        self.messages.append(messages)
        self.calls += 1
        if self.calls == 1:
            return StepResult(
                text="",
                tool_calls=[ToolCall(id="1", name="bash", arguments={"command": "echo ok"})],
                stop_reason="tool_use",
                usage=Usage(input_tokens=1, output_tokens=1),
            )
        return StepResult(
            text="done",
            tool_calls=[],
            stop_reason="end_turn",
            usage=Usage(input_tokens=1, output_tokens=1),
        )


class Bash:
    def run(self, command: str, timeout: int = 60) -> str:
        assert command == "echo ok"
        return "ok"


def test_bare_treatment_is_a_strict_no_op() -> None:
    treatment = BareTreatment()
    assert treatment.prepare("task") == ""
    assert treatment.before_model_call(1) == ""
    assert treatment.after_action("bash", {"command": "x"}, "ok", False) is None
    assert treatment.finalize(None)["provider_calls"] == 0


def test_treatment_cannot_rewrite_or_block_agent_tool_action() -> None:
    class Treatment(BareTreatment):
        def prepare(self, task: str) -> str:
            return "repository fact"

        def after_action(self, name, arguments, output, is_error):
            self.observed = (name, dict(arguments), output, is_error)

    provider = Provider()
    treatment = Treatment()
    result = Agent(
        provider=provider,
        system="system",
        bash=Bash(),
        treatment=treatment,
        verify=False,
    ).run("task")

    assert result.stop_reason == "end_turn"
    assert treatment.observed == ("bash", {"command": "echo ok", "timeout": 60}, "ok", False)
    assert provider.messages[0][0]["content"] == "task\n\nrepository fact"


def test_groundtruth_failure_is_explicit_and_nonblocking(tmp_path: Path) -> None:
    root = tmp_path / "not-code"
    root.mkdir()
    treatment = GroundTruthTreatment(root)

    assert treatment.prepare("task") == ""
    receipt = treatment.finalize(None)
    assert receipt["treatment"] == "groundtruth"
    assert receipt["provider_calls"] == 0
    assert receipt["graph_available"] is False
    assert receipt["delivery_count"] == 0


def test_groundtruth_honors_private_state_directory(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "private-state"
    monkeypatch.setenv("GT_STATE_DIR", str(state))

    treatment = GroundTruthTreatment(tmp_path / "repository")

    assert treatment.service.state_dir == state.resolve()


def test_groundtruth_delivers_valid_composed_relationship_context(tmp_path: Path) -> None:
    class FakeReceipt:
        query_ready = True
        build_status = GraphStatus.READY
        repository = str(tmp_path)
        commit_sha = "a" * 40
        source_revision = "b" * 64
        graph_checksum_or_identity = "c" * 64
        degraded_reasons = ()

        def as_dict(self):
            return {"build_status": self.build_status.value, "query_ready": True}

    class FakeService:
        def status(self):
            return FakeReceipt()

        def query(self, mode, symbol, **_kwargs):
            if mode == "search" and symbol == "answer":
                return {
                    "evidence": [
                        {
                            "id": 1,
                            "label": "Function",
                            "name": "answer",
                            "qualified_name": "answer",
                            "file_path": "app.py",
                            "start_line": 1,
                        }
                    ]
                }
            if mode == "callers":
                return {
                    "evidence": [
                        {
                            "id": 2,
                            "label": "Function",
                            "name": "invoke",
                            "qualified_name": "invoke",
                            "file_path": "caller.py",
                            "start_line": 3,
                            "relationship": "CALLS",
                        }
                    ]
                }
            return {"evidence": []}

    treatment = GroundTruthTreatment(tmp_path)
    treatment.service = FakeService()
    treatment.task = "Change answer without breaking callers"

    rendered = treatment._render(update=False, budget=4_000, delivered_before_call=1)

    assert len(rendered) <= 4_000
    assert rendered.endswith("\n</groundtruth-repository-context>")
    payload = json.loads(rendered.splitlines()[1])
    assert payload["schema"] == "gt.agent_context.v2"
    assert any(row["query_mode"] == "callers" for row in payload["evidence"])


def test_official_bare_and_groundtruth_arms_use_the_identical_agent_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    import nano.agent
    import nano.cli
    from gt_harness.cli import _run_agent

    captures: list[dict[str, object]] = []

    class FakeAgent:
        def __init__(self, **kwargs):
            captures.append(kwargs)
            self.treatment = kwargs["treatment"]

        def run(self, _task: str):
            return SimpleNamespace(
                stop_reason="end_turn",
                iterations=1,
                total_input_tokens=10,
                total_output_tokens=2,
                total_cache_read_tokens=0,
                transcript=[
                    {"type": "assistant"},
                    {"type": "treatment_receipt", "receipt": self.treatment.finalize(None)},
                ],
            )

    monkeypatch.setattr(nano.agent, "Agent", FakeAgent)
    monkeypatch.setattr(nano.cli, "build_provider", lambda **_kwargs: object())
    common = {
        "task": "Fix the parser",
        "model": "provider/model",
        "base_url": "https://provider.invalid",
        "max_iterations": 30,
        "time_budget_seconds": 120.0,
        "root": str(tmp_path),
        "temperature": 0.0,
        "run_id": None,
        "output": None,
        "state_dir": None,
    }
    assert _run_agent(SimpleNamespace(**common, treatment="bare")) == 0
    assert _run_agent(SimpleNamespace(**common, treatment="groundtruth")) == 0

    assert captures[0]["system"] == captures[1]["system"]
    assert captures[0]["max_iterations"] == captures[1]["max_iterations"]
    assert captures[0]["time_budget_seconds"] == captures[1]["time_budget_seconds"]
    assert isinstance(captures[0]["treatment"], BareTreatment)
    assert isinstance(captures[1]["treatment"], GroundTruthTreatment)
    run_root = tmp_path / ".groundtruth" / "runs"
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in run_root.glob("*.json")]
    assert len(receipts) == 2
    assert {receipt["treatment"] for receipt in receipts} == {"bare", "groundtruth"}
    assert all(receipt["treatment_receipt_present"] for receipt in receipts)
    assert all(receipt["resolved"] is None for receipt in receipts)
    assert all(receipt["task_fingerprint"] for receipt in receipts)
    assert all(receipt["task_id"].startswith("task-") for receipt in receipts)
    assert all(receipt["trial_id"] == "1" for receipt in receipts)
    assert all(receipt["agent_scaffold"] == "nano.agent.Agent" for receipt in receipts)
    assert len({receipt["system_prompt_sha256"] for receipt in receipts}) == 1
    assert len({receipt["tool_policy_sha256"] for receipt in receipts}) == 1
    assert len({receipt["repository_start"]["source_revision"] for receipt in receipts}) == 1
