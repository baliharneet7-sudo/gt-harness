"""Concrete hooks for Mini-SWE-Agent 2.x.

The hooks use Mini-SWE's public agent/environment methods and its final
``_prepare_messages_for_api`` normalization seam. They are opt-in and preserve
stock behavior when not installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MethodType
from typing import Any

from .miniswe_integration import MiniSweAdapter


@dataclass
class RuntimeHookHandle:
    installed: bool = True


def _command(action: Any) -> str:
    if isinstance(action, dict):
        return str(action.get("cmd") or action.get("command") or "")
    return str(getattr(action, "cmd", "") or getattr(action, "command", "") or "")


def _observation_output(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("output") or result.get("message") or "")
    return str(result or "")


def install_runtime_hooks(agent: Any, adapter: MiniSweAdapter) -> RuntimeHookHandle:
    """Install hooks once and return a stable handle.

    ``agent`` is expected to be a Mini-SWE ``DefaultAgent`` instance. A clear
    error is raised for missing seams instead of silently degrading attribution.
    """
    existing = getattr(agent, "_gt_runtime_hook_handle", None)
    if existing is not None:
        return existing
    model = getattr(agent, "model", None)
    prepare = getattr(model, "_prepare_messages_for_api", None)
    execute = getattr(agent, "execute_actions", None)
    environment = getattr(agent, "env", None)
    if not callable(prepare) or not callable(execute) or environment is None:
        raise TypeError("Mini-SWE agent must expose model normalization and execute_actions")

    if adapter.phase == "ORIENT":
        adapter.start_task()

    def prepare_messages(_model: Any, messages: list[dict]) -> list[dict]:
        prepared = prepare(messages)
        suffix = adapter.next_provider_suffix()
        if prepared and isinstance(prepared[-1], dict):
            last = dict(prepared[-1])
            content = last.get("content", "")
            if isinstance(content, str) and suffix not in content:
                last["content"] = f"{content}\n\n[GT_CONTROL]\n{suffix}"
                prepared = [*prepared[:-1], last]
        adapter.bind_provider_payload({"messages": prepared})
        return prepared

    def execute_actions(_agent: Any, message: dict) -> list[dict]:
        actions = tuple((message.get("extra") or {}).get("actions") or ())
        results: list[dict] = []
        for action_index, action in enumerate(actions, start=1):
            command = _command(action)
            lower_command = command.lower()
            if "submit" in lower_command and adapter.phase in {"IMPLEMENT", "VERIFY"}:
                if adapter.phase == "IMPLEMENT":
                    adapter.begin_verify()
                adapter.begin_submit()
            adapter.before_action("bash", command)
            result = environment.execute(action)
            results.append(result)
            if any(word in lower_command for word in ("pytest", "test", "check", "verify")):
                if adapter.phase == "IMPLEMENT":
                    adapter.begin_verify()
            adapter.after_observation(_observation_output(result))
            if adapter.contract is not None:
                returncode = (
                    result.get("returncode")
                    if isinstance(result, dict)
                    else getattr(result, "returncode", None)
                )
                adapter.evaluate_observation(
                    command,
                    _observation_output(result),
                    returncode=returncode,
                    action_index=action_index,
                )
        formatter = getattr(model, "format_observation_messages", None)
        if callable(formatter):
            return agent.add_messages(*formatter(message, results, agent.get_template_vars()))
        return results

    model._gt_original_prepare_messages_for_api = prepare
    model._prepare_messages_for_api = MethodType(prepare_messages, model)
    agent._gt_original_execute_actions = execute
    agent.execute_actions = MethodType(execute_actions, agent)
    handle = RuntimeHookHandle()
    agent._gt_runtime_hook_handle = handle
    return handle
