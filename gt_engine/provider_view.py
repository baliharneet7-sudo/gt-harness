"""Deterministic provider-history compaction for the central Mini-SWE loop.

Compaction is smart, never aggressive: it first drops byte-identical duplicate
assistant/tool turns (no duplicate text is sent), then replaces only older
turns with an omission marker plus a typed state summary.  The summary carries
forward the bounded progress ledger (last edit, latest validation, unresolved
failure, read targets, changed paths) so the model never loses working memory
and is never told to rerun a completed command.
"""

from __future__ import annotations

import copy
import hashlib
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
    duplicate_turns_removed: int

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "compacted": self.compacted,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "elided_chars": self.elided_chars,
            "preserved_recent_messages": self.preserved_recent_messages,
            "active_state_chars": self.active_state_chars,
            "duplicate_turns_removed": self.duplicate_turns_removed,
        }


def _chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)) for item in messages
    )


def _turn_bounds(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return (start, end) index ranges of each assistant+tool turn."""
    turns: list[tuple[int, int]] = []
    index = 0
    total = len(messages)
    while index < total:
        if messages[index].get("role") == "assistant":
            end = index + 1
            while end < total and messages[end].get("role") == "tool":
                end += 1
            turns.append((index, end))
            index = end
        else:
            index += 1
    return turns


def _turn_fingerprint(
    messages: list[dict[str, Any]], start: int, end: int
) -> str:
    commands = [
        str(action.get("command") or "")
        for action in (messages[start].get("extra") or {}).get("actions") or []
    ]
    contents = [
        str(messages[idx].get("content") or "") for idx in range(start + 1, end)
    ]
    return hashlib.sha256(
        json.dumps([commands, contents], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def dedupe_provider_view(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop older assistant/tool turns that are byte-identical to a later turn.

    Protocol-safe: whole groups are removed, never a lone tool message, so
    tool-call/results pairing is preserved and no duplicate command output is
    sent to the provider.
    """
    turns = _turn_bounds(messages)
    if not turns:
        return messages
    last_by_fingerprint: dict[str, int] = {}
    for position, (start, end) in enumerate(turns):
        last_by_fingerprint[_turn_fingerprint(messages, start, end)] = position
    keep_positions = set(last_by_fingerprint.values())
    keep = [True] * len(messages)
    for position, (start, end) in enumerate(turns):
        if position not in keep_positions:
            for index in range(start, end):
                keep[index] = False
    return [message for message, flag in zip(messages, keep, strict=False) if flag]


def _active_state_text(active_state: dict[str, Any], *, limit: int = 4_000) -> str:
    lines = ["Current task state (derived from executed commands and workspace state):"]
    labels = (
        ("obligations", "Unresolved requirements"),
        ("source_revision", "Current source revision"),
        ("changed_paths", "Changed source paths"),
        ("last_edit", "Latest source edit"),
        ("latest_validation", "Latest validation"),
        ("unresolved_failure", "Unresolved failure"),
        ("recent_reads", "Files already read"),
        ("declared_checks", "Declared checks"),
        ("decision", "Current decision evidence"),
    )
    for key, label in labels:
        value = active_state.get(key)
        if value in (None, "", [], (), {}):
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            if key == "declared_checks" and value:
                rendered = ", ".join(f"{k}={v}" for k, v in value.items())
            else:
                rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        else:
            rendered = str(value)
        lines.append(f"{label}: {' '.join(rendered.split())}")
    return "\n".join(lines)[:limit]


def _compact_message(message: dict[str, Any]) -> dict[str, Any]:
    compacted = copy.deepcopy(message)
    role = str(compacted.get("role") or "")
    if role == "assistant":
        # The command actions remain so the model knows what was run; only the
        # long reasoning/result prose is dropped, and the typed state summary
        # carries the outcome forward.
        compacted["content"] = ""
        compacted.pop("reasoning_content", None)
        extra = compacted.get("extra")
        if isinstance(extra, dict):
            compacted["extra"] = {
                key: value for key, value in extra.items() if key in {"actions"}
            }
    elif role == "tool":
        original = str(compacted.get("content") or "")
        compacted["content"] = (
            f"Earlier command result summarized in the current task state above; "
            f"the exact output is not resent. (was {len(original)} characters)"
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

    1. Byte-identical duplicate assistant/tool turns are dropped first, so no
       duplicate text is ever sent.
    2. If the deduped view still exceeds the trigger, only older turns are
       summarized and the typed state summary (progress ledger) is injected.
    3. The most recent assistant/tool turns remain verbatim.
    """
    deduped = dedupe_provider_view(copy.deepcopy(messages))
    input_chars = _chars(deduped)
    duplicate_turns_removed = max(0, len(_turn_bounds(messages)) - len(_turn_bounds(deduped)))

    if input_chars <= max(1, int(trigger_chars)):
        return deduped, ProviderViewMetrics(
            compacted=False,
            input_chars=input_chars,
            output_chars=input_chars,
            elided_chars=0,
            preserved_recent_messages=len(deduped),
            active_state_chars=0,
            duplicate_turns_removed=duplicate_turns_removed,
        )

    original = deduped
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

    target = max(1, int(target_chars))
    while _chars(view) > target and len(middle) >= 2:
        removed = middle.pop(0)
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
        duplicate_turns_removed=duplicate_turns_removed,
    )
