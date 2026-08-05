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
from gt_engine.preflight import (
    ActionDisposition,
    PreflightDecision,
    PreflightMode,
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


class _BatchModel(_ScriptedModel):
    def __init__(self, batches):
        self.batches = iter(batches)
        self.observed = []
        self.observed_history = []

    def query(self, messages):
        self.observed = [str(item.get("content") or "") for item in messages]
        self.observed_history.append(self.observed)
        commands = next(self.batches)
        return {
            "role": "assistant",
            "content": "act",
            "extra": {
                "actions": [
                    {"command": command, "tool_call_id": f"call-{index}"}
                    for index, command in enumerate(commands, 1)
                ],
                "response": {"usage": {}},
                "cost": 0.0,
            },
        }

    def format_observation_messages(self, message, outputs, template_vars=None):
        actions = message["extra"]["actions"]
        assert len(outputs) == len(actions)
        return [
            {
                "role": "tool",
                "tool_call_id": action["tool_call_id"],
                "content": output["output"],
            }
            for action, output in zip(actions, outputs, strict=True)
        ]


class _ObservedMutationEnvironment(_Environment):
    def __init__(self, mutation_command: str, manifest_after: str):
        super().__init__()
        self.mutation_command = mutation_command
        self.manifest_after = manifest_after
        self.changed = False

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        self.commands.append((command, env))
        if command.startswith("uname "):
            return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
        if "-printf" in command:
            return ExecResult(
                stdout=self.manifest_after if self.changed else "", return_code=0
            )
        if command.startswith("sha256sum"):
            paths = [word for word in command.split() if word.endswith(".py")]
            return ExecResult(
                stdout="".join(("a" * 64) + f"  {path}\n" for path in paths),
                return_code=0,
            )
        if command.startswith("python3 -c"):
            return ExecResult(stdout='{"app.py":"eCA9IDEK"}\n', return_code=0)
        if command == self.mutation_command:
            self.changed = True
        return ExecResult(return_code=0)


@pytest.mark.asyncio
async def test_source_backed_localization_reaches_first_provider_call(tmp_path):
    class TransferEnvironment(_Environment):
        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            root = Path(target_dir)
            (root / "src").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
            (root / "src" / "greeter.py").write_text(
                "def greet(name: str) -> str:\n    return f'hello {name}'\n"
            )

    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_task_start_advisory=True,
    )
    agent._model_factory = lambda: model

    await agent.run(
        "Change greet so it returns an uppercase greeting.",
        TransferEnvironment(),
        AgentContext(),
    )

    assert len(model.observed_history) == 1
    assert any("src/greeter.py" in item for item in model.observed_history[0])
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    evidence = receipt["repository_evidence"]
    assert evidence["available"] is True
    delivery = receipt["guidance_deliveries"][0]
    assert delivery["evidence_action"] == 0
    assert delivery["delivered_before_call"] == 1
    assert delivery["one_step_late"] is False
    assert delivery["not_predictive"] is True


@pytest.mark.asyncio
async def test_preflight_spy_runs_before_selected_command_executes(tmp_path):
    events = []

    class OrderedEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            if command == "cat src/app.py":
                events.append("exec")
            return await super().exec(command, cwd, env, timeout_sec, user)

    model = _ScriptedModel(["cat src/app.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test", enable_preflight=True)
    agent._model_factory = lambda: model
    original = agent._features.preflight_action

    def ordered_preflight(*args, **kwargs):
        events.append("preflight")
        return original(*args, **kwargs)

    agent._features.preflight_action = ordered_preflight
    await agent.run("Read app.py.", OrderedEnvironment(), AgentContext())

    assert events[:2] == ["preflight", "exec"]


@pytest.mark.asyncio
async def test_material_edit_preflight_returns_then_revised_edit_executes(tmp_path):
    class RevisionEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.edited = False
            self.executed_edits = []

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                size = 4 if self.edited else 3
                stamp = "2.0" if self.edited else "1.0"
                return ExecResult(stdout=f"f\t{size}\t{stamp}\t{stamp}\tapp.py\t\n", return_code=0)
            if command.startswith("sha256sum"):
                return ExecResult(
                    stdout=("b" if self.edited else "a") * 64 + "  app.py\n",
                    return_code=0,
                )
            if command.startswith("python3 -c"):
                return ExecResult(stdout='{"app.py":"eCA9IDEK"}\n', return_code=0)
            if command.startswith("sed -i"):
                self.executed_edits.append(command)
                self.edited = True
                return ExecResult(stdout="", return_code=0)
            if "COMPLETE_TASK" in command:
                return ExecResult(stdout="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", return_code=0)
            return ExecResult(stdout="", return_code=0)

    environment = RevisionEnvironment()
    first = "sed -i 's/x/y/' app.py"
    revised = "sed -i 's/x/z/' app.py"
    model = _ScriptedModel([first, revised, "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_preflight=True,
        enable_lint=False,
    )
    agent._model_factory = lambda: model
    real_preflight = agent._features.preflight_action
    returned = False

    def material_once(proposed, *args, **kwargs):
        nonlocal returned
        if not returned and proposed.raw_command == first:
            returned = True
            return PreflightDecision(
                ActionDisposition.RETURN_TO_MODEL,
                proposed.raw_command,
                evidence=("Exact target has a material coupled-file risk.",),
                reason_codes=("material_edit_risk",),
                confidence=1.0,
                source_revision=proposed.source_revision,
            )
        return real_preflight(proposed, *args, **kwargs)

    agent._features.preflight_action = material_once
    await agent.run("Change app.py.", environment, AgentContext())

    assert environment.executed_edits == [revised]
    assert any("material coupled-file risk" in item for item in model.observed_history[1])
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["features"]["action_metrics"]["workspace_change_actions"] == 1


@pytest.mark.asyncio
async def test_real_missing_edit_producer_returns_before_exec_then_revised_edit_runs(tmp_path):
    class ExistingFileEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.executed_edits: list[str] = []
            self.edited = False

        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            Path(target_dir, "app.py").write_text("x = 1\n")

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                size = 6
                stamp = "2.0" if self.edited else "1.0"
                return ExecResult(
                    stdout=f"f\t{size}\t{stamp}\t{stamp}\tapp.py\t\n",
                    return_code=0,
                )
            if command.startswith("sha256sum"):
                digest = "b" if self.edited else "a"
                return ExecResult(stdout=(digest * 64) + "  app.py\n", return_code=0)
            if command.startswith("python3 -c"):
                encoded = "eCA9IDIK" if self.edited else "eCA9IDEK"
                return ExecResult(stdout=f'{{"app.py":"{encoded}"}}\n', return_code=0)
            if command.startswith("sed -i"):
                self.executed_edits.append(command)
                self.edited = True
                return ExecResult(return_code=0)
            if "COMPLETE_TASK" in command:
                return ExecResult(stdout="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", return_code=0)
            return ExecResult(return_code=0)

    first = "sed -i 's/x/y/' missing.py"
    revised = "sed -i 's/x/y/' app.py"
    model = _ScriptedModel([first, revised, "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    environment = ExistingFileEnvironment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
        enable_lint=False,
    )
    agent._model_factory = lambda: model

    await agent.run("Edit app.py.", environment, AgentContext())

    assert environment.executed_edits == [revised]
    assert any("missing.py" in item for item in model.observed_history[1])
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    cycles = receipt["features"]["action_cycles"]
    first_cycle = next(row for row in cycles if row["proposed"]["raw_command"] == first)
    assert first_cycle["applied_disposition"] == "return_to_model"
    assert first_cycle["executed"] is False
    revised_cycle = next(row for row in cycles if row["proposed"]["raw_command"] == revised)
    assert revised_cycle["executed"] is True
    assert revised_cycle["postflight"]["source_revision"]
    session = receipt["repository_session"]
    assert session["fresh"] is True
    assert len(session["refresh_log"]) == 2
    assert session["source_revision"] == receipt["source_revision"]
    assert receipt["metrics"]["preflight_commands_returned_to_model"] == 1
    assert receipt["metrics"]["preflight_commands_changed_after_return"] == 1


@pytest.mark.asyncio
async def test_shadow_records_material_candidate_but_executes_original(tmp_path):
    model = _ScriptedModel(
        [
            "sed -i 's/x/y/' missing.py",
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.SHADOW,
        enable_lint=False,
    )
    agent._model_factory = lambda: model

    await agent.run("Edit a file.", environment, AgentContext())

    assert any(command.startswith("sed -i") for command, _ in environment.commands)
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    cycle = next(
        row
        for row in receipt["features"]["action_cycles"]
        if row["proposed"]["raw_command"].startswith("sed -i")
    )
    assert cycle["candidate_decision"]["disposition"] == "return_to_model"
    assert cycle["applied_disposition"] == "pass"
    assert cycle["executed"] is True


@pytest.mark.asyncio
async def test_off_and_shadow_dispatch_identical_model_commands(tmp_path):
    commands = ["cat app.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
    off_model = _ScriptedModel(commands)
    shadow_model = _ScriptedModel(commands)
    off_environment = _Environment()
    shadow_environment = _Environment()
    off = MiniSweCentralAgent(
        logs_dir=tmp_path / "off",
        model_name="test",
        preflight_mode=PreflightMode.OFF,
    )
    shadow = MiniSweCentralAgent(
        logs_dir=tmp_path / "shadow",
        model_name="test",
        preflight_mode=PreflightMode.SHADOW,
    )
    off._model_factory = lambda: off_model
    shadow._model_factory = lambda: shadow_model

    await off.run("Read app.py.", off_environment, AgentContext())
    await shadow.run("Read app.py.", shadow_environment, AgentContext())

    off_selected = [
        command
        for command, _ in off_environment.commands
        if "-printf" not in command and not command.startswith("uname ")
    ]
    shadow_selected = [
        command
        for command, _ in shadow_environment.commands
        if "-printf" not in command and not command.startswith("uname ")
    ]
    assert shadow_selected == off_selected
    off_receipt = json.loads((tmp_path / "off" / "central_receipt.json").read_text())
    shadow_receipt = json.loads((tmp_path / "shadow" / "central_receipt.json").read_text())
    assert off_receipt["features"]["action_cycles"] == []
    assert len(shadow_receipt["features"]["action_cycles"]) == 2


@pytest.mark.asyncio
async def test_preflight_timeout_is_recorded_and_fails_open(tmp_path):
    model = _ScriptedModel(["cat app.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
        preflight_timeout_sec=0.001,
    )
    agent._model_factory = lambda: model

    def slow_preflight(*args, **kwargs):
        time.sleep(0.03)
        raise AssertionError("result should be ignored after timeout")

    agent._features.preflight_action = slow_preflight
    await agent.run("Read app.py.", environment, AgentContext())

    assert any(command == "cat app.py" for command, _ in environment.commands)
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    cycle = next(
        row
        for row in receipt["features"]["action_cycles"]
        if row["proposed"]["raw_command"] == "cat app.py"
    )
    assert "preflight_timeout" in cycle["candidate_decision"]["reason_codes"]
    assert cycle["applied_disposition"] == "pass"
    assert cycle["executed"] is True


@pytest.mark.asyncio
async def test_rewrite_is_never_dispatched_in_assistive_safe_mode(tmp_path):
    original = "cat app.py"
    rewritten = "rm app.py"
    model = _ScriptedModel([original, "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
    )
    agent._model_factory = lambda: model
    real_preflight = agent._features.preflight_action

    def unsafe_rewrite(proposed, *args, **kwargs):
        if proposed.raw_command != original:
            return real_preflight(proposed, *args, **kwargs)
        return PreflightDecision(
            ActionDisposition.REWRITE,
            rewritten,
            evidence=("claimed equivalent",),
            reason_codes=("rewrite_candidate",),
            confidence=1.0,
            source_revision=proposed.source_revision,
        )

    agent._features.preflight_action = unsafe_rewrite
    await agent.run("Read app.py.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert original in commands
    assert rewritten not in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    cycle = next(
        row
        for row in receipt["features"]["action_cycles"]
        if row["proposed"]["raw_command"] == original
    )
    assert "rewrite_disabled" in cycle["applied_reason_codes"]


@pytest.mark.asyncio
async def test_assistive_safe_keeps_read_only_batch_and_pairs_every_output(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    model = _BatchModel([["cat a.py", "rg -n x src"], [submit]])
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the files.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert "cat a.py" in commands
    assert "rg -n x src" in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["stale_batched_actions_prevented"] == 0


@pytest.mark.asyncio
async def test_successful_unknown_without_material_change_does_not_split_batch(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    model = _BatchModel([["pwd", "cat a.py"], [submit]])
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the workspace.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert "pwd" in commands
    assert "cat a.py" in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["stale_batched_actions_prevented"] == 0


@pytest.mark.asyncio
async def test_unclassified_exploration_failure_alone_does_not_split_batch(tmp_path):
    class ExplorationEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command == "ls missing":
                return ExecResult(stderr="not found\n", return_code=1)
            return ExecResult(return_code=0)

    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    model = _BatchModel([["ls missing", "cat a.py"], [submit]])
    environment = ExplorationEnvironment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the workspace.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert "ls missing" in commands
    assert "cat a.py" in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["stale_batched_actions_prevented"] == 0


@pytest.mark.asyncio
async def test_assistive_safe_breaks_mutating_batch_before_stale_second_action(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    model = _BatchModel([["touch app.py", "rm app.py"], [submit]])
    environment = _ObservedMutationEnvironment(
        "touch app.py", "f\t6\t2.0\t2.0\tapp.py\t\n"
    )
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
        enable_lint=False,
    )
    agent._model_factory = lambda: model

    await agent.run("Create app.py.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert "touch app.py" in commands
    assert "rm app.py" not in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["stale_batched_actions_prevented"] == 1
    assert receipt["features"]["batch_interrupts"][0]["reason"] == "stale_batch_barrier"
    cancelled = next(
        row
        for row in receipt["features"]["action_cycles"]
        if row["proposed"]["raw_command"] == "rm app.py"
    )
    assert cancelled["executed"] is False
    assert cancelled["postflight"]["status"] == "cancelled_before_dispatch"


@pytest.mark.asyncio
async def test_compound_mutating_action_breaks_batch_after_observed_directory_change(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    model = _BatchModel([["mkdir -p work && echo made", "cat work/result"], [submit]])
    environment = _ObservedMutationEnvironment(
        "mkdir -p work && echo made", "d\t0\t2.0\t2.0\twork\t\n"
    )
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
    )
    agent._model_factory = lambda: model

    await agent.run("Create the work directory.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert "mkdir -p work && echo made" in commands
    assert "cat work/result" not in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["stale_batched_actions_prevented"] == 1


@pytest.mark.asyncio
async def test_terminal_submit_pairs_and_cancels_predecided_suffix(tmp_path):
    submit = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    model = _BatchModel([[submit, "rm app.py"]])
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        preflight_mode=PreflightMode.ASSISTIVE_SAFE,
    )
    agent._model_factory = lambda: model

    await agent.run("Finish the task.", environment, AgentContext())

    commands = [command for command, _ in environment.commands]
    assert submit in commands
    assert "rm app.py" not in commands
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    cancelled = next(
        row
        for row in receipt["features"]["action_cycles"]
        if row["proposed"]["raw_command"] == "rm app.py"
    )
    assert cancelled["postflight"]["reason"] == "terminal_submit"


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
    assert "preflight_mode=shadow" in workflow
    assert "enable_preflight=true" not in workflow


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
                    "s1": ("f\t4\t1.0\t1.0\tapp.py\t\nf\t3\t1.0\t1.0\tnew_module.py\t\n"),
                    "s2": ("f\t5\t2.0\t2.0\tapp.py\t\nf\t3\t1.0\t1.0\tnew_module.py\t\n"),
                    "s3": ("f\t6\t3.0\t3.0\tapp.py\t\nf\t3\t1.0\t1.0\tnew_module.py\t\n"),
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
        row["feature_id"] for row in features["effect_applications"] if row["state_fields_changed"]
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
            return [{"role": "tool", "content": outputs[i]["output"]} for i in range(len(outputs))]

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
        "Syntax check failed for app.py" in item for item in MultiActionModel.observed_history[0]
    )
    assert any(
        "Syntax check failed for app.py" in item for item in MultiActionModel.observed_history[1]
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
