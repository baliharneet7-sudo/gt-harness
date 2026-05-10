from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0


class StepResult(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str  # end_turn | tool_use | max_tokens
    usage: Usage


@runtime_checkable
class Provider(Protocol):
    model: str

    def step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
    ) -> StepResult: ...


from dataclasses import dataclass


def _ensure_block_list(content: Any) -> list[dict[str, Any]]:
    """Normalize a message's content to a list-of-blocks form so we can
    attach cache_control to the last block."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [dict(b) for b in content]


@dataclass
class AnthropicProvider:
    model: str
    client: Any = None  # injectable for tests; defaults to anthropic.Anthropic()
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()

    def step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
    ) -> StepResult:
        sys_param = [{"type": "text", "text": system,
                      "cache_control": {"type": "ephemeral"}}]
        msgs = [{"role": m["role"], "content": _ensure_block_list(m["content"])}
                for m in messages]
        # Cache-mark the last user turn (spec §3.5: system + second-to-last user
        # turn — by the time step() runs, the "second-to-last" is the most recent
        # user message before the assistant turn we're about to generate).
        for m in reversed(msgs):
            if m["role"] == "user" and m["content"]:
                m["content"][-1]["cache_control"] = {"type": "ephemeral"}
                break

        resp = self.client.messages.create(
            model=self.model,
            system=sys_param,
            messages=msgs,
            tools=tools,
            max_tokens=self.max_tokens,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id, name=block.name, arguments=dict(block.input)))

        usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        )

        return StepResult(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            usage=usage,
        )
