from __future__ import annotations

import json
from dataclasses import dataclass
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


_OAI_FINISH_REASON = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _normalize_assistant_for_openai(msg: dict[str, Any]) -> dict[str, Any]:
    """Convert our internal assistant message (which may carry tool_calls in
    Anthropic-style dict form) to OpenAI's expected shape. Tool messages stay
    role='tool' with tool_call_id."""
    if msg["role"] != "assistant":
        return msg
    content = msg.get("content")
    tool_calls = msg.get("tool_calls")
    out: dict[str, Any] = {"role": "assistant"}
    if isinstance(content, list):
        out["content"] = "\n".join(
            b["text"] for b in content if b.get("type") == "text"
        ) or None
    else:
        out["content"] = content
    if tool_calls:
        out["tool_calls"] = [{
            "id": tc["id"],
            "type": "function",
            "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
        } for tc in tool_calls]
    return out


@dataclass
class OpenAIProvider:
    model: str
    client: Any = None
    base_url: str | None = None
    max_completion_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.client is None:
            import openai
            self.client = openai.OpenAI(base_url=self.base_url) if self.base_url \
                else openai.OpenAI()

    def step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
    ) -> StepResult:
        oai_messages = [{"role": "system", "content": system}] + [
            _normalize_assistant_for_openai(m) for m in messages
        ]
        oai_tools = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        } for t in tools]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_completion_tokens": self.max_completion_tokens,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = Usage(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0),
            output_tokens=getattr(resp.usage, "completion_tokens", 0),
            cache_read_tokens=0,
        )

        return StepResult(
            text=msg.content,
            tool_calls=tool_calls,
            stop_reason=_OAI_FINISH_REASON.get(choice.finish_reason, choice.finish_reason),
            usage=usage,
        )
