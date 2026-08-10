from __future__ import annotations

import hashlib
import inspect
import io
import json
import tarfile
import time
from pathlib import Path

import pytest
from harbor.agents.base import BaseAgent
from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import ExecResult
from harbor.models.agent.context import AgentContext
from minisweagent.exceptions import FormatError

from eval.gt_central_agent import (
    GTIntegrationMode,
    MiniSweCentralAgent,
    MiniSweCentralShadowAgent,
    _graph_gate_degraded_fallback,
    _message_context_chars,
    _partition_recovered_repository_failures,
    _stable_provider_prefix,
)
from gt_engine.central_runtime import (
    FileState,
    WorkspaceSnapshot,
    WorkspaceTransition,
    classify_validation_command,
)
from gt_engine.preflight import (
    ActionDisposition,
    PreflightDecision,
    PreflightMode,
    adapt_proposed_action,
)
from gt_engine.repository_intelligence import RepositoryEvidence, RepositorySession
from gt_engine.uplift_policy import GTPolicyMode


def test_recovered_frontier_failure_is_receipted_but_not_current_failure():
    current, transient = _partition_recovered_repository_failures(
        [
            {
                "source_revision": "r1",
                "disposition": "substrate_failure",
            },
            {
                "source_revision": "r1",
                "disposition": "no_frontier",
            },
        ],
        current_source_revision="r1",
        failure_values=frozenset({"substrate_failure", "stale_source_revision"}),
        prefix="frontier",
    )

    assert current == []
    assert transient == ["frontier:substrate_failure"]


def test_current_frontier_failure_remains_fail_closed():
    current, transient = _partition_recovered_repository_failures(
        [
            {
                "source_revision": "r1",
                "disposition": "substrate_failure",
            }
        ],
        current_source_revision="r1",
        failure_values=frozenset({"substrate_failure", "stale_source_revision"}),
        prefix="frontier",
    )

    assert current == ["frontier:substrate_failure"]
    assert transient == []


def test_recovered_initial_graph_failure_does_not_remain_degraded():
    """A transient pre-source snapshot must not invalidate a later fresh graph."""

    assert _graph_gate_degraded_fallback(
        initial_failures=("no_supported_source", "graph_missing"),
        current_failures=(),
    ) is False
    assert _graph_gate_degraded_fallback(
        initial_failures=("no_supported_source",),
        current_failures=("graph_not_current",),
    ) is True


def test_merge_gate_does_not_promote_recovered_transient_repository_failures():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "tb2_miniswe_central.yml"
    ).read_text(encoding="utf-8")
    merge_block = workflow[
        workflow.index("invalid_intelligence = [") : workflow.index("out = [")
    ]
    assert "repository_intelligence_transient_failures" not in merge_block


def test_recovered_refresh_failure_is_not_current_failure():
    current, transient = _partition_recovered_repository_failures(
        [
            {"source_revision": "r1", "status": "sensor_degraded"},
            {"source_revision": "r1", "status": "source_backed"},
        ],
        current_source_revision="r1",
        failure_values=frozenset({"sensor_degraded", "index_unavailable"}),
        prefix="repository_refresh",
    )

    assert current == []
    assert transient == ["repository_refresh:sensor_degraded"]


class _Environment:
    default_user = "root"

    def __init__(self):
        self.commands: list[tuple[str, dict | None]] = []

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        self.commands.append((command, env))
        if command == "pwd -P":
            return ExecResult(stdout="/app\n", return_code=0)
        if command.startswith("uname "):
            return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
        if "-printf" in command:
            return ExecResult(stdout="", return_code=0)
        return ExecResult(stdout="", return_code=0)


@pytest.mark.asyncio
async def test_default_cwd_is_resolved_from_environment_not_assumed_app(tmp_path):
    class RootEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            if command == "pwd -P":
                self.commands.append((command, env))
                return ExecResult(stdout="/root\n", return_code=0)
            return await super().exec(command, cwd, env, timeout_sec, user)

    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")

    resolved = await agent._resolve_cwd(RootEnvironment())

    assert resolved == "/root"
    assert agent.cwd == "/root"


@pytest.mark.asyncio
async def test_invalid_configured_cwd_falls_back_to_inherited_environment_cwd(tmp_path):
    class RootEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            if cwd == "/app":
                raise RuntimeError("configured cwd does not exist")
            if command == "pwd -P":
                return ExecResult(stdout="/root\n", return_code=0)
            if command.startswith("test -d "):
                return ExecResult(return_code=1)
            return await super().exec(command, cwd, env, timeout_sec, user)

    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test", cwd="/app")

    resolved = await agent._resolve_cwd(RootEnvironment())

    assert resolved == "/root"
    assert agent._cwd_receipt["status"] == "invalid_configured_fallback"


@pytest.mark.asyncio
async def test_oversized_changed_source_is_hydrated_and_digest_verified(tmp_path):
    payload = ("def generated():\n    return 1\n" * 12_000).encode()
    digest = hashlib.sha256(payload).hexdigest()

    class DownloadEnvironment:
        async def download_file(self, source_path, target_path):
            Path(target_path).write_bytes(payload)

    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test", cwd="/workspace")
    session = RepositorySession.temporary(instruction="Implement generated.py")
    transition = WorkspaceTransition(
        action_id=1,
        command="write generated.py",
        before_revision="w0",
        after_revision="w1",
        created=("generated.py",),
        after_contents={},
    )
    snapshot = WorkspaceSnapshot(
        revision="w1",
        healthy=True,
        entries={
            "generated.py": FileState(
                "f", len(payload), "1", "1", "", digest=digest, content=None
            )
        },
    )

    try:
        hydrated = await agent._hydrate_graph_transition(
            DownloadEnvironment(),
            session,
            transition,
            snapshot=snapshot,
            changed_paths=("generated.py",),
            source_revision="g1",
        )
    finally:
        session.close()

    assert hydrated.after_contents["generated.py"].startswith("def generated")
    receipt = agent._repository_work_receipts[-1]
    assert receipt["kind"] == "incremental_source_transfer"
    assert receipt["status"] == "complete"
    assert receipt["digest_verified"] is True


def test_stable_provider_prefix_counts_only_exact_append_stable_messages():
    previous = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "reasoning-a"},
    ]
    appended = [*previous, {"role": "tool", "content": "result"}]
    count, chars, ratio = _stable_provider_prefix(previous, appended)

    assert count == 3
    assert chars > 0
    assert 0.0 < ratio < 1.0

    changed = [dict(previous[0]), {"role": "user", "content": "changed"}]
    assert _stable_provider_prefix(previous, changed)[0] == 1


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
            return ExecResult(stdout=self.manifest_after if self.changed else "", return_code=0)
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
        enable_context_frontier=False,
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
    assert receipt["metrics"]["semantic_utilization_deliveries"] == 1
    assert receipt["metrics"]["semantic_utilization_no_match"] == 1


@pytest.mark.asyncio
async def test_opt_in_replay_capture_is_receipted_without_changing_request(tmp_path):
    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_replay_capture=True,
        enable_repository_intelligence=False,
    )
    agent._model_factory = lambda: model

    await agent.run("Complete the task.", _Environment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    metadata = receipt["replay_bundle"]
    assert metadata["enabled"] is True
    assert metadata["request_bodies_captured"] is True
    assert metadata["responses_captured"] is True
    assert metadata["trajectory_replay_ready"] is True
    assert metadata["model_causal_replay_ready"] is False
    manifest = json.loads((tmp_path / "gt_replay" / "manifest.json").read_text())
    calls = (tmp_path / "gt_replay" / "calls.jsonl").read_text().splitlines()
    assert manifest["schema"] == "gt.counterfactual_replay_bundle.v2"
    assert calls


@pytest.mark.asyncio
async def test_context_frontier_advances_repository_intelligence_without_feature_advisory(
    tmp_path,
):
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
        enable_task_start_advisory=False,
        enable_context_frontier=True,
    )
    agent._model_factory = lambda: model

    await agent.run(
        "Ensure greet returns an uppercase greeting.",
        TransferEnvironment(),
        AgentContext(),
    )

    first_request = "\n".join(model.observed_history[0])
    assert "Repository intelligence" in first_request
    assert "src/greeter.py" in first_request
    assert "def greet(name: str) -> str" in first_request
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    intelligence = receipt["repository_intelligence"]
    assert intelligence["status"] == "passed"
    assert len(intelligence["frontier_deliveries"]) == 1
    delivery = intelligence["frontier_deliveries"][0]
    assert delivery["delivered_before_call"] == 1
    assert (
        delivery["request_payload_sha256"]
        == receipt["model_call_contexts"][0]["request_payload_sha256"]
    )
    assert delivery["behavioral_relation"] == "submit_action"
    assert delivery["anchor_followed"] is False
    assert delivery["certified_opportunity"]["certified"] is True
    assert receipt["metrics"]["repository_intelligence_valid"] == 1
    assert receipt["metrics"]["repository_graph_schema_valid"] == 1
    assert receipt["metrics"]["repository_graph_nodes"] > 0
    assert receipt["metrics"]["context_frontier_chars_added"] > 0
    assert receipt["metrics"]["semantic_utilization_deliveries"] == 1
    assert receipt["metrics"]["semantic_utilization_no_match"] == 1
    assert receipt["metrics"]["context_frontier_zero_tasks"] == 0
    assert receipt["metrics"]["repository_mirror_files"] == 2
    assert receipt["metrics"]["repository_mirror_bytes"] > 0
    assert receipt["metrics"]["repository_mirror_transfer_ms"] >= 0
    assert receipt["metrics"]["repository_index_refresh_ms"] > 0
    assert receipt["metrics"]["repository_full_refreshes"] == 1
    assert [row["kind"] for row in receipt["repository_work_receipts"]] == [
        "mirror_transfer",
        "initial_index",
    ]


@pytest.mark.asyncio
async def test_context_frontier_exposes_path_only_evidence_without_symbol_leak(tmp_path):
    """A path need receives a location without an unrequested ranked symbol."""

    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_task_start_advisory=False,
        enable_context_frontier=True,
    )
    agent._model_factory = lambda: model

    async def fake_repository_session(*args, **kwargs):
        return (
            RepositoryEvidence(
                available=True,
                graph_revision="g1",
                anchors=(
                    {
                        "path": "legacy.cob",
                        "line": 42,
                        "symbol": "WRITE-RECORD",
                        "semantic_certainty": 1.0,
                        "retrieval_relevance": 1.0,
                    },
                ),
                status="source_backed",
                # The fake deliberately leaves the revision unbound; the
                # compiler accepts it and binds the fact to the agent's
                # current source revision for this boundary test.
                source_revision="",
                index_current=True,
                intelligence_valid=True,
                substrate_ready=True,
            ),
            None,
        )

    agent._start_repository_session = fake_repository_session
    await agent.run("Update the record writer in legacy.cob.", _Environment(), AgentContext())

    assert any("legacy.cob:42" in item for item in model.observed_history[0])
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    deliveries = receipt["repository_intelligence"]["frontier_deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["delivered_before_call"] == 1
    assert deliveries[0]["facts"][0]["kind"] == "file"
    assert deliveries[0]["facts"][0]["symbol"] == ""
    call = receipt["model_call_contexts"][0]
    assert call["stock_provider_messages_sha256"] != call["provider_messages_sha256"]
    assert call["provider_changed_message_indices"]
    assert call["certified_graph_chars"] > 0


@pytest.mark.asyncio
async def test_source_less_task_is_denominator_excluded_not_graph_invalid(
    tmp_path,
):
    class TransferEnvironment(_Environment):
        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            Path(target_dir, "README.md").write_text("no structurally supported source\n")

    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_frontier=True,
    )
    agent._model_factory = lambda: model

    await agent.run("Fix the repository implementation.", TransferEnvironment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    intelligence = receipt["repository_intelligence"]
    assert intelligence["status"] == "not_applicable"
    assert intelligence["applicability"] == "not_applicable_no_supported_source"
    assert intelligence["denominator_excluded"] is True
    assert intelligence["failures"] == []
    assert intelligence["graph_gate"]["failures"] == []
    assert intelligence["frontier_deliveries"] == []
    assert receipt["metrics"]["repository_intelligence_valid"] == 0
    assert receipt["metrics"]["repository_graph_schema_valid"] == 0
    assert receipt["metrics"]["context_frontier_zero_tasks"] == 0


@pytest.mark.asyncio
async def test_task_graph_failure_degrades_but_preserves_provider_loop(tmp_path):
    class TransferEnvironment(_Environment):
        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            Path(target_dir, "README.md").write_text(
                "the task has no structurally indexable source\n"
            )

    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_frontier=True,
        require_graph_ready=True,
    )
    agent._model_factory = lambda: model

    await agent.run("Fix the repository implementation.", TransferEnvironment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert len(model.observed_history) == 1
    assert receipt["calls"] == 1
    assert receipt["metrics"]["repository_graph_gate_enabled"] == 1
    assert receipt["metrics"]["repository_graph_gate_blocked"] == 0
    assert receipt["metrics"]["repository_graph_degraded_fallback"] == 0
    assert receipt["metrics"]["repository_graph_gate_failures"] == []
    assert receipt["metrics"]["api_calls"] == 1


@pytest.mark.asyncio
async def test_paid_environment_path_transfers_only_selected_source_files(tmp_path):
    class SourceArchiveEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(
                    stdout=(
                        "f\t40\t1.0\t1.0\tapp.py\t\n"
                        "f\t498000000\t1.0\t1.0\tgpt2-124M.ckpt\t\n"
                        "f\t1000000\t1.0\t1.0\tvocab.bpe\t\n"
                    ),
                    return_code=0,
                )
            if command.startswith("sha256sum"):
                return ExecResult(stdout=("a" * 64) + "  app.py\n", return_code=0)
            return ExecResult(stdout="", return_code=0)

        async def download_file(self, source_path, target_path):
            payload = b"def solve():\n    return 1\n"
            with tarfile.open(target_path, "w:gz") as archive:
                member = tarfile.TarInfo("app.py")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_frontier=False,
        require_graph_ready=False,
    )
    agent._model_factory = lambda: model

    environment = SourceArchiveEnvironment()
    await agent.run("Fix solve in app.py.", environment, AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    plan = next(
        row for row in receipt["repository_work_receipts"]
        if row["kind"] == "source_mirror_plan"
    )
    transfer = next(
        row for row in receipt["repository_work_receipts"]
        if row["kind"] == "mirror_transfer"
    )
    assert plan["paths"] == ["app.py"]
    assert plan["excluded_artifacts"] == 2
    assert transfer["transfer_mode"] == "source_only_archive"
    transfer_commands = [command for command, _env in environment.commands]
    assert not any("/tmp/gt-source-paths.nul" in command for command in transfer_commands)
    assert not any("/tmp/gt-source-mirror.tar.gz" in command for command in transfer_commands)
    assert any(
        "rmdir -- /tmp/.gt-mirror." in command and "test ! -e /tmp/.gt-mirror." in command
        for command in transfer_commands
    )
    assert receipt["metrics"]["repository_mirror_files"] == 1
    assert (
        receipt["host_execution"]["category_counts"]["repository_transfer"]
        >= 2
    )


@pytest.mark.asyncio
async def test_strict_graph_gate_allows_current_certified_graph(tmp_path):
    class TransferEnvironment(_Environment):
        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            root = Path(target_dir)
            (root / "app.py").write_text(
                "def target(value):\n    return value + 1\n\n"
                "def caller():\n    return target(1)\n",
                encoding="utf-8",
            )

    model = _ScriptedModel(["echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_frontier=True,
        require_graph_ready=True,
    )
    agent._model_factory = lambda: model

    await agent.run(
        "Change target to return the requested value.",
        TransferEnvironment(),
        AgentContext(),
    )

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert len(model.observed_history) == 1
    assert receipt["metrics"]["repository_graph_gate_enabled"] == 1
    assert receipt["metrics"]["repository_graph_gate_blocked"] == 0
    assert receipt["metrics"]["repository_graph_source_revision"]


@pytest.mark.asyncio
async def test_frontier_fact_is_one_shot_and_task_budget_is_receipted(tmp_path):
    class TransferEnvironment(_Environment):
        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            root = Path(target_dir)
            (root / "src").mkdir(parents=True)
            (root / "src" / "greeter.py").write_text(
                "def greet(name: str) -> str:\n    return f'hello {name}'\n"
            )

    model = _ScriptedModel(["cat src/greeter.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_frontier=True,
        context_frontier_task_budget_chars=400,
    )
    agent._model_factory = lambda: model

    await agent.run(
        "Ensure greet returns an uppercase greeting.",
        TransferEnvironment(),
        AgentContext(),
    )

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    deliveries = receipt["repository_intelligence"]["frontier_deliveries"]
    delivered_ids = [fact for row in deliveries for fact in row["fact_ids"]]
    assert len(delivered_ids) == len(set(delivered_ids))
    assert receipt["metrics"]["context_frontier_duplicate_facts"] == 0
    assert receipt["metrics"]["context_frontier_chars_added"] <= 400
    assert receipt["metrics"]["context_frontier_task_budget_chars"] == 400


@pytest.mark.asyncio
async def test_proven_read_only_action_reuses_workspace_snapshot_without_rescan(tmp_path):
    model = _ScriptedModel(["cat src/greeter.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    environment = _Environment()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_repository_intelligence=False,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the file and finish.", environment, AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    manifest_execs = [
        row
        for row in receipt["host_execution"]["receipts"]
        if row["category"] == "workspace_manifest" and not row["cache_hit"]
    ]
    manifest_cache_hits = [
        row
        for row in receipt["host_execution"]["receipts"]
        if row["category"] == "workspace_manifest" and row["cache_hit"]
    ]
    assert len(manifest_execs) == 2  # initial snapshot plus submit postflight
    assert len(manifest_cache_hits) == 1
    assert manifest_cache_hits[0]["action_id"] == 1


@pytest.mark.asyncio
async def test_partial_completion_plan_executes_no_private_predicates(tmp_path):
    model = _ScriptedModel(
        [
            "touch /app/task_file/output_data/plan_b1.jsonl",
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    environment = _Environment()
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model

    await agent.run(
        "Produce /app/task_file/output_data/plan_b1.jsonl and satisfy all scheduling constraints.",
        environment,
        AgentContext(),
    )

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["completion_plan_status"] == "partial"
    assert receipt["metrics"]["completion_probe_execs"] == 0
    assert not any(command.startswith("test -s ") for command, _env in environment.commands)


@pytest.mark.asyncio
async def test_custom_probe_failure_is_not_reframed_as_model_guidance(tmp_path):
    class ProbeEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command == "python3 /tmp/test_single.py":
                return ExecResult(
                    stdout="UnexpectedAlertPresentException: exploit alert fired\n",
                    return_code=1,
                )
            return ExecResult(return_code=0)

    model = _ScriptedModel(
        ["python3 /tmp/test_single.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
    )
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model

    await agent.run("Demonstrate the browser exploit behavior.", ProbeEnvironment(), AgentContext())

    assert len(model.observed_history) == 2
    second_request = "\n".join(model.observed_history[1])
    assert "UnexpectedAlertPresentException" in second_request
    assert "Validation failed for the current source revision" not in second_request
    assert "failing required check" not in second_request
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["payload_deliveries"] == 0
    assert receipt["features"]["required_check_claims_without_declared_id"] == 0


@pytest.mark.asyncio
async def test_context_transform_preserves_oversized_read_before_budget_pressure(tmp_path):
    class LargeReadEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command == "cat huge.log":
                return ExecResult(stdout="Z" * 30_000, return_code=0)
            return ExecResult(return_code=0)

    model = _ScriptedModel(["cat huge.log", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_compaction=True,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect huge.log and finish.", LargeReadEnvironment(), AgentContext())

    second_request = "\n".join(model.observed_history[1])
    assert "Z" * 30_000 in second_request
    assert "Tool output bounded by host" not in second_request
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["context_compactions"] == 0
    compiler = receipt["model_call_contexts"][1]["context_compiler"]
    assert compiler["bounded_observation_count"] == 0
    call = receipt["model_call_contexts"][1]
    assert call["stock_provider_messages_sha256"] == call["provider_messages_sha256"]
    assert call["provider_changed_message_indices"] == []
    assert all(
        not row["provider_compaction_epoch_started"] for row in receipt["model_call_contexts"]
    )


@pytest.mark.asyncio
async def test_context_soft_character_limit_never_starts_compaction_epoch(tmp_path):
    class LargeReadEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command.startswith("cat huge"):
                return ExecResult(stdout=command[-5:] * 5_000, return_code=0)
            return ExecResult(return_code=0)

    model = _ScriptedModel(
        [
            "cat huge1.log",
            "cat huge2.log",
            "cat huge3.log",
            "cat huge4.log",
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_compaction=True,
        context_trigger_chars=20_000,
        context_target_chars=12_000,
        context_min_compaction_savings_chars=1,
        context_min_compaction_savings_ratio=0.0,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the logs and finish.", LargeReadEnvironment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["context_compactions"] == 0
    assert receipt["metrics"]["context_compaction_epochs"] == []
    assert receipt["metrics"]["context_unique_reasoning_chars_removed"] == 0
    assert receipt["metrics"]["context_bounded_observations"] == 0
    assert receipt["metrics"]["context_bounded_observation_applications"] == 0


@pytest.mark.asyncio
async def test_soft_compaction_defers_when_cache_break_savings_are_too_small(tmp_path):
    class LargeReadEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command.startswith("cat huge"):
                return ExecResult(stdout=command[-5:] * 5_000, return_code=0)
            return ExecResult(return_code=0)

    model = _ScriptedModel(
        [
            "cat huge1.log",
            "cat huge2.log",
            "cat huge3.log",
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_compaction=True,
        context_trigger_chars=20_000,
        context_target_chars=12_000,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the logs and finish.", LargeReadEnvironment(), AgentContext())

    metrics = json.loads((tmp_path / "central_receipt.json").read_text())["metrics"]
    assert metrics["context_compactions"] == 0
    assert metrics["context_compaction_deferral_count"] == 0


@pytest.mark.asyncio
async def test_disabled_task_start_advisory_never_leaks_into_call_two(tmp_path):
    class TransferEnvironment(_Environment):
        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            root = Path(target_dir)
            (root / "src").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
            (root / "src" / "greeter.py").write_text("def greet(): return 'hello'\n")

    model = _ScriptedModel(["echo inspect", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_task_start_advisory=False,
    )
    agent._model_factory = lambda: model

    await agent.run("Change the greeting.", TransferEnvironment(), AgentContext())

    assert len(model.observed_history) == 2
    assert not any(
        "src/greeter.py" in item for history in model.observed_history for item in history
    )
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert not any(row["feature_id"] == "GT_LOC_RESLOT" for row in receipt["guidance_deliveries"])


@pytest.mark.asyncio
async def test_receipt_hashes_the_provider_prepared_messages_not_private_extra(tmp_path):
    class PreparedModel(_ScriptedModel):
        model_kwargs = {"temperature": 1.0}
        tools = [{"type": "function", "function": {"name": "bash"}}]

        def __init__(self, commands):
            super().__init__(commands)
            self.raw_history = []

        def _prepare_messages_for_api(self, messages):
            return [
                {key: value for key, value in message.items() if key != "extra"}
                for message in messages
            ]

        def query(self, messages):
            self.raw_history.append(json.loads(json.dumps(messages)))
            return super().query(messages)

    model = PreparedModel(["echo inspect", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model

    await agent.run("Inspect café, then finish.", _Environment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    row = receipt["model_call_contexts"][1]
    logical = model.observed_history[1]
    prepared = model._prepare_messages_for_api(model.raw_history[1])
    expected = hashlib.sha256(
        json.dumps(
            prepared,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    assert row["provider_messages_sha256"] == expected
    assert row["provider_request_chars"] == len(
        json.dumps(
            prepared,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )
    assert row["provider_message_count"] == len(prepared)
    assert logical


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
async def test_missing_edit_passes_to_shell_then_postflight_keeps_loop_live(tmp_path):
    class ExistingFileEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.executed_edits: list[str] = []
            self.edited = False

        async def download_dir_with_exclusions(self, *, source_dir, target_dir, exclude):
            Path(target_dir, "app.py").write_text("def x():\n    return 1\n")

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                size = 22
                stamp = "2.0" if self.edited else "1.0"
                return ExecResult(
                    stdout=f"f\t{size}\t{stamp}\t{stamp}\tapp.py\t\n",
                    return_code=0,
                )
            if command.startswith("sha256sum"):
                digest = "b" if self.edited else "a"
                return ExecResult(stdout=(digest * 64) + "  app.py\n", return_code=0)
            if command.startswith("python3 -c"):
                encoded = (
                    "ZGVmIHkoKToKICAgIHJldHVybiAyCg=="
                    if self.edited
                    else "ZGVmIHgoKToKICAgIHJldHVybiAxCg=="
                )
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

    assert environment.executed_edits == [first, revised]
    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    cycles = receipt["features"]["action_cycles"]
    first_cycle = next(row for row in cycles if row["proposed"]["raw_command"] == first)
    assert first_cycle["candidate_decision"]["disposition"] == "pass"
    assert first_cycle["applied_disposition"] == "pass"
    assert first_cycle["executed"] is True
    revised_cycle = next(row for row in cycles if row["proposed"]["raw_command"] == revised)
    assert revised_cycle["executed"] is True
    assert revised_cycle["postflight"]["source_revision"]
    session = receipt["repository_session"]
    assert session["fresh"] is True
    assert len(session["refresh_log"]) == 3
    assert [row["mode"] for row in session["refresh_log"]] == [
        "full",
        "incremental",
        "action_query",
    ]
    assert session["refresh_log"][-1]["active_paths"] == ["app.py"]
    assert session["source_revision"] == receipt["source_revision"]
    assert receipt["metrics"]["repository_incremental_refreshes"] == 1
    assert receipt["metrics"]["preflight_commands_returned_to_model"] == 0
    assert receipt["metrics"]["preflight_commands_changed_after_return"] == 0


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
    assert cycle["candidate_decision"]["disposition"] == "pass"
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
        integration_mode=GTIntegrationMode.OFF,
    )
    shadow = MiniSweCentralAgent(
        logs_dir=tmp_path / "shadow",
        model_name="test",
        preflight_mode=PreflightMode.SHADOW,
        integration_mode=GTIntegrationMode.AUDIT,
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
    assert off_receipt["integration_mode"] == "off"
    assert shadow_receipt["integration_mode"] == "audit"
    assert [row["provider_messages_sha256"] for row in off_receipt["model_call_contexts"]] == [
        row["provider_messages_sha256"] for row in shadow_receipt["model_call_contexts"]
    ]


def test_integration_mode_is_one_switch_and_audit_cannot_intervene(tmp_path):
    off = MiniSweCentralAgent(
        logs_dir=tmp_path / "off",
        model_name="test",
        integration_mode="off",
        preflight_mode="assistive_safe",
        enable_context_compaction=True,
        enable_task_start_advisory=True,
    )
    audit = MiniSweCentralAgent(
        logs_dir=tmp_path / "audit",
        model_name="test",
        integration_mode="audit",
        preflight_mode="assistive_safe",
        enable_context_compaction=True,
        enable_task_start_advisory=True,
    )

    assert off.integration_mode is GTIntegrationMode.OFF
    assert off.preflight_mode is PreflightMode.OFF
    assert off.enable_context_compaction is False
    assert off.enable_task_start_advisory is False
    assert off.enable_lint is False
    assert off.enable_submit_readiness is False
    assert audit.integration_mode is GTIntegrationMode.AUDIT
    assert audit.preflight_mode is PreflightMode.SHADOW
    assert audit.enable_context_compaction is False
    assert audit.enable_task_start_advisory is False


def test_certified_shadow_is_provider_neutral_and_cannot_run_active_controllers(tmp_path):
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        policy_mode="certified_shadow",
        preflight_mode="assistive_safe",
        enable_context_compaction=True,
        enable_completion_controller=True,
        enable_adaptive_validation_timeout=True,
    )

    assert agent.policy_mode is GTPolicyMode.CERTIFIED_SHADOW
    assert agent.preflight_mode is PreflightMode.SHADOW
    assert agent.enable_context_compaction is False
    assert agent.enable_completion_controller is False
    assert agent.enable_feature_guidance is False
    assert agent.enable_adaptive_validation_timeout is False
    assert agent._features.model_visible is False


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
    environment = _ObservedMutationEnvironment("touch app.py", "f\t6\t2.0\t2.0\tapp.py\t\n")
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


def test_context_compaction_uses_provider_headroom_reserve_not_only_char_threshold(tmp_path):
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")

    assert agent.context_capacity_chars == 400_000
    assert agent.context_trigger_chars == 120_000
    assert agent.context_target_chars == 80_000
    assert agent.provider_context_reserve_tokens == 131_072


def test_explicit_foreground_validation_may_receive_bounded_timeout_extension(tmp_path):
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_adaptive_validation_timeout=True,
    )
    classification = classify_validation_command("timeout 90s python3 -m pytest -q")
    proposal = adapt_proposed_action(
        {"command": classification.command},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
        validation=classification,
    )

    timeout, reason = agent._select_action_timeout(
        proposal,
        classification,
        remaining_agent_time_sec=500.0,
    )

    assert timeout == 90.0
    assert reason == "literal_validation_timeout"


def test_redirected_declared_validator_receives_bounded_timeout_extension(tmp_path):
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_adaptive_validation_timeout=True,
    )
    command = "cd /app && timeout 900 python3 benchmark.py 2>&1"
    classification = classify_validation_command(command, ("python3 benchmark.py",))
    proposal = adapt_proposed_action(
        {"command": command},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
        validation=classification,
    )

    timeout, reason = agent._select_action_timeout(
        proposal,
        classification,
        remaining_agent_time_sec=700.0,
    )

    assert timeout == 120.0
    assert reason == "literal_validation_timeout"


def test_timeout_extension_abstains_for_custom_or_dynamic_probes(tmp_path):
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_adaptive_validation_timeout=True,
    )
    classification = classify_validation_command("timeout $WAIT python3 /tmp/test_one.py")
    proposal = adapt_proposed_action(
        {"command": classification.command},
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
        validation=classification,
    )

    timeout, reason = agent._select_action_timeout(
        proposal,
        classification,
        remaining_agent_time_sec=500.0,
    )

    assert timeout == 30.0
    assert reason == "default_command_timeout"


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
    assert (
        "options: [off, audit, certified_context, certified_controllers, certified_full]"
        in workflow
    )
    assert "default: audit" in workflow
    assert "enable_lint=false" in workflow
    assert "preflight_mode=shadow" in workflow
    assert "enable_preflight=true" not in workflow


def test_paid_engine_workflow_receives_exact_harbor_budget_without_new_limit():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tb2_miniswe_engine.yml"
    ).read_text(encoding="utf-8")

    # The same task.toml timeout still owns the experiment.  GT receives that
    # value only so it can return before Harbor asynchronously cancels run().
    assert "--ak enable_lint=true" in workflow
    assert "--ak enable_submit_readiness=true" in workflow
    assert "scripts/resolve_harbor_budget.py" in workflow
    assert '--ak execution_budget_sec="$EXECUTION_BUDGET"' in workflow
    assert "--ak model_timeout_sec" not in workflow
    assert "--ak model_loop_timeout_sec" not in workflow
    assert "--agent-timeout-multiplier 1.0" in workflow
    assert "--ak enable_context_compaction=true" in workflow
    assert "--ak enable_completion_controller=true" in workflow
    assert "--ak enable_feature_guidance=false --ak enable_context_frontier=false" in workflow


def test_paid_central_matrix_uses_the_same_outcome_preserving_contract():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tb2_miniswe_central.yml"
    ).read_text(encoding="utf-8")

    assert 'AGENT="eval.gt_central_agent:MiniSweCentralAgent"' in workflow
    assert '--agent-import-path "$AGENT"' in workflow
    assert "--ak integration_mode=active" in workflow
    assert "--ak policy_mode=certified_active" in workflow
    assert "--ak integration_mode=off --ak policy_mode=off --ak preflight_mode=off" in workflow
    assert (
        "--ak integration_mode=audit --ak policy_mode=audit --ak preflight_mode=shadow"
        in workflow
    )
    assert "--ak preflight_mode=shadow" in workflow
    assert "--ak enable_context_compaction=true" in workflow
    assert "--ak enable_adaptive_validation_timeout=true" in workflow
    assert "--ak enable_completion_controller=true" in workflow
    assert "--ak enable_progress_control=true" in workflow
    assert '--ak execution_budget_sec="$EXECUTION_BUDGET"' in workflow
    assert "scripts/resolve_harbor_budget.py" in workflow
    assert "--agent-timeout-multiplier 1.0" in workflow
    assert "--ak model_timeout_sec" not in workflow
    assert "--ak model_loop_timeout_sec" not in workflow
    assert "harbor_result=got[0] if got else None" in workflow


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
    assert not any("Observed task fact:" in item for item in model.observed_history[0])
    assert any(
        "Observed task fact: Syntax check failed for app.py" in item
        for item in model.observed_history[1]
    )
    assert not any(
        "Observed task fact: Syntax check failed for app.py" in item
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
    assert "Observed task fact:" not in trajectory
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
    assert metrics["context_compiler_calls"] == metrics["api_calls"]
    assert metrics["context_unique_reasoning_chars_removed"] == 0
    assert metrics["context_compiler_effects_unaccounted"] == 0
    assert all(row["context_compiler_ran"] for row in contexts)
    assert all(row["context_facts_accounted"] == row["context_fact_candidates"] for row in contexts)
    assert all(
        row["context_compiler"]["accounted_fact_count"]
        == row["context_compiler"]["candidate_fact_count"]
        for row in contexts
    )
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

    class IndexedAllFeatureAgent(MiniSweCentralAgent):
        async def _start_repository_session(
            self,
            environment,
            instruction,
            *,
            snapshot,
            source_revision,
            task_deliverables=frozenset(),
        ):
            return (
                RepositoryEvidence(
                    available=True,
                    graph_revision="graph-r0",
                    anchors=(
                        {"path": "app.py", "line": 10, "symbol": "f"},
                        {"path": "tests/test_app.py", "line": 20, "symbol": "test_f"},
                    ),
                    definitions=(
                        {
                            "path": "app.py",
                            "line": 10,
                            "symbol": "f",
                            "semantics": "graph_definition",
                        },
                    ),
                    references=(
                        {
                            "path": "tests/test_app.py",
                            "line": 20,
                            "symbol": "f",
                            "semantics": "graph_call_reference",
                        },
                    ),
                    callers=(
                        {
                            "caller_path": "tests/test_app.py",
                            "caller_line": 20,
                            "caller_symbol": "test_f",
                            "target_path": "app.py",
                            "target_symbol": "f",
                            "semantics": "graph_recorded",
                        },
                    ),
                    status="available",
                ),
                None,
            )

    agent = IndexedAllFeatureAgent(logs_dir=tmp_path, model_name="test")
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
async def test_provider_budget_failure_stops_before_model_query_and_is_receipted(tmp_path):
    class MustNotQuery(_ScriptedModel):
        def __init__(self):
            super().__init__(["echo never-executed"])
            self.queries = 0

        def query(self, messages):
            self.queries += 1
            raise AssertionError("an over-budget provider request must not be sent")

    model = MustNotQuery()
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        provider_context_limit_tokens=100,
        provider_context_hard_ratio=0.5,
    )
    agent._model_factory = lambda: model
    context = AgentContext()

    await agent.run("do it", _Environment(), context)

    assert model.queries == 0
    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    assert receipt["metrics"]["provider_request_budget_failures"] == 1
    assert receipt["metrics"]["censored"] is False
    assert receipt["metrics"]["censored_reason"] == ""
    assert receipt["metrics"]["solver_exhausted"] is True
    assert receipt["metrics"]["solver_exhausted_reason"] == "context_budget_exhausted"
    assert receipt["model_call_contexts"][0]["request_budget_within_limit"] is False
    assert receipt["metrics"]["provider_requests_prepared"] == 1
    assert receipt["metrics"]["model_query_invocations"] == 0
    assert receipt["metrics"]["provider_responses_received"] == 0
    assert receipt["metrics"]["provider_requests_not_sent"] == 1
    assert receipt["metrics"]["api_calls"] == 0
    assert receipt["model_call_contexts"][0]["dispatch_status"] == "prepared_not_sent"
    assert context.metadata["exit_status"] == "ContextBudgetExhausted"


@pytest.mark.asyncio
async def test_stall_aggregate_reaches_first_next_model_call_once_without_advice(tmp_path):
    model = _ScriptedModel(
        [
            "printf same",
            "printf same",
            "printf same",
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_repository_intelligence=False,
        enable_progress_control=True,
    )
    agent._model_factory = lambda: model

    await agent.run("Complete the task.", _Environment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    deliveries = receipt["progress"]["fact_deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["first_eligible_call"] == deliveries[0]["delivered_before_call"]
    assert deliveries[0]["one_step_late"] is False
    assert deliveries[0]["not_predictive"] is True
    assert receipt["metrics"]["progress_frame_deliveries"] == 1
    visible = "\n".join(model.observed_history[3])
    assert "Execution state STALLED" in visible
    stall_line = next(line for line in visible.splitlines() if "Execution state STALLED" in line)
    assert "should" not in stall_line.lower()


@pytest.mark.asyncio
async def test_failed_reader_does_not_consume_anchor_or_create_fallback_stall(tmp_path):
    class ReaderEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command.startswith("xxd "):
                return ExecResult(stdout="xxd: command not found", return_code=127)
            if command.startswith("od "):
                return ExecResult(stdout=f"bytes for {command.split()[-1]}", return_code=0)
            return ExecResult(stdout="", return_code=0)

    paths = ("a.cob", "b.cob", "c.cob", "d.cob")
    model = _ScriptedModel(
        [
            *(f"xxd {path}" for path in paths),
            *(f"od {path}" for path in paths),
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]
    )
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_repository_intelligence=False,
        enable_progress_control=True,
    )
    agent._model_factory = lambda: model

    await agent.run("Inspect the COBOL inputs and finish.", ReaderEnvironment(), AgentContext())

    receipt = json.loads((tmp_path / "central_receipt.json").read_text())
    assert receipt["metrics"]["progress_frame_deliveries"] == 0
    assert receipt["metrics"]["failed_read_anchors_not_consumed"] == 4
    assert receipt["metrics"]["semantic_progress_kinds"]["localization_gain"] == 4
    assert len(receipt["progress"]["observations"]) == 9
    assert all(
        len(row["output_sha256"]) == 64
        and "declared_check_id" in row
        and "diagnostic_fingerprint" in row
        for row in receipt["progress"]["observations"]
    )
    assert all(
        "Execution state STALLED" not in "\n".join(history)
        for history in model.observed_history
    )


@pytest.mark.asyncio
async def test_over_budget_next_request_does_not_confirm_pending_guidance(tmp_path):
    class LargeFailureEnvironment(_Environment):
        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                return ExecResult(stdout="", return_code=0)
            if command == "pytest -q":
                return ExecResult(
                    stdout="FAILED tests/test_app.py::test_app\n" + ("x" * 50_000),
                    return_code=1,
                )
            raise AssertionError(command)

    model = _ScriptedModel(["pytest -q", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        enable_context_compaction=True,
        provider_context_limit_tokens=30_000,
        provider_context_hard_ratio=0.5,
    )
    agent._model_factory = lambda: model

    await agent.run(
        "Run `pytest -q` before finishing.",
        LargeFailureEnvironment(),
        AgentContext(),
    )

    assert len(model.observed_history) == 1
    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    assert receipt["metrics"]["provider_request_budget_failures"] == 1
    assert receipt["metrics"]["payload_deliveries"] == 0
    assert receipt["guidance_deliveries"] == []
    assert receipt["model_call_contexts"][-1]["runtime_message_index"] is not None
    assert receipt["model_call_contexts"][-1]["request_budget_within_limit"] is False


@pytest.mark.asyncio
async def test_executable_completion_certificate_auto_submits_before_next_model_call(tmp_path):
    task = """Please solve this issue: Write me data.comp that's compressed such that
running cat data.comp | /app/decomp gives exactly data.txt.
You can generate data.comp any way you want, but data.comp must be at most 2500 bytes.

## Recommended Workflow
1. Analyze the codebase
2. Submit with echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
"""

    class ArtifactEnvironment(_Environment):
        def __init__(self):
            super().__init__()
            self.created = False

        async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
            self.commands.append((command, env))
            if command.startswith("uname "):
                return ExecResult(stdout="Linux\t6.8\tversion\tx86_64\n", return_code=0)
            if "-printf" in command:
                manifest = "f\t100\t1.0\t1.0\tdata.txt\t\nf\t100\t1.0\t1.0\tdecomp\t\n"
                if self.created:
                    manifest += "f\t2372\t2.0\t2.0\tdata.comp\t\n"
                return ExecResult(stdout=manifest, return_code=0)
            if command.startswith("sha256sum"):
                return ExecResult(stdout=("a" * 64) + "  data.comp\n", return_code=0)
            if command == "write candidate":
                self.created = True
                return ExecResult(return_code=0)
            if command.startswith("tmp=$(mktemp)"):
                return ExecResult(return_code=0)
            if command.startswith("test -f /app/data.comp"):
                return ExecResult(return_code=0)
            if command == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
                return ExecResult(stdout="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", return_code=0)
            raise AssertionError(f"unexpected command: {command}")

    model = _ScriptedModel(["write candidate"])
    environment = ArtifactEnvironment()
    agent = MiniSweCentralAgent(logs_dir=tmp_path, model_name="test")
    agent._model_factory = lambda: model
    context = AgentContext()

    await agent.run(task, environment, context)

    assert len(model.observed_history) == 1
    executed = [command for command, _ in environment.commands]
    assert executed.count("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT") == 1
    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    certificate = receipt["completion"]["latest_certificate"]
    assert certificate["status"] == "complete"
    assert certificate["auto_submit_eligible"] is True
    assert receipt["completion"]["auto_submit_count"] == 1
    assert receipt["metrics"]["auto_submits"] == 1
    assert receipt["metrics"]["actions"] == 1
    # Extensionless files are captured once so content-signature sources can
    # be classified and mirrored rather than silently omitted from graph
    # substrate discovery.
    assert receipt["metrics"]["actual_environment_execs"] == 10
    assert receipt["metrics"]["effective_actions"] == 9
    assert receipt["metrics"]["sensor_environment_execs"] == 5
    assert receipt["metrics"]["controller_environment_execs"] == 9
    assert receipt["metrics"]["effective_actions_schema"] == "actual-task-environment-execs-v2"
    assert receipt["metrics"]["host_exec_category_counts"]["model_action"] == 1
    assert receipt["metrics"]["host_exec_category_counts"]["completion_probe"] == 2
    assert receipt["metrics"]["host_exec_category_counts"]["auto_submit"] == 1
    gt_certificate = next(
        row for row in receipt["features"]["receipts"] if row["feature_id"] == "GT_CERT_DELIVERY"
    )
    assert gt_certificate["payload"]["check_count"] == 2
    assert gt_certificate["payload"]["passing_checks"] == 2
    assert gt_certificate["payload"]["readiness"] == "validated"
    assert context.metadata["exit_status"] == "Submitted"


@pytest.mark.asyncio
async def test_execution_budget_reserve_exits_before_outer_timeout(tmp_path):
    class SlowModel(_ScriptedModel):
        def query(self, messages):
            time.sleep(0.05)
            return super().query(messages)

    agent = MiniSweCentralAgent(
        logs_dir=tmp_path,
        model_name="test",
        execution_budget_sec=0.03,
        deadline_reserve_sec=0.01,
    )
    agent._model_factory = lambda: SlowModel(["echo too-late"])
    context = AgentContext()

    await agent.run("do it", _Environment(), context)

    receipt = json.loads((tmp_path / "central_receipt.json").read_text(encoding="utf-8"))
    assert receipt["metrics"]["censored"] is False
    assert receipt["metrics"]["deadline_reserve_exits"] == 1
    assert receipt["deadline"]["execution_budget_sec"] == 0.03
    assert context.metadata["exit_status"] == "DeadlineReserveReached"


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
