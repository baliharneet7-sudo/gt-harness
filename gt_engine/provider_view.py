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
        }


def _chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)) for item in messages
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


def _apply_frame_index(
    accounting: list[dict[str, Any]], *, insertion_index: int
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for original in accounting:
        row = dict(original)
        indices = [int(index) for index in row["provider_message_indices"]]
        if row["disposition"] == "selected_state_frame":
            indices = [insertion_index]
        else:
            indices = [index + 1 if index >= insertion_index else index for index in indices]
        row["provider_message_indices"] = indices
        rows.append(row)
    return tuple(rows)


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
        exact_duplicate_chars_removed=max(0, raw_input_chars - input_chars),
        unique_assistant_reasoning_chars_removed=0,
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
    )


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
    transform: bool = True,
) -> tuple[list[dict[str, Any]], ProviderViewMetrics]:
    """Return a compact inference view without mutating the audit history.

    1. Byte-identical duplicate assistant/tool turns are dropped first, so no
       duplicate text is ever sent.
    2. If the deduped view still exceeds the trigger, only older turns are
       summarized and the typed state summary (progress ledger) is injected.
    3. The most recent assistant/tool turns remain verbatim.
    """
    raw_input_chars = _chars(messages)
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
        )
    deduped = dedupe_provider_view(copy.deepcopy(messages))
    input_chars = _chars(deduped)
    duplicate_turns_removed = max(0, len(_turn_bounds(messages)) - len(_turn_bounds(deduped)))
    facts, duplicate_fact_count = _context_facts(active_state)

    if input_chars <= max(1, int(trigger_chars)):
        _state_text, _selected_fact_ids, compiled_rows = _compile_fact_frame(
            facts, deduped
        )
        # Below the compaction threshold the stock provider history is already
        # authoritative.  Private engine state is accounted for, but missing
        # facts are not converted into an extra user turn on every request.
        # Decision-relevant one-shot evidence uses the semantic delivery path.
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
        return deduped, _provider_metrics(
            compacted=False,
            raw_input_chars=raw_input_chars,
            input_chars=input_chars,
            view=deduped,
            preserved_recent_messages=len(deduped),
            state_text="",
            duplicate_turns_removed=duplicate_turns_removed,
            duplicate_fact_count=duplicate_fact_count,
            selected_fact_ids=(),
            accounting=accounting,
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
    target = max(1, int(target_chars))
    while True:
        base_view = [*prefix, *middle, *recent]
        state_text, selected_fact_ids, accounting_rows = _compile_fact_frame(
            facts, base_view
        )
        insertion_index = len(prefix) + len(middle)
        view = [*prefix, *middle]
        if state_text:
            view.append({"role": "user", "content": state_text})
        view.extend(recent)
        if _chars(view) <= target or len(middle) < 2:
            break
        removed = middle.pop(0)
        if removed.get("role") == "assistant":
            while middle and middle[0].get("role") == "tool":
                middle.pop(0)

    accounting = _apply_frame_index(
        accounting_rows, insertion_index=insertion_index
    )
    return view, _provider_metrics(
        compacted=True,
        raw_input_chars=raw_input_chars,
        input_chars=input_chars,
        view=view,
        preserved_recent_messages=len(recent),
        state_text=state_text,
        duplicate_turns_removed=duplicate_turns_removed,
        duplicate_fact_count=duplicate_fact_count,
        selected_fact_ids=selected_fact_ids,
        accounting=accounting,
    )
