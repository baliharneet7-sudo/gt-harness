"""Deterministic provider-history compaction for the central Mini-SWE loop."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderViewMetrics:
    compacted: bool
    input_chars: int
    output_chars: int
    elided_chars: int
    preserved_recent_messages: int
    active_state_chars: int

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "compacted": self.compacted,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "elided_chars": self.elided_chars,
            "preserved_recent_messages": self.preserved_recent_messages,
            "active_state_chars": self.active_state_chars,
        }


def _chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)) for item in messages
    )


def _active_state_text(active_state: dict[str, Any], *, limit: int = 4_000) -> str:
    lines = ["Current task state (derived from executed commands and workspace state):"]
    labels = (
        ("obligations", "Unresolved requirements"),
        ("changed_paths", "Changed source paths"),
        ("latest_failure", "Latest unresolved failure"),
        ("validation", "Current validation"),
        ("decision", "Current decision evidence"),
    )
    for key, label in labels:
        value = active_state.get(key)
        if value in (None, "", [], (), {}):
            continue
        if isinstance(value, (list, tuple, set)):
            rendered = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        else:
            rendered = str(value)
        lines.append(f"{label}: {' '.join(rendered.split())}")
    return "\n".join(lines)[:limit]


def _compact_message(message: dict[str, Any]) -> dict[str, Any]:
    compacted = copy.deepcopy(message)
    role = str(compacted.get("role") or "")
    if role == "assistant":
        compacted["content"] = ""
        compacted.pop("reasoning_content", None)
        extra = compacted.get("extra")
        if isinstance(extra, dict):
            # Provider-only bookkeeping is logged in the immutable trajectory;
            # it is not required to preserve tool protocol in the next request.
            compacted["extra"] = {key: value for key, value in extra.items() if key in {"actions"}}
    elif role == "tool":
        original = str(compacted.get("content") or "")
        compacted["content"] = (
            f"Older tool output omitted ({len(original)} characters); "
            "rerun the command if the exact output is needed."
        )
    return compacted


def build_provider_view(
    messages: list[dict[str, Any]],
    *,
    active_state: dict[str, Any],
    trigger_chars: int = 120_000,
    target_chars: int = 60_000,
    keep_recent_turns: int = 2,
) -> tuple[list[dict[str, Any]], ProviderViewMetrics]:
    """Return a compact inference view without mutating the audit history.

    System/task messages and the most recent assistant/tool turns remain
    verbatim.  Older messages retain their role and tool-call identifiers so
    OpenAI-compatible request validation still sees paired tool calls/results.
    """
    original = copy.deepcopy(messages)
    input_chars = _chars(original)
    if input_chars <= max(1, int(trigger_chars)):
        return original, ProviderViewMetrics(
            compacted=False,
            input_chars=input_chars,
            output_chars=input_chars,
            elided_chars=0,
            preserved_recent_messages=len(original),
            active_state_chars=0,
        )

    assistant_indices = [
        index for index, item in enumerate(original) if item.get("role") == "assistant"
    ]
    if assistant_indices:
        recent_start = assistant_indices[-max(1, int(keep_recent_turns))]
    else:
        recent_start = len(original)

    prefix_end = 0
    while prefix_end < len(original) and original[prefix_end].get("role") in {
        "system",
        "user",
    }:
        prefix_end += 1
    prefix = original[:prefix_end]
    middle = [_compact_message(item) for item in original[prefix_end:recent_start]]
    recent = original[recent_start:]
    state_text = _active_state_text(active_state)
    state_message = {"role": "user", "content": state_text} if state_text else None

    view = [*prefix, *middle]
    if state_message is not None:
        view.append(state_message)
    view.extend(recent)

    # If structural skeletons still exceed the target, discard the oldest
    # complete assistant/tool groups.  The immutable audit history remains
    # untouched and active state carries unresolved facts forward.
    target = max(1, int(target_chars))
    while _chars(view) > target and len(middle) >= 2:
        removed = middle.pop(0)
        # Remove tool observations belonging to the removed assistant until
        # the next assistant boundary.  This avoids orphaning tool messages.
        if removed.get("role") == "assistant":
            while middle and middle[0].get("role") == "tool":
                middle.pop(0)
        view = [*prefix, *middle]
        if state_message is not None:
            view.append(state_message)
        view.extend(recent)

    output_chars = _chars(view)
    return view, ProviderViewMetrics(
        compacted=True,
        input_chars=input_chars,
        output_chars=output_chars,
        elided_chars=max(0, input_chars - output_chars),
        preserved_recent_messages=len(recent),
        active_state_chars=len(state_text),
    )
