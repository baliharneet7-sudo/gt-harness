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
