from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .providers import Provider, StepResult, ToolCall
from .tools import TOOLS, BashTool, ToolError, dispatch


@dataclass
class AgentResult:
    final_text: str | None
    stop_reason: str  # end_turn | max_iterations | max_tokens | error
    iterations: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    transcript: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Agent:
    provider: Provider
    system: str
    max_iterations: int = 30
    max_input_tokens: int = 200_000
    truncation_char_budget: int = 120_000  # ~30k tokens of tool_result content
    on_event: Callable[[dict[str, Any]], None] | None = None
    bash: BashTool | None = None

    def __post_init__(self) -> None:
        if self.bash is None:
            self.bash = BashTool()

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event(event)

    def run(self, task: str) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        transcript: list[dict[str, Any]] = [{"type": "user", "content": task}]
        total_in = total_out = total_cache = 0
        iteration = 0

        while True:
            iteration += 1
            if iteration > self.max_iterations:
                return AgentResult(
                    final_text=None, stop_reason="max_iterations",
                    iterations=iteration - 1,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    total_cache_read_tokens=total_cache, transcript=transcript,
                )

            self._truncate_if_needed(messages, transcript)
            sr: StepResult = self.provider.step(messages, TOOLS, self.system)
            total_in += sr.usage.input_tokens
            total_out += sr.usage.output_tokens
            total_cache += sr.usage.cache_read_tokens

            transcript.append({
                "type": "assistant", "text": sr.text,
                "tool_calls": [tc.model_dump() for tc in sr.tool_calls],
                "stop_reason": sr.stop_reason, "usage": sr.usage.model_dump(),
            })
            self._emit({"type": "assistant", "text": sr.text,
                        "tool_calls": sr.tool_calls})

            messages.append(self._assistant_message(sr))

            # The cap is on per-step context size, not cumulative spend: every
            # step resends the whole conversation, so capping the sum would
            # silently end long tasks after a handful of steps. Cap breach takes
            # priority over natural completion even if the model said end_turn.
            if sr.usage.input_tokens >= self.max_input_tokens:
                return AgentResult(
                    final_text=sr.text, stop_reason="max_tokens",
                    iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    total_cache_read_tokens=total_cache, transcript=transcript,
                )

            # Output cut off mid-response (often mid-tool-call JSON): nudge a
            # continuation instead of misreporting success.
            if sr.stop_reason == "max_tokens" and not sr.tool_calls:
                nudge = ("Your previous response was cut off by the output "
                         "token limit. Continue: re-issue the incomplete tool "
                         "call in full, or finish your answer.")
                messages.append({"role": "user", "content": nudge})
                transcript.append({"type": "user", "content": nudge})
                continue

            if sr.stop_reason == "end_turn" or not sr.tool_calls:
                return AgentResult(
                    final_text=sr.text, stop_reason="end_turn",
                    iterations=iteration,
                    total_input_tokens=total_in, total_output_tokens=total_out,
                    total_cache_read_tokens=total_cache, transcript=transcript,
                )

            tool_results = self._execute_tool_calls(sr.tool_calls, transcript)
            messages.append({"role": "user", "content": tool_results})

    def _truncate_if_needed(self, messages: list[dict[str, Any]],
                            transcript: list[dict[str, Any]]) -> None:
        def total_chars() -> int:
            n = 0
            for m in messages:
                c = m.get("content")
                if isinstance(c, str):
                    n += len(c)
                elif isinstance(c, list):
                    for b in c:
                        n += len(b.get("text", "")) + len(b.get("content", ""))
            return n

        if total_chars() <= self.truncation_char_budget:
            return

        # Drop oldest tool_result block content first; keep the message and id.
        for m in messages:
            if not isinstance(m.get("content"), list):
                continue
            for b in m["content"]:
                if b.get("type") == "tool_result" and not str(
                        b.get("content", "")).startswith("[truncated"):
                    original_len = len(b.get("content", ""))
                    b["content"] = f"[truncated - {original_len} chars dropped]"
                    transcript.append({"type": "truncation",
                                       "tool_use_id": b.get("tool_use_id"),
                                       "dropped_chars": original_len})
                    if total_chars() <= self.truncation_char_budget:
                        return

    def _assistant_message(self, sr: StepResult) -> dict[str, Any]:
        # Internal canonical shape: assistant carries text + structured tool_calls.
        # Each provider re-serializes from this form.
        content_blocks: list[dict[str, Any]] = []
        if sr.text:
            content_blocks.append({"type": "text", "text": sr.text})
        for tc in sr.tool_calls:
            content_blocks.append({"type": "tool_use", "id": tc.id,
                                   "name": tc.name, "input": tc.arguments})
        return {
            "role": "assistant",
            "content": content_blocks,
            "tool_calls": [tc.model_dump() for tc in sr.tool_calls],
        }

    def _execute_tool_calls(self, calls: list[ToolCall],
                            transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for call in calls:
            try:
                output = dispatch(call.name, call.arguments, bash=self.bash)
                is_error = False
            except ToolError as e:
                output = f"ERROR: {e}"
                is_error = True
            transcript.append({"type": "tool_result", "id": call.id,
                               "name": call.name, "output": output,
                               "is_error": is_error})
            self._emit({"type": "tool_result", "id": call.id,
                        "output": output, "is_error": is_error})
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": output, "is_error": is_error})
        return results
