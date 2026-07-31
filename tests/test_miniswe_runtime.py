from __future__ import annotations

from gt_engine.miniswe_controller import Predicate
from gt_engine.miniswe_integration import MiniSweAdapter
from gt_engine.miniswe_runtime import install_runtime_hooks


class FakeModel:
    def __init__(self):
        self.calls = []

    def _prepare_messages_for_api(self, messages):
        return [{k: v for k, v in item.items() if k != "extra"} for item in messages]


class FakeEnv:
    def execute(self, action):
        return {"output": "ok", "returncode": 0}


class FakeAgent:
    def __init__(self):
        self.model = FakeModel()
        self.env = FakeEnv()

    def execute_actions(self, message):
        return []


def test_runtime_hooks_capture_provider_payload_and_action(tmp_path):
    agent = FakeAgent()
    adapter = MiniSweAdapter(task_id="t", state_dir=tmp_path,
                             predicates=[Predicate("p", "p")])
    handle = install_runtime_hooks(agent, adapter)
    prepared = agent.model._prepare_messages_for_api([
        {"role": "user", "content": "task"},
    ])
    assert prepared[0]["content"].startswith("task")
    assert adapter.deliveries
    agent.execute_actions({"extra": {"actions": [{"cmd": "printf ok"}]}})
    assert handle.installed is True
    assert adapter.iteration == 1


def test_runtime_hooks_are_idempotent(tmp_path):
    agent = FakeAgent()
    adapter = MiniSweAdapter(task_id="t", state_dir=tmp_path, predicates=[])
    first = install_runtime_hooks(agent, adapter)
    second = install_runtime_hooks(agent, adapter)
    assert first is second


def test_real_miniswe_entrypoint_builds_pinned_adapter(tmp_path):
    from scripts.miniswe_gt_run import build_agent

    agent, adapter = build_agent(
        task="Create output.py and run pytest.",
        model="deepseek-v4-flash",
        cwd=str(tmp_path),
        state_dir=str(tmp_path / "state"),
        output=None,
        temperature=1.0,
    )
    assert agent._gt_runtime_hook_handle.installed is True
    assert adapter.contract is not None
    assert adapter.task_id
