"""Provider-visible GT consumption ledger.

This module is intentionally dependency-free so the benchmark collectors can
run on the GT-OFF control arm.  It preserves the public ledger API used by the
deep/performance/behavior collectors; an empty control trajectory therefore
produces a valid, explicitly empty ledger instead of an infrastructure error.
For GT-ON trajectories it records each closed GT block found in a
model-visible message and never treats private/controller data as delivered.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

MODEL_VISIBLE_SOURCES = frozenset({"model_visible_message", "trajectory_message"})
_BLOCK_RE = re.compile(r"<(gt-[a-z0-9_-]+)\b[^>]*>.*?</\1>", re.I | re.S)
_FILE_RE = re.compile(r'file="([^"]+)"', re.I)


def _typed_lineage_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    lineage = row.get("lineage")
    return dict(lineage) if isinstance(lineage, dict) else None


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or item.get("content") or "")
            for item in content if isinstance(item, dict)
        )
    return ""


def build_consumption_ledger(
    trajectory: dict[str, Any] | list[dict[str, Any]],
    *,
    runtime_ledger_path: str | None = None,
    window: int | None = None,
    **_: Any,
) -> dict[str, Any]:
    messages = trajectory if isinstance(trajectory, list) else (
        trajectory.get("messages", []) if isinstance(trajectory, dict) else []
    )
    entries: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") not in {"user", "tool"}:
            continue
        text = _message_text(message)
        for match in _BLOCK_RE.finditer(text):
            body = match.group(0)
            kind = match.group(1).lower()
            files = _FILE_RE.findall(body)
            entries.append({
                "entry_id": f"trajectory-{index}-{len(entries)}",
                "source": "model_visible_message",
                "message_index": index,
                "tag": kind,
                "content_sha256_16": _content_hash(body),
                "chars_delivered": len(body),
                "files": files,
                "level": 1,
                "consumed": False,
                "resolved_state": None,
                "lineage": None,
            })
    return {
        "schema": "gt.consumption_ledger.v2",
        "entries": entries,
        "ledger_rows_delivered": len(entries),
        "ledger_rows_joined": len(entries),
        "gt_blocks_delivered": len(entries),
        "gt_blocks_consumed": 0,
        "runtime_ledger_path": runtime_ledger_path,
        "window": window,
    }


def ledger_from_trajectory_path(
    trajectory_path: str,
    *,
    runtime_ledger_path: str | None = None,
    window: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        with open(trajectory_path, encoding="utf-8") as stream:
            trajectory = json.load(stream)
    except (OSError, ValueError, TypeError):
        trajectory = {}
    return build_consumption_ledger(
        trajectory, runtime_ledger_path=runtime_ledger_path,
        window=window, **kwargs
    )
