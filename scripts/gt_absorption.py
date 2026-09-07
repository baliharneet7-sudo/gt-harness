#!/usr/bin/env python3
"""Measure whether the model acted on what GT delivered.

Absence is not evidence here. "GT named a, b, c and the model opened d" is
consistent with three different worlds -- absorbed and moved on, ignored, and
GT was wrong so it looked elsewhere -- and an action trace cannot separate
them. So this measures the positive direction only:

    After GT delivers a fact naming identifier X, does the model's next
    command reference X, when X appears NOWHERE earlier in anything the model
    could see?

A first mention that originates in a GT delivery and is then used by the model
has one explanation. That is the whole point of the first-mention filter: an
identifier the model had already seen proves nothing, because the model could
have carried it from its own earlier output.

This is an instrument, not a gate. It reports; it never fails a run.

Usage:
    python scripts/gt_absorption.py <run-artifact-dir>

It locates events.jsonl, the delivery blobs beside it, and the agent
trajectory, wherever they sit under the given directory.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# Identifiers worth attributing: dotted/underscored symbol names and repo
# paths. Deliberately excludes bare short words, which collide with English
# and would manufacture attribution out of prose.
_SYMBOL = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")
_PATH = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|mjs|cjs|go|rb|pyi)\b")

# Tokens that carry no attribution: GT's own envelope vocabulary, plus the
# most common English/code words. A hit on "schema" is not the model using GT.
_STOP = {
    "schema", "sha256", "encoding", "kind", "total_length", "retrieval_command",
    "unit_id", "supersession_key", "source_revision", "supersedes", "historical",
    "action_index", "delivery_identity", "evidence", "context", "reference",
    "utf-8", "true", "false", "null", "none", "this", "that", "with", "from",
    "have", "will", "then", "when", "what", "which", "there", "these", "those",
    "gt_context_unit", "gt_context_unit_reference", "gt_history_evidence",
    "gt_history_ref", "decision_evidence",
}


def _identifiers(text: str) -> set[str]:
    found = {m.group(0) for m in _PATH.finditer(text)}
    for match in _SYMBOL.finditer(text):
        token = match.group(0)
        if token.lower() in _STOP or token.isdigit():
            continue
        found.add(token)
    return found


def _find(root: Path, name: str) -> Path | None:
    if (root / name).is_file():
        return root / name
    return next(iter(sorted(root.rglob(name))), None)


def _agent_commands(root: Path) -> list[str]:
    """The model's own commands, in order."""

    trajectory = _find(root, "miniswe_trajectory.json") or _find(root, "traj.json")
    if trajectory is None:
        return []
    payload = json.loads(trajectory.read_text(encoding="utf-8", errors="replace"))
    commands: list[str] = []
    for message in payload.get("messages") or []:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(arguments.get("command"), str):
                commands.append(arguments["command"])
    return commands


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(argv[1]).resolve()
    journal = _find(root, "events.jsonl")
    if journal is None:
        print(f"no events.jsonl under {root}")
        return 2

    deliveries: list[dict] = []
    for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("event") in {"context_addition_delivery", "evidence_delivery"}:
            deliveries.append(row)

    # The journal and the delivery blobs do not always share a parent: a run
    # artifact carries both agent/events.jsonl and agent/gt-state/<task>/, and
    # the blobs live beside the latter. Resolve by finding the directory, not
    # by assuming the layout.
    blob_root = journal.parent / "deliveries"
    if not blob_root.is_dir():
        candidates = [d for d in root.rglob("deliveries") if d.is_dir()]
        if candidates:
            blob_root = max(candidates, key=lambda d: len(list(d.glob("*.json"))))
    commands = _agent_commands(root)
    command_text = "\n".join(commands)

    # Everything the model itself said before GT said it. An identifier the
    # model produced first cannot have been learned from GT.
    seen_before: set[str] = set()
    per_command_ids = [_identifiers(command) for command in commands]

    # Prefix of the model's own vocabulary, by action index. An identifier the
    # model had already typed is NOT attributable to GT however novel it looks
    # to GT's own delivery history, so the baseline must include the agent's
    # prior commands, not just prior deliveries.
    command_prefix: list[set[str]] = []
    running: set[str] = set()
    for ids in per_command_ids:
        command_prefix.append(set(running))
        running |= ids

    total = referenced = pointer_only = 0
    deliveries_with_novel = 0
    novel_total = novel_used = 0
    by_kind: Counter[str] = Counter()
    used_by_kind: Counter[str] = Counter()
    unresolved_pointers = 0

    for index, delivery in enumerate(deliveries):
        identity = str(delivery.get("payload_sha256") or delivery.get("delivery_identity") or "")
        kind = str(delivery.get("kind") or "?")
        blob = blob_root / f"{identity}.json" if identity else None
        text = ""
        if blob is not None and blob.is_file():
            text = blob.read_text(encoding="utf-8", errors="replace")
        if not text:
            continue
        total += 1
        by_kind[kind] += 1

        is_pointer = "GT_CONTEXT_UNIT_REFERENCE" in text or "GT_HISTORY_EVIDENCE" in text
        if is_pointer:
            pointer_only += 1
            if "gt-evidence" not in command_text:
                unresolved_pointers += 1

        delivered_ids = _identifiers(text)
        try:
            action_index = int(delivery.get("action_index") or 0)
        except (TypeError, ValueError):
            action_index = 0
        action_index = max(0, min(action_index, len(command_prefix) - 1)) if command_prefix else 0
        already_typed = command_prefix[action_index] if command_prefix else set()
        # Novel = neither GT nor the MODEL had produced it before this point.
        novel = {t for t in delivered_ids if t not in seen_before and t not in already_typed}
        novel_total += len(novel)
        if novel:
            deliveries_with_novel += 1

        # Did any LATER command use one of them?
        used = set()
        for later in per_command_ids[action_index + 1:]:
            used |= novel & later
        if used:
            referenced += 1
            used_by_kind[kind] += 1
        novel_used += len(used)

        seen_before |= delivered_ids

    print(f"journal            : {journal}")
    print(f"deliveries examined: {total}   (blobs read from {blob_root.name}/)")
    print()
    print("POINTER DELIVERIES -- content the model had to fetch itself")
    print(f"  shipped as a pointer            : {pointer_only}")
    print(f"  never dereferenced by the model : {unresolved_pointers}")
    print(f"  'gt-evidence' commands issued   : {sum('gt-evidence' in c for c in commands)}")
    print()
    print("ATTRIBUTABLE USE -- identifiers GT introduced first, later used by the model")
    print(f"  deliveries introducing a novel identifier : {deliveries_with_novel}/{total}")
    print(f"  novel identifiers delivered               : {novel_total}")
    print(f"  novel identifiers later used by the model : {novel_used}")
    if novel_total:
        print(f"  attributable use rate                     : {100 * novel_used / novel_total:.1f}%")
    if total:
        print(f"  deliveries with >=1 attributable use      : {referenced}/{total}"
              f" ({100 * referenced / total:.1f}%)")
    print()
    print("BY KIND (deliveries -> deliveries with attributable use)")
    for kind, count in by_kind.most_common():
        used = used_by_kind[kind]
        print(f"  {kind:38s} {count:>4} -> {used:>4}  ({100 * used / count:.0f}%)")
    print()
    print(f"model commands: {len(commands)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
