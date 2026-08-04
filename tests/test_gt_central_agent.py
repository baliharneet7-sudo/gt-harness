from __future__ import annotations

import inspect
import json
import time
from pathlib import Path

import pytest
from harbor.agents.base import BaseAgent
from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import ExecResult
from harbor.models.agent.context import AgentContext
from minisweagent.exceptions import FormatError

from eval.gt_central_agent import (
    MiniSweCentralAgent,
    MiniSweCentralShadowAgent,
    _message_context_chars,
)


class _Environment:
    default_user = "root"

    def __init__(self):
        self.commands: list[tuple[str, dict | None]] = []

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        self.commands.append((command, env))
        if command.startswith("uname "):
            return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
        if "-printf" in command:
            return ExecResult(stdout="", return_code=0)
        return ExecResult(stdout="", return_code=0)


class _ScriptedModel:
    config = type("Config", (), {"model_name": "test"})()

    def __init__(self, commands):
        self.commands = iter(commands)
        self.observed: list[str] = []
        self.observed_history: list[list[str]] = []

    def format_message(self, **kwargs):
        return kwargs

    def get_template_vars(self):
        return {
            "observation_template": "{{ output.output }}",
            "format_error_template": "error",
        }

    def query(self, messages):
        self.observed = [str(item.get("content") or "") for item in messages]
        self.observed_history.append(self.observed)
        command = next(self.commands)
        return {
            "role": "assistant",
            "content": "act",
            "extra": {
                "actions": [{"command": command, "tool_call_id": "call-1"}],
                "response": {
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    }
                },
                "cost": 0.0,
            },
        }

    def format_observation_messages(self, message, outputs, template_vars=None):
        return [{"role": "tool", "content": outputs[0]["output"]}]


def test_central_agent_is_host_owned_not_installed():
    assert issubclass(MiniSweCentralAgent, BaseAgent)
    assert not issubclass(MiniSweCentralAgent, BaseInstalledAgent)
    assert inspect.iscoroutinefunction(MiniSweCentralAgent.run)
    assert MiniSweCentralAgent.SUPPORTS_ATIF is True


@pytest.mark.asyncio
async def test_setup_does_not_install_or_upload_anything(tmp_path):
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test-model")
    environment = _Environment()

    await agent.setup(environment)

    assert environment.commands == []


def test_shadow_and_treatment_are_both_central_gt_on_arms(tmp_path):
    treatment = MiniSweCentralAgent(logs_dir=tmp_path / "a", model_name="test")
    shadow = MiniSweCentralShadowAgent(logs_dir=tmp_path / "b", model_name="test")

    assert treatment.runtime_mode == "treatment"
    assert shadow.runtime_mode == "shadow"
    assert treatment.name() == "miniswe-central"
    assert shadow.name() == "miniswe-central-shadow"


def test_context_accounting_includes_reasoning_and_tool_calls():
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": "reason",
        "tool_calls": [{"function": {"name": "bash", "arguments": '{"command":"pytest -q"}'}}],
    }

    assert _message_context_chars(message) > len("reason")


def test_paid_workflow_uses_external_central_agent_and_frozen_version():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tb2_miniswe_engine.yml"
    ).read_text(encoding="utf-8")

    assert 'AGENT="eval.gt_central_agent:MiniSweCentralAgent"' in workflow
    assert '--agent-import-path "$AGENT"' in workflow
    assert '-a "$AGENT"' not in workflow
    assert '"mini-swe-agent==2.2.8"' in workflow
    assert "eval.miniswe_agent:MiniSweEngineAgent" not in workflow
    assert "MiniSweCentralShadowAgent" in workflow
    assert "enable_lint=false" in workflow
    assert "enable_submit_readiness=false" in workflow


def test_paid_engine_workflow_has_no_time_censors():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tb2_miniswe_engine.yml"
    ).read_text(encoding="utf-8")

    # Benchmark treatment is bounded by step_limit and cost_limit only; no
    # wall-time or per-call time censors that can cut a hard task mid-run.
    assert "--ak enable_lint=true --ak enable_submit_readiness=true" in workflow
    assert "--ak model_timeout_sec" not in workflow
    assert "--ak model_loop_timeout_sec" not in workflow


@pytest.mark.asyncio
async def test_model_shell_receives_no_host_credentials_or_private_env(tmp_path):
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    environment = _Environment()
    context = AgentContext()

    class ScriptedModel:
        config = type("Config", (), {"model_name": "test"})()

        def format_message(self, **kwargs):
            return kwargs

        def get_template_vars(self):
            return {
                "observation_template": "{{ output.output }}",
                "format_error_template": "error",
            }

        def query(self, messages):
            return {
                "role": "assistant",
                "content": "submit",
                "extra": {
                    "actions": [
                        {
                            "command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                            "tool_call_id": "call-1",
                        }
                    ],
                    "response": {"usage": {}},
                    "cost": 0.0,
                },
            }

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [{"role": "tool", "content": outputs[0]["output"]}]

    agent._model_factory = lambda: ScriptedModel()
    await agent.run("do the task", environment, context)

    model_actions = [item for item in environment.commands if "COMPLETE_TASK" in item[0]]
    assert len(model_actions) == 1
    assert model_actions[0][1] in (None, {})
    assert not any(
        name.startswith("GT_") for _, env in environment.commands for name in (env or {})
    )


@pytest.mark.asyncio
async def test_actual_loop_tracks_edit_lints_and_submits_without_private_context(tmp_path):
    class StatefulEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.state = "empty"

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                if self.state == "empty":
                    raw = ""
                elif self.state == "bad":
                    raw = "f\t4\t2.0\t2.0\tapp.py\t\n"
                elif self.state == "good":
                    raw = "f\t3\t3.0\t3.0\tapp.py\t\n"
                else:
                    raw = "f\t5\t4.0\t4.0\tapp.py\t\n"
                return ExecResult(stdout=raw, return_code=0)
            if command.startswith("sha256sum"):
                return ExecResult(stdout=("a" * 64) + "  app.py\n", return_code=0)
            if "py_compile" in command:
                if self.state == "bad":
                    return ExecResult(stderr="SyntaxError: invalid syntax\n", return_code=1)
                return ExecResult(return_code=0)
            if command == "write bad":
                self.state = "bad"
                return ExecResult(return_code=0)
            if command == "write good":
                self.state = "good"
                return ExecResult(return_code=0)
            if command == "write better":
                self.state = "better"
                return ExecResult(return_code=0)
            if command == "pytest -q":
                return ExecResult(stdout="1 passed\n", return_code=0)
            if "COMPLETE_TASK" in command:
                return ExecResult(stdout="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", return_code=0)
            raise AssertionError(f"unexpected command: {command}")

    environment = StatefulEnvironment()
    model = _ScriptedModel(
        [
            "write bad",
            "write good",
            "write better",
            "pytest -q",
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model
    context = AgentContext()

    await agent.run("Fix it, then run `pytest -q`.", environment, context)

    trajectory = (tmp_path / "miniswe_trajectory.json").read_text(encoding="utf-8")
    assert not any("Runtime evidence:" in item for item in model.observed_history[0])
    assert any(
        "Runtime evidence: Syntax check failed for app.py" in item
        for item in model.observed_history[1]
    )
    assert not any(
        "Runtime evidence: Syntax check failed for app.py" in item
        for history in model.observed_history[2:]
        for item in history
    )
    assert any(
        "Unvalidated authored changes in app.py; declared check: pytest -q" in item
        for item in model.observed_history[3]
    )
    assert not any(
        "Unvalidated authored changes in app.py; declared check: pytest -q" in item
        for history in model.observed_history[4:]
        for item in history
    )
    # The durable trajectory stays clean; timing proof lives in receipt-v2.
    assert "Runtime evidence:" not in trajectory
    assert "groundtruth" not in trajectory.lower()
    assert "gt_" not in trajectory.lower()
    assert context.metadata["exit_status"] == "Submitted"
    assert context.n_input_tokens == 50
    assert context.n_output_tokens == 10
    atif = (tmp_path / "trajectory.json").read_text(encoding="utf-8")
    assert '"schema_version": "ATIF-v1.7"' in atif
    assert '"function_name": "bash"' in atif
    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    metrics = receipt["metrics"]
    assert metrics["total_tokens"] == metrics["input_tokens"] + metrics["output_tokens"]
    assert metrics["api_calls"] == context.metadata["api_calls"]
    assert metrics["actions"] == context.metadata["actions"]
    assert metrics["assistant_steps"] == context.metadata["assistant_steps"]
    assert metrics["trajectory_messages"] >= metrics["assistant_steps"]
    assert metrics["uncached_input_tokens"] == 50
    assert metrics["prompt_cache_hit_rate"] == 0.0
    assert metrics["normalized_cost_usd"] > 0
    assert metrics["tokens_per_call"] == 12.0
    assert metrics["tokens_per_assistant_step"] == 12.0
    assert metrics["actions_per_assistant_step"] == 1.0
    assert metrics["elapsed_seconds"] > 0
    assert metrics["successful_actions"] == 5
    assert metrics["failed_actions"] == 0
    assert metrics["check_actions"] == 1
    assert metrics["workspace_change_actions"] == 3
    assert metrics["lint_passes"] == 2
    assert metrics["lint_failures"] == 1
    assert metrics["guidance_candidates"] >= metrics["guidance_events"]
    assert metrics["guidance_suppressed"] >= 1
    deliveries = receipt["guidance_deliveries"]
    assert len(deliveries) == 2
    assert deliveries[0]["feature_id"] == "syntax_result"
    assert deliveries[0]["evidence_action"] == 1
    assert deliveries[0]["delivered_before_call"] == 2
    assert deliveries[0]["decision_window"] == "first_next_model_call"
    assert deliveries[0]["not_predictive"] is True
    assert deliveries[1]["feature_id"] == "GT_EDIT_CHECK"
    assert deliveries[1]["evidence_action"] == 3
    assert deliveries[1]["delivered_before_call"] == 4
    assert deliveries[1]["decision_window"] == "first_next_model_call"
    assert deliveries[1]["not_predictive"] is True
    contexts = receipt["model_call_contexts"]
    assert len(contexts) == metrics["api_calls"]
    assert contexts[1]["runtime_advisory_chars"] == deliveries[0]["chars"]
    assert contexts[1]["stock_context_chars"] > 0
    assert contexts[3]["runtime_advisory_chars"] == deliveries[1]["chars"]
    assert contexts[4]["runtime_advisory_chars"] == 0


@pytest.mark.asyncio
async def test_actual_agent_loop_routes_all_17_features_with_nonpredictive_effects(tmp_path):
    """Strict release proof: real agent lifecycle, not runtime-only fixtures."""

    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

    class AllFeatureEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.state = "empty"

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                rows = {
                    "empty": "f\t3\t0.0\t0.0\tapp.py\t\n",
                    "s1": (
                        "f\t4\t1.0\t1.0\tapp.py\t\n"
                        "f\t3\t1.0\t1.0\tnew_module.py\t\n"
                    ),
                    "s2": (
                        "f\t5\t2.0\t2.0\tapp.py\t\n"
                        "f\t3\t1.0\t1.0\tnew_module.py\t\n"
                    ),
                    "s3": (
                        "f\t6\t3.0\t3.0\tapp.py\t\n"
                        "f\t3\t1.0\t1.0\tnew_module.py\t\n"
                    ),
                }
                return ExecResult(stdout=rows[self.state], return_code=0)
            if command.startswith("sha256sum"):
                paths = [path for path in ("app.py", "new_module.py") if path in command]
                return ExecResult(
                    stdout="".join(("a" * 64) + f"  {path}\n" for path in paths),
                    return_code=0,
                )
            if command.startswith("rg "):
                return ExecResult(
                    stdout=(
                        "app.py:10:def f(x)\n"
                        "tests/test_app.py:20:caller references f; existing registry pattern\n"
                    ),
                    return_code=0,
                )
            if command.startswith("sed -i"):
                self.state = "s1"
                return ExecResult(return_code=0)
            if command == "write update-1":
                self.state = "s2"
                return ExecResult(return_code=0)
            if command == "write update-2":
                self.state = "s3"
                return ExecResult(return_code=0)
            if "py_compile" in command:
                if self.state == "s1":
                    return ExecResult(stderr="SyntaxError: invalid syntax\n", return_code=1)
                return ExecResult(return_code=0)
            if command == "pytest -q":
                return ExecResult(stdout="1 failed: assertion error\n", return_code=1)
            if command == submit:
                return ExecResult(stdout=submit + "\n", return_code=0)
            raise AssertionError(f"unexpected command: {command}")

    model = _ScriptedModel(
        [
            "rg -n 'f|caller' .",
            "sed -i 's/def f(x)/def f(x, y)/' app.py",
            "write update-1",
            "write update-2",
            "pytest -q",
            "pytest -q",
            submit,
            submit,
        ]
    )
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model

    await agent.run(
        "Fix f, then run `pytest -q` before submitting.",
        AllFeatureEnvironment(),
        AgentContext(),
    )

    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    features = receipt["features"]
    assert set(features["consumer_paths"]) == set(features["feature_ids"])
    assert {row["feature_id"] for row in features["receipts"]} == set(features["feature_ids"])
    assert {row["feature_id"] for row in features["effects"]} == set(features["feature_ids"])
    assert {
        row["feature_id"]
        for row in features["effect_applications"]
        if row["state_fields_changed"]
    } == set(features["feature_ids"])
    assert all(row["evidence_before_effect"] for row in features["effects"])
    assert all(row["effect_before_next_action"] for row in features["effects"])
    assert all(row["non_late"] and not row["predictive"] for row in features["effects"])
    assert all(
        row["not_predictive"]
        and row["delivered_before_model_query"]
        and not row["one_step_late"]
        and row["delivered_before_call"] == row["first_eligible_call"]
        and row["request_payload_sha256"]
        == receipt["model_call_contexts"][row["delivered_before_call"] - 1][
            "request_payload_sha256"
        ]
        for row in receipt["guidance_deliveries"]
    )
    assert features["action_metrics"]["submit_holds"] == 0
    assert features["action_metrics"]["batch_interrupts"] == 0
    assert features["action_metrics"]["interrupted_actions"] == 0


@pytest.mark.asyncio
async def test_grounded_failure_warns_before_submit_without_holding_it(tmp_path):
    class CheckEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command == "pytest -q":
                return ExecResult(stdout="failed\n", return_code=1)
            if "COMPLETE_TASK" in command:
                return ExecResult(stdout="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", return_code=0)
            raise AssertionError(command)

    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    environment = CheckEnvironment()
    # The spare third response keeps the RED witness finite under the old
    # submit-hold implementation.  The repaired loop must terminate after the
    # first submit and therefore issue only two model calls.
    model = _ScriptedModel(["pytest -q", submit, submit])
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model

    await agent.run("Run `pytest -q` before finishing.", environment, AgentContext())

    executed_submits = [command for command, _ in environment.commands if command == submit]
    assert executed_submits == [submit]
    assert len(model.observed_history) == 2
    assert any("pytest -q" in item for item in model.observed_history[1])
    trajectory = (tmp_path / "miniswe_trajectory.json").read_text(encoding="utf-8")
    assert "Submit again to continue without another hold" not in trajectory
    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    assert receipt["metrics"]["submit_holds"] == 0


@pytest.mark.asyncio
async def test_format_error_is_returned_to_model_instead_of_aborting(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

    class RecoveringModel(_ScriptedModel):
        def __init__(self):
            super().__init__([submit])
            self.queries = 0

        def query(self, messages):
            self.queries += 1
            if self.queries == 1:
                raise FormatError({"role": "user", "content": "Use the bash tool correctly."})
            return super().query(messages)

    class Environment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command == submit:
                return ExecResult(stdout="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", return_code=0)
            raise AssertionError(command)

    model = RecoveringModel()
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model

    await agent.run("do it", Environment(), AgentContext())

    assert model.queries == 2
    trajectory = (tmp_path / "miniswe_trajectory.json").read_text(encoding="utf-8")
    assert "Use the bash tool correctly" in trajectory


@pytest.mark.asyncio
async def test_model_timeout_writes_a_censored_partial_receipt(tmp_path):
    class SlowModel(_ScriptedModel):
        def query(self, messages):
            time.sleep(0.05)
            return super().query(messages)

    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        model_timeout_sec=0.001,
    )
    agent._model_factory = lambda: SlowModel(["echo never-executed"])
    context = AgentContext()

    await agent.run("do it", _Environment(), context)

    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == "central-runtime-receipt-v3"
    assert receipt["metrics"]["censored"] is True
    assert receipt["metrics"]["censored_reason"] == "model_request_timeout"
    assert receipt["metrics"]["actions"] == 0
    assert context.metadata["exit_status"] == "ModelTimeout"


@pytest.mark.asyncio
async def test_syntax_failure_does_not_interrupt_multi_action_batch(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

    class MultiActionModel:
        config = type("Config", (), {"model_name": "test"})()
        queries = 0
        observed_history: list[list[str]] = []

        def format_message(self, **kwargs):
            return kwargs

        def get_template_vars(self):
            return {
                "observation_template": "{{ output.output }}",
                "format_error_template": "error",
            }

        def query(self, messages):
            type(self).queries += 1
            type(self).observed_history.append(
                [str(item.get("content") or "") for item in messages]
            )
            if type(self).queries == 1:
                return {
                    "role": "assistant",
                    "content": "act",
                    "extra": {
                        "actions": [
                            {"command": "write broken", "tool_call_id": "call-1"},
                            {"command": "echo MUST_NOT_EXECUTE", "tool_call_id": "call-2"},
                            {"command": "echo ALSO_MUST_NOT_EXECUTE", "tool_call_id": "call-3"},
                        ],
                        "response": {
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 2,
                                "total_tokens": 12,
                            }
                        },
                        "cost": 0.0,
                    },
                }
            return {
                "role": "assistant",
                "content": "submit",
                "extra": {
                    "actions": [{"command": submit, "tool_call_id": "call-4"}],
                    "response": {
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                            "total_tokens": 12,
                        }
                    },
                    "cost": 0.0,
                },
            }

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [
                {"role": "tool", "content": outputs[i]["output"]} for i in range(len(outputs))
            ]

    class InterruptEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.state = "empty"

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                if self.state == "empty":
                    raw = ""
                elif self.state == "bad":
                    raw = "f\t4\t2.0\t2.0\tapp.py\t\n"
                else:
                    raw = "f\t3\t3.0\t3.0\tapp.py\t\n"
                return ExecResult(stdout=raw, return_code=0)
            if command.startswith("sha256sum"):
                return ExecResult(stdout=("a" * 64) + "  app.py\n", return_code=0)
            if "py_compile" in command:
                if self.state == "bad":
                    return ExecResult(stderr="SyntaxError: invalid syntax\n", return_code=1)
                return ExecResult(return_code=0)
            if command == "write broken":
                self.state = "bad"
                return ExecResult(return_code=0)
            if command in {"echo MUST_NOT_EXECUTE", "echo ALSO_MUST_NOT_EXECUTE"}:
                return ExecResult(stdout=command + "\n", return_code=0)
            if command == submit:
                return ExecResult(stdout=submit + "\n", return_code=0)
            raise AssertionError(f"unexpected command: {command}")

    environment = InterruptEnvironment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_submit_readiness=False,
    )
    agent._model_factory = lambda: MultiActionModel()
    context = AgentContext()

    await agent.run("Fix the syntax error.", environment, context)

    executed = [
        command
        for command, _ in environment.commands
        if not command.startswith("uname")
        and "-printf" not in command
        and not command.startswith("sha256sum")
        and not command.startswith("python3 -c")
        and "py_compile" not in command
    ]
    assert executed == [
        "write broken",
        "echo MUST_NOT_EXECUTE",
        "echo ALSO_MUST_NOT_EXECUTE",
        submit,
    ]
    assert not any(
        "Syntax check failed for app.py" in item
        for item in MultiActionModel.observed_history[0]
    )
    assert any(
        "Syntax check failed for app.py" in item
        for item in MultiActionModel.observed_history[1]
    )
    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    assert receipt["metrics"]["batch_interrupts"] == 0
    assert receipt["metrics"]["interrupted_actions"] == 0
    assert receipt["features"]["batch_interrupts"] == []
    syntax_effect = next(
        effect
        for effect in receipt["features"]["effects"]
        if effect["feature_id"] == "syntax_result"
    )
    assert syntax_effect["predecided_actions_cancelled"] == 0
    assert syntax_effect["predecided_actions_executed_after_evidence"] == 2
    assert receipt["guidance_deliveries"][0]["delivered_before_call"] == 2
    assert receipt["guidance_deliveries"][0]["first_eligible_call"] == 2
    assert receipt["guidance_deliveries"][0]["delivered_before_model_query"] is True
    assert context.metadata["exit_status"] == "Submitted"
