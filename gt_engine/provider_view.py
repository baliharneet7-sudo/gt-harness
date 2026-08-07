"""Deterministic, reasoning-preserving provider history for Mini-SWE.

The audit trajectory retains exact model reasoning and tool output.  The
provider view bounds oversized tool observations and, only when necessary,
clears older tool bodies to immutable receipts.  Assistant reasoning is never
compacted by this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ContextFactKind(StrEnum):
    REQUIREMENT = "requirement"
    REVISION = "revision"
    READ = "read"
    CHANGE = "change"
    VALIDATION = "validation"
    FAILURE = "failure"
    CHECK = "check"
    DECISION = "decision"
    STRUCTURAL = "structural"


class FactFreshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContextFact:
    """A deterministic source-backed fact considered for a provider view."""

    fact_id: str
    kind: ContextFactKind
    source_revision: str
    workspace_revision: str
    evidence_action: int
    paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    freshness: FactFreshness = FactFreshness.UNKNOWN
    required_until: str | None = None

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["kind"] = self.kind.value
        row["freshness"] = self.freshness.value
        return row


@dataclass(frozen=True, slots=True)
class ProviderViewMetrics:
    compiler_ran: bool
    compacted: bool
    raw_input_chars: int
    input_chars: int
    output_chars: int
    elided_chars: int
    preserved_recent_messages: int
    active_state_chars: int
    duplicate_turns_removed: int
    exact_duplicate_chars_removed: int
    unique_assistant_reasoning_chars_removed: int
    candidate_fact_count: int
    selected_fact_count: int
    represented_fact_count: int
    controller_only_fact_count: int
    omitted_fact_count: int
    accounted_fact_count: int
    stale_fact_count: int
    duplicate_fact_count: int
    selected_fact_ids: tuple[str, ...] = ()
    omitted_fact_reasons: dict[str, str] = field(default_factory=dict)
    fact_accounting: tuple[dict[str, Any], ...] = ()
    frame_sha256: str = ""
    bounded_observation_count: int = 0
    bounded_observation_chars_removed: int = 0
    duplicate_turns_represented: int = 0
    old_tool_results_cleared: int = 0
    state_frame_message_index: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "compiler_ran": self.compiler_ran,
            "compacted": self.compacted,
            "raw_input_chars": self.raw_input_chars,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "elided_chars": self.elided_chars,
            "preserved_recent_messages": self.preserved_recent_messages,
            "active_state_chars": self.active_state_chars,
            "duplicate_turns_removed": self.duplicate_turns_removed,
            "exact_duplicate_chars_removed": self.exact_duplicate_chars_removed,
            "unique_assistant_reasoning_chars_removed": (
                self.unique_assistant_reasoning_chars_removed
            ),
            "candidate_fact_count": self.candidate_fact_count,
            "selected_fact_count": self.selected_fact_count,
            "represented_fact_count": self.represented_fact_count,
            "controller_only_fact_count": self.controller_only_fact_count,
            "omitted_fact_count": self.omitted_fact_count,
            "accounted_fact_count": self.accounted_fact_count,
            "stale_fact_count": self.stale_fact_count,
            "duplicate_fact_count": self.duplicate_fact_count,
            "selected_fact_ids": list(self.selected_fact_ids),
            "omitted_fact_reasons": dict(self.omitted_fact_reasons),
            "fact_accounting": [dict(row) for row in self.fact_accounting],
            "frame_sha256": self.frame_sha256,
            "bounded_observation_count": self.bounded_observation_count,
            "bounded_observation_chars_removed": self.bounded_observation_chars_removed,
            "duplicate_turns_represented": self.duplicate_turns_represented,
            "old_tool_results_cleared": self.old_tool_results_cleared,
            "state_frame_message_index": self.state_frame_message_index,
        }


@dataclass(frozen=True, slots=True)
class RequestBudget:
    context_limit_tokens: int
    counted_tokens: int
    conservative_tokens: int
    effective_tokens: int
    hard_prompt_limit: int
    remaining_tokens: int
    counter_source: str

    @property
    def within_limit(self) -> bool:
        return self.effective_tokens <= self.hard_prompt_limit

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "within_limit": self.within_limit,
        }


def _chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)) for item in messages
    )


def provider_request_budget(
    messages: list[dict[str, Any]],
    *,
    model_name: str,
    context_limit_tokens: int = 1_048_576,
    hard_ratio: float = 0.90,
) -> RequestBudget:
    """Measure a provider request with a conservative no-overflow fallback."""

    payload = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    conservative = len(payload)
    counted = 0
    source = "utf8_byte_upper_bound"
    try:
        import litellm

        counted = int(litellm.token_counter(model=model_name, messages=messages) or 0)
        if counted > 0:
            source = "litellm_token_counter+utf8_byte_upper_bound"
    except Exception:
        counted = 0
    limit = max(1, int(context_limit_tokens))
    ratio = min(0.99, max(0.50, float(hard_ratio)))
    hard = max(1, int(limit * ratio))
    effective = max(counted, conservative)
    return RequestBudget(
        context_limit_tokens=limit,
        counted_tokens=counted,
        conservative_tokens=conservative,
        effective_tokens=effective,
        hard_prompt_limit=hard,
        remaining_tokens=hard - effective,
        counter_source=source,
    )


_FACT_KIND_BY_STATE_KEY = {
    "obligations": ContextFactKind.REQUIREMENT,
    "source_revision": ContextFactKind.REVISION,
    "workspace_revision": ContextFactKind.REVISION,
    "changed_paths": ContextFactKind.CHANGE,
    "last_edit": ContextFactKind.CHANGE,
    "latest_validation": ContextFactKind.VALIDATION,
    "unresolved_failure": ContextFactKind.FAILURE,
    "latest_failure": ContextFactKind.FAILURE,
    "recent_reads": ContextFactKind.READ,
    "declared_checks": ContextFactKind.CHECK,
    "project_checks": ContextFactKind.CHECK,
    "decision": ContextFactKind.DECISION,
    "feature_states": ContextFactKind.STRUCTURAL,
}


def _paths_from_value(value: Any) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(value, dict):
        raw_paths = value.get("paths") or ()
        if isinstance(raw_paths, str):
            raw_paths = (raw_paths,)
        candidates = [value.get("path"), *raw_paths]
    elif isinstance(value, (list, tuple)):
        candidates = [
            item.get("path") if isinstance(item, dict) else item
            for item in value
        ]
    else:
        candidates = []
    for candidate in candidates:
        cleaned = str(candidate or "").replace("\\", "/")
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return tuple(values)


def _fact_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return {"items": list(value)}
    return {"value": value}


def _context_facts(active_state: dict[str, Any]) -> tuple[tuple[ContextFact, ...], int]:
    current_source = str(active_state.get("source_revision") or "")
    current_workspace = str(active_state.get("workspace_revision") or "")
    candidates: list[ContextFact] = []
    for state_key, kind in _FACT_KIND_BY_STATE_KEY.items():
        value = active_state.get(state_key)
        if value in (None, "", [], (), {}):
            continue
        values = (
            value
            if state_key in {"recent_reads", "feature_states"}
            and isinstance(value, list)
            else [value]
        )
        for item in values:
            payload = (
                {"path": item}
                if state_key == "recent_reads" and isinstance(item, str)
                else _fact_payload(item)
            )
            payload["state_key"] = state_key
            item_source = str(payload.get("source_revision") or current_source)
            item_workspace = str(payload.get("workspace_revision") or current_workspace)
            revision_persistent = kind is ContextFactKind.REQUIREMENT or (
                kind is ContextFactKind.STRUCTURAL
                and payload.get("feature_id") == "obligations"
            )
            freshness = (
                FactFreshness.STALE
                if not revision_persistent
                and current_source
                and item_source
                and item_source != current_source
                else FactFreshness.CURRENT
            )
            material = json.dumps(
                [kind.value, item_source, item_workspace, payload],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            content_hash = hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()
            candidates.append(
                ContextFact(
                    fact_id="fact-" + content_hash[:20],
                    kind=kind,
                    source_revision=item_source,
                    workspace_revision=item_workspace,
                    evidence_action=int(payload.get("action_id") or 0),
                    paths=_paths_from_value(item),
                    symbols=tuple(
                        str(symbol)
                        for symbol in (
                            (payload.get("symbols"),)
                            if isinstance(payload.get("symbols"), str)
                            else payload.get("symbols") or ()
                        )
                    ),
                    payload=payload,
                    content_hash=content_hash,
                    freshness=freshness,
                )
            )
    unique: dict[str, ContextFact] = {}
    for fact in candidates:
        unique[fact.fact_id] = fact
    return tuple(unique.values()), max(0, len(candidates) - len(unique))


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
    assistant = messages[start]
    # Tool-call IDs are transport-local and differ across retries.  The
    # command, assistant reasoning, action metadata, tool output, and tool
    # status are semantic evidence and must all participate in deduplication.
    # Previously only command text and output text were hashed, so two turns
    # with the same prose but different return codes could be collapsed.
    actions = []
    for action in (assistant.get("extra") or {}).get("actions") or []:
        normalized = dict(action)
        normalized.pop("tool_call_id", None)
        normalized.pop("id", None)
        actions.append(normalized)
    tool_turns = []
    for idx in range(start + 1, end):
        tool = dict(messages[idx])
        tool.pop("tool_call_id", None)
        tool_turns.append(tool)
    return hashlib.sha256(
        json.dumps(
            [
                str(assistant.get("content") or ""),
                str(assistant.get("reasoning_content") or ""),
                actions,
                tool_turns,
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
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


_DIAGNOSTIC_LINE_RE = re.compile(
    r"(?i)(?:traceback|exception|error|failed?|assert(?:ion)?|panic|fatal|warning)"
)


def _tool_return_code(message: dict[str, Any]) -> int | None:
    extra = message.get("extra")
    if isinstance(extra, dict) and extra.get("returncode") is not None:
        try:
            return int(extra["returncode"])
        except (TypeError, ValueError):
            return None
    match = re.search(r"<returncode>\s*(-?\d+)\s*</returncode>", str(message.get("content") or ""))
    return int(match.group(1)) if match else None


def _bound_tool_content(
    content: str,
    *,
    return_code: int | None,
    max_chars: int = 20_000,
) -> tuple[str, int]:
    """Create a deterministic head/diagnostic/tail provider observation."""

    if len(content) <= max_chars:
        return content, 0
    digest = hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()
    notice = (
        "\n[Tool output bounded by host: "
        f"full_chars={len(content)} omitted_chars={{omitted}} sha256={digest}; "
        "use a narrower command if omitted detail is required.]\n"
    )
    payload_budget = max(2_000, max_chars - len(notice.format(omitted=0)))
    diagnostics = ""
    if return_code not in (None, 0):
        selected: list[str] = []
        used = 0
        for line in content.splitlines():
            if not _DIAGNOSTIC_LINE_RE.search(line):
                continue
            normalized = line.rstrip()
            if not normalized or normalized in selected:
                continue
            addition = len(normalized) + 1
            if used + addition > 4_000:
                break
            selected.append(normalized)
            used += addition
        if selected:
            diagnostics = "\n[Selected diagnostic lines]\n" + "\n".join(selected) + "\n"
    remaining = max(1_000, payload_budget - len(diagnostics))
    head_chars = min(8_000 if not diagnostics else 6_000, remaining // 2)
    tail_chars = max(1, remaining - head_chars)
    omitted = max(0, len(content) - head_chars - tail_chars)
    bounded = (
        content[:head_chars]
        + notice.format(omitted=omitted)
        + diagnostics
        + content[-tail_chars:]
    )
    if len(bounded) > max_chars:
        bounded = bounded[:max_chars]
    return bounded, max(0, len(content) - len(bounded))


def _prepare_provider_history(
    messages: list[dict[str, Any]],
    *,
    observation_limit_chars: int = 20_000,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Bound tool bodies and represent later exact duplicates append-only."""

    prepared = copy.deepcopy(messages)
    bounded_count = 0
    bounded_removed = 0
    for item in prepared:
        if item.get("role") != "tool":
            continue
        original = str(item.get("content") or "")
        bounded, omitted = _bound_tool_content(
            original,
            return_code=_tool_return_code(item),
            max_chars=max(2_000, int(observation_limit_chars)),
        )
        if omitted:
            item["content"] = bounded
            bounded_count += 1
            bounded_removed += omitted

    duplicate_count = 0
    duplicate_removed = 0
    first_by_fingerprint: dict[str, int] = {}
    original_turns = _turn_bounds(messages)
    prepared_turns = _turn_bounds(prepared)
    for position, ((original_start, original_end), (start, end)) in enumerate(
        zip(original_turns, prepared_turns, strict=False)
    ):
        fingerprint = _turn_fingerprint(messages, original_start, original_end)
        if fingerprint not in first_by_fingerprint:
            first_by_fingerprint[fingerprint] = position
            continue
        prior = first_by_fingerprint[fingerprint]
        duplicate_count += 1
        for index in range(start + 1, end):
            tool = prepared[index]
            old = str(tool.get("content") or "")
            full_original = str(messages[original_start + (index - start)].get("content") or "")
            digest = hashlib.sha256(
                full_original.encode("utf-8", "surrogatepass")
            ).hexdigest()
            replacement = (
                f"[Exact duplicate of prior action {prior + 1}; "
                f"output_sha256={digest} chars={len(full_original)}.]"
            )
            tool["content"] = replacement
            duplicate_removed += max(0, len(old) - len(replacement))

    return prepared, {
        "bounded_count": bounded_count,
        "bounded_removed": bounded_removed,
        "duplicate_count": duplicate_count,
        "duplicate_removed": duplicate_removed,
    }


def _clear_old_tool_results(
    view: list[dict[str, Any]],
    *,
    target_chars: int,
    keep_recent_turns: int,
) -> tuple[list[dict[str, Any]], int]:
    """Clear only old tool bodies; preserve every assistant message exactly."""

    cleared = copy.deepcopy(view)
    turns = _turn_bounds(cleared)
    protected = max(1, int(keep_recent_turns))
    clearable = turns[: max(0, len(turns) - protected)]
    count = 0
    for start, end in clearable:
        if _chars(cleared) <= target_chars:
            break
        for index in range(start + 1, end):
            tool = cleared[index]
            original = str(tool.get("content") or "")
            if original.startswith("[Earlier tool result cleared:"):
                continue
            digest = hashlib.sha256(
                original.encode("utf-8", "surrogatepass")
            ).hexdigest()
            tool["content"] = (
                f"[Earlier tool result cleared: chars={len(original)} "
                f"sha256={digest} returncode={_tool_return_code(tool)}.]"
            )
            count += 1
    return cleared, count


def _bounded_text(value: Any, limit: int) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _render_read_observations(value: Any) -> str:
    if not isinstance(value, list):
        return _bounded_text(value, 600)
    rendered: list[str] = []
    for item in value[-12:]:
        if not isinstance(item, dict):
            rendered.append(_bounded_text(item, 100))
            continue
        path = _bounded_text(item.get("path"), 180)
        start = item.get("start_line")
        end = item.get("end_line")
        if start is not None:
            path += f":{start}-{end if end is not None else start}"
        revision = _bounded_text(item.get("source_revision"), 48)
        status = f"rc={item.get('returncode')}" if item.get("returncode") is not None else ""
        rendered.append("@".join(part for part in (path, revision, status) if part))
    return ", ".join(item for item in rendered if item)


def _render_state_value(key: str, value: Any) -> str:
    if isinstance(value, dict) and set(value) == {"value"}:
        return _bounded_text(value["value"], 600)
    if key == "recent_reads":
        return _render_read_observations(value)
    if key == "last_edit" and isinstance(value, dict):
        command = str(value.get("command") or "")
        command_hash = hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()[:16]
        first_line = _bounded_text(command.splitlines()[0] if command else "", 120)
        paths = ",".join(_bounded_text(item, 160) for item in value.get("paths") or ())
        return "; ".join(
            part
            for part in (
                f"paths={paths}" if paths else "",
                f"source_revision={_bounded_text(value.get('source_revision'), 48)}",
                f"command={first_line}" if first_line else "",
                f"command_sha256={command_hash}",
            )
            if part
        )
    if key == "latest_validation" and isinstance(value, dict):
        return "; ".join(
            part
            for part in (
                f"command={_bounded_text(value.get('command'), 180)}",
                f"returncode={value.get('returncode')}",
                f"source_revision={_bounded_text(value.get('source_revision'), 48)}",
            )
            if part
        )
    if key in {"unresolved_failure", "latest_failure"} and isinstance(value, dict):
        return "; ".join(
            part
            for part in (
                f"command={_bounded_text(value.get('command'), 160)}",
                f"diagnostic={_bounded_text(value.get('diagnostic'), 360)}",
                f"fingerprint={_bounded_text(value.get('fingerprint'), 80)}",
                f"source_revision={_bounded_text(value.get('source_revision'), 48)}",
            )
            if part and not part.endswith("=")
        )
    if key == "declared_checks" and isinstance(value, dict):
        return ", ".join(
            f"{_bounded_text(name, 180)}={_bounded_text(state, 40)}"
            for name, state in value.items()
        )
    if isinstance(value, (list, tuple)):
        return ", ".join(_bounded_text(item, 240) for item in value[:20])
    if isinstance(value, dict):
        return _bounded_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), 600
        )
    return _bounded_text(value, 600)


_CONTROLLER_ONLY_FACT_KINDS = frozenset(
    {ContextFactKind.REVISION, ContextFactKind.STRUCTURAL}
)
_FACT_PRIORITY = {
    ContextFactKind.FAILURE: 0,
    ContextFactKind.VALIDATION: 1,
    ContextFactKind.DECISION: 2,
    ContextFactKind.REQUIREMENT: 3,
    ContextFactKind.CHECK: 4,
    ContextFactKind.CHANGE: 5,
    ContextFactKind.READ: 6,
}
_FACT_LABELS = {
    ContextFactKind.FAILURE: "Unresolved failure",
    ContextFactKind.VALIDATION: "Latest validation",
    ContextFactKind.DECISION: "Current decision evidence",
    ContextFactKind.REQUIREMENT: "Unresolved requirements",
    ContextFactKind.CHECK: "Declared checks",
    ContextFactKind.CHANGE: "Changed source state",
    ContextFactKind.READ: "Files already read",
}


def _action_commands(message: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(action.get("command") or action.get("cmd") or "")
        for action in (message.get("extra") or {}).get("actions") or ()
    )


def _paired_tool_indices(messages: list[dict[str, Any]], assistant_index: int) -> list[int]:
    indices: list[int] = []
    index = assistant_index + 1
    while index < len(messages) and messages[index].get("role") == "tool":
        indices.append(index)
        index += 1
    return indices


def _indices_containing(
    messages: list[dict[str, Any]], needle: str, *, roles: set[str] | None = None
) -> list[int]:
    if not needle:
        return []
    return [
        index
        for index, message in enumerate(messages)
        if (roles is None or str(message.get("role") or "") in roles)
        and needle in str(message.get("content") or "")
    ]


def _command_turn_indices(
    messages: list[dict[str, Any]], command: str
) -> list[int]:
    if not command:
        return []
    normalized = " ".join(command.strip().split())
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "assistant":
            continue
        if any(
            candidate == command or " ".join(candidate.strip().split()) == normalized
            for candidate in _action_commands(message)
        ):
            return [index, *_paired_tool_indices(messages, index)]
    return []


def _command_mentions_path(command: str, path: str) -> bool:
    normalized_path = str(path or "").replace("\\", "/").strip()
    if not normalized_path:
        return False
    relative = normalized_path
    if relative.startswith("/app/"):
        relative = relative[5:]
    elif relative.startswith("./"):
        relative = relative[2:]
    forms = tuple(dict.fromkeys((normalized_path, relative, f"./{relative}", f"/app/{relative}")))
    normalized_command = str(command or "").replace("\\", "/")
    for form in forms:
        if not form:
            continue
        pattern = rf"(?<![A-Za-z0-9_./-]){re.escape(form)}(?![A-Za-z0-9_./-])"
        if re.search(pattern, normalized_command):
            return True
    return False


def _fact_representation_indices(
    fact: ContextFact, messages: list[dict[str, Any]]
) -> list[int]:
    """Return exact provider-message indices that mechanically represent a fact."""

    state_key = str(fact.payload.get("state_key") or "")
    if fact.kind is ContextFactKind.READ:
        for path in fact.paths:
            for index in range(len(messages) - 1, -1, -1):
                message = messages[index]
                if message.get("role") != "assistant":
                    continue
                if any(
                    _command_mentions_path(command, path)
                    for command in _action_commands(message)
                ):
                    tools = _paired_tool_indices(messages, index)
                    if tools:
                        return [index, *tools]
        return []

    if fact.kind is ContextFactKind.CHANGE:
        command = str(fact.payload.get("command") or "")
        if state_key == "last_edit" and command:
            return _command_turn_indices(messages, command)
        if fact.paths:
            for index in range(len(messages) - 1, -1, -1):
                commands = _action_commands(messages[index])
                if commands and all(
                    any(_command_mentions_path(command, path) for command in commands)
                    for path in fact.paths
                ):
                    return [index, *_paired_tool_indices(messages, index)]
        return []

    if fact.kind is ContextFactKind.VALIDATION:
        command = str(fact.payload.get("command") or "")
        turn = _command_turn_indices(messages, command)
        if not turn:
            return []
        expected = fact.payload.get("returncode")
        if expected is None:
            return turn
        for index in turn[1:]:
            message = messages[index]
            extra_code = (message.get("extra") or {}).get("returncode")
            content = str(message.get("content") or "")
            if extra_code == expected or f"<returncode>{expected}</returncode>" in content:
                return turn
        return []

    if fact.kind is ContextFactKind.FAILURE:
        diagnostic = str(fact.payload.get("diagnostic") or "")
        diagnostic_indices = _indices_containing(messages, diagnostic, roles={"tool"})
        if not diagnostic_indices:
            return []
        command_indices = _command_turn_indices(
            messages, str(fact.payload.get("command") or "")
        )
        return sorted(set([*command_indices, *diagnostic_indices]))

    if fact.kind in {ContextFactKind.REQUIREMENT, ContextFactKind.CHECK}:
        raw = fact.payload.get("items", fact.payload.get("value"))
        if isinstance(raw, dict):
            needles = [str(key) for key in raw]
        elif isinstance(raw, (list, tuple)):
            needles = [str(item) for item in raw]
        elif raw not in (None, ""):
            needles = [str(raw)]
        else:
            needles = [
                str(key) for key in fact.payload if key not in {"state_key"}
            ]
        indices: set[int] = set()
        for needle in needles:
            matches = _indices_containing(
                messages, needle, roles={"system", "user", "tool"}
            )
            if not matches:
                return []
            indices.add(matches[-1])
        return sorted(indices)

    if fact.kind is ContextFactKind.DECISION:
        anchors = [*fact.paths, *fact.symbols]
        if not anchors:
            anchors = [
                str(value)
                for key, value in fact.payload.items()
                if key != "state_key" and isinstance(value, (str, int, float))
            ]
        indices: set[int] = set()
        for anchor in anchors:
            matches = _indices_containing(messages, anchor)
            if not matches:
                return []
            indices.add(matches[-1])
        return sorted(indices)
    return []


def _render_fact(fact: ContextFact) -> str:
    state_key = str(fact.payload.get("state_key") or "")
    payload = {key: value for key, value in fact.payload.items() if key != "state_key"}
    render_value: Any = (
        payload["items"] if set(payload) == {"items"} else payload
    )
    if state_key == "recent_reads":
        rendered = _render_state_value("recent_reads", [payload])
    else:
        rendered = _render_state_value(state_key, render_value)
    label = {
        "last_edit": "Latest source edit",
        "changed_paths": "Changed source paths",
        "recent_reads": "Files already read",
        "latest_validation": "Latest validation",
        "unresolved_failure": "Unresolved failure",
        "latest_failure": "Unresolved failure",
        "declared_checks": "Declared checks",
        "project_checks": "Project checks",
        "obligations": "Unresolved requirements",
        "decision": "Current decision evidence",
    }.get(
        state_key,
        _FACT_LABELS.get(fact.kind, fact.kind.value.replace("_", " ").title()),
    )
    return f"{label}: {rendered}" if rendered else ""


def _fact_action_anchors(fact: ContextFact) -> list[str]:
    anchors = [*fact.paths, *fact.symbols]
    for key in ("command", "declared_check", "precedent_path"):
        value = fact.payload.get(key)
        if isinstance(value, str) and value.strip():
            anchors.append(value.strip())
    return list(dict.fromkeys(anchor for anchor in anchors if anchor))


def _compile_fact_frame(
    facts: tuple[ContextFact, ...],
    messages: list[dict[str, Any]],
    *,
    limit: int = 4_000,
) -> tuple[str, tuple[str, ...], list[dict[str, Any]]]:
    """Select only current facts absent from the concrete provider request."""

    ordered = sorted(
        facts,
        key=lambda fact: (
            _FACT_PRIORITY.get(fact.kind, 99),
            -fact.evidence_action,
            fact.fact_id,
        ),
    )
    header = "Current task facts absent from the retained command history:"
    lines = [header]
    selected: list[str] = []
    accounting: list[dict[str, Any]] = []
    for fact in ordered:
        indices: list[int] = []
        if fact.freshness is FactFreshness.STALE:
            disposition = "stale_source_revision"
        elif fact.kind in _CONTROLLER_ONLY_FACT_KINDS:
            disposition = "controller_only"
        else:
            indices = _fact_representation_indices(fact, messages)
            if indices:
                disposition = "represented_message"
            else:
                line = _render_fact(fact)
                if line and len("\n".join((*lines, line))) <= limit:
                    lines.append(line)
                    selected.append(fact.fact_id)
                    disposition = "selected_state_frame"
                else:
                    disposition = "state_frame_budget"
        accounting.append(
            {
                "fact_id": fact.fact_id,
                "kind": fact.kind.value,
                "state_key": str(fact.payload.get("state_key") or ""),
                "feature_id": str(fact.payload.get("feature_id") or ""),
                "effect_id": str(fact.payload.get("effect_id") or ""),
                "source_revision": fact.source_revision,
                "workspace_revision": fact.workspace_revision,
                "evidence_action": fact.evidence_action,
                "paths": list(fact.paths),
                "action_anchors": _fact_action_anchors(fact),
                "content_hash": fact.content_hash,
                "disposition": disposition,
                "provider_message_indices": indices,
            }
        )
    state_text = "\n".join(lines) if selected else ""
    return state_text, tuple(selected), accounting


def _assistant_reasoning_chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(str(item.get("content") or ""))
        + len(str(item.get("reasoning_content") or ""))
        for item in messages
        if item.get("role") == "assistant"
    )


def _provider_metrics(
    *,
    compacted: bool,
    raw_input_chars: int,
    input_chars: int,
    view: list[dict[str, Any]],
    preserved_recent_messages: int,
    state_text: str,
    duplicate_turns_removed: int,
    duplicate_fact_count: int,
    selected_fact_ids: tuple[str, ...],
    accounting: tuple[dict[str, Any], ...],
    assistant_reasoning_input_chars: int,
    exact_duplicate_chars_removed: int = 0,
    bounded_observation_count: int = 0,
    bounded_observation_chars_removed: int = 0,
    duplicate_turns_represented: int = 0,
    old_tool_results_cleared: int = 0,
    state_frame_message_index: int | None = None,
) -> ProviderViewMetrics:
    output_chars = _chars(view)
    dispositions = [str(row["disposition"]) for row in accounting]
    omitted_reasons = {
        str(row["fact_id"]): str(row["disposition"])
        for row in accounting
        if row["disposition"] not in {"selected_state_frame", "represented_message"}
    }
    return ProviderViewMetrics(
        compiler_ran=True,
        compacted=compacted,
        raw_input_chars=raw_input_chars,
        input_chars=input_chars,
        output_chars=output_chars,
        elided_chars=max(0, input_chars - output_chars),
        preserved_recent_messages=preserved_recent_messages,
        active_state_chars=len(state_text),
        duplicate_turns_removed=duplicate_turns_removed,
        exact_duplicate_chars_removed=max(0, exact_duplicate_chars_removed),
        unique_assistant_reasoning_chars_removed=max(
            0, assistant_reasoning_input_chars - _assistant_reasoning_chars(view)
        ),
        candidate_fact_count=len(accounting),
        selected_fact_count=dispositions.count("selected_state_frame"),
        represented_fact_count=dispositions.count("represented_message"),
        controller_only_fact_count=dispositions.count("controller_only"),
        omitted_fact_count=sum(
            disposition
            not in {"selected_state_frame", "represented_message"}
            for disposition in dispositions
        ),
        accounted_fact_count=len(accounting),
        stale_fact_count=dispositions.count("stale_source_revision"),
        duplicate_fact_count=duplicate_fact_count,
        selected_fact_ids=selected_fact_ids,
        omitted_fact_reasons=omitted_reasons,
        fact_accounting=accounting,
        frame_sha256=(
            hashlib.sha256(state_text.encode("utf-8", "replace")).hexdigest()
            if state_text
            else ""
        ),
        bounded_observation_count=bounded_observation_count,
        bounded_observation_chars_removed=bounded_observation_chars_removed,
        duplicate_turns_represented=duplicate_turns_represented,
        old_tool_results_cleared=old_tool_results_cleared,
        state_frame_message_index=state_frame_message_index,
    )


def _attach_state_frame(
    view: list[dict[str, Any]], state_text: str
) -> tuple[list[dict[str, Any]], int | None]:
    """Attach one bounded current-state frame to the latest tool result.

    Tool observations are already part of Mini-SWE's durable interaction
    surface.  Reusing that surface avoids inventing a user instruction or a
    model-facing GT marker.  If no tool result survived compaction, the frame
    remains controller-only and the caller records that safe omission.
    """

    if not state_text:
        return view, None
    prepared = [dict(item) for item in view]
    for index in range(len(prepared) - 1, -1, -1):
        if prepared[index].get("role") != "tool":
            continue
        separator = "\n\n"
        prepared[index]["content"] = (
            str(prepared[index].get("content") or "") + separator + state_text
        )
        return prepared, index
    return view, None


def build_provider_view(
    messages: list[dict[str, Any]],
    *,
    active_state: dict[str, Any],
    trigger_chars: int = 120_000,
    target_chars: int = 60_000,
    keep_recent_turns: int = 2,
    transform: bool = True,
) -> tuple[list[dict[str, Any]], ProviderViewMetrics]:
    """Return a bounded provider view without mutating the audit trajectory.

    ``transform=False`` is byte-identical observation-only mode.  Transform
    mode bounds each tool result deterministically, represents later exact
    duplicates append-only, and clears only old tool bodies if the complete
    view still exceeds the configured trigger.  It never deletes assistant
    reasoning.  When clearing removes the only textual representation of a
    current fact, one bounded frame is attached to the latest retained tool
    observation.
    """
    raw_input_chars = _chars(messages)
    reasoning_input_chars = _assistant_reasoning_chars(messages)
    if not transform:
        untouched = copy.deepcopy(messages)
        facts, duplicate_fact_count = _context_facts(active_state)
        _state_text, _selected_fact_ids, compiled_rows = _compile_fact_frame(
            facts, untouched
        )
        accounting = tuple(
            {
                **row,
                "disposition": (
                    "no_compaction_controller_only"
                    if row["disposition"] == "selected_state_frame"
                    else row["disposition"]
                ),
                "provider_message_indices": (
                    []
                    if row["disposition"] == "selected_state_frame"
                    else row["provider_message_indices"]
                ),
            }
            for row in compiled_rows
        )
        return untouched, _provider_metrics(
            compacted=False,
            raw_input_chars=raw_input_chars,
            input_chars=raw_input_chars,
            view=untouched,
            preserved_recent_messages=len(untouched),
            state_text="",
            duplicate_turns_removed=0,
            duplicate_fact_count=duplicate_fact_count,
            selected_fact_ids=(),
            accounting=accounting,
            assistant_reasoning_input_chars=reasoning_input_chars,
        )

    prepared, preparation = _prepare_provider_history(messages)
    input_chars = _chars(prepared)
    facts, duplicate_fact_count = _context_facts(active_state)
    view = prepared
    cleared = 0
    if input_chars > max(1, int(trigger_chars)):
        view, cleared = _clear_old_tool_results(
            view,
            target_chars=max(1, int(target_chars)),
            keep_recent_turns=keep_recent_turns,
        )
    state_text, selected_fact_ids, compiled_rows = _compile_fact_frame(facts, view)
    state_frame_message_index: int | None = None
    if cleared and state_text:
        view, state_frame_message_index = _attach_state_frame(view, state_text)
    if state_frame_message_index is not None:
        compiled_rows = [
            {
                **row,
                "provider_message_indices": [state_frame_message_index]
                if row["disposition"] == "selected_state_frame"
                else row["provider_message_indices"],
            }
            for row in compiled_rows
        ]
    accounting = tuple(
        {
            **row,
            "disposition": (
                "selected_state_frame"
                if (
                    row["disposition"] == "selected_state_frame"
                    and state_frame_message_index is not None
                )
                else "no_safe_delivery_surface"
                if row["disposition"] == "selected_state_frame" and cleared
                else "no_compaction_controller_only"
                if row["disposition"] == "selected_state_frame"
                else row["disposition"]
            ),
            "provider_message_indices": row["provider_message_indices"],
        }
        for row in compiled_rows
    )
    compacted = bool(
        preparation["bounded_count"]
        or preparation["duplicate_count"]
        or cleared
    )
    return view, _provider_metrics(
        compacted=compacted,
        raw_input_chars=raw_input_chars,
        input_chars=input_chars,
        view=view,
        preserved_recent_messages=len(view),
        state_text=state_text if state_frame_message_index is not None else "",
        duplicate_turns_removed=0,
        duplicate_fact_count=duplicate_fact_count,
        selected_fact_ids=(
            selected_fact_ids if state_frame_message_index is not None else ()
        ),
        accounting=accounting,
        assistant_reasoning_input_chars=reasoning_input_chars,
        exact_duplicate_chars_removed=preparation["duplicate_removed"],
        bounded_observation_count=preparation["bounded_count"],
        bounded_observation_chars_removed=preparation["bounded_removed"],
        duplicate_turns_represented=preparation["duplicate_count"],
        old_tool_results_cleared=cleared,
        state_frame_message_index=state_frame_message_index,
    )
