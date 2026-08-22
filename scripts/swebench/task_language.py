"""Authoritative task-language derivation for metadata-only SWE task manifests."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Mapping

_EXTENSION_LANGUAGE = {
    ".py": "python", ".pyi": "python", ".go": "go", ".js": "js",
    ".jsx": "js", ".ts": "ts", ".tsx": "ts", ".rs": "rust",
    ".java": "java",
}
_SUPPORTED_LANGUAGES = set(_EXTENSION_LANGUAGE.values())
_DIFF_PATH = re.compile(r"^diff --git a/(.+?) b/", re.MULTILINE)


def normalize_language(value: object) -> str | None:
    """Normalize an explicitly declared language, rejecting unknown values."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    value = {"javascript": "js", "typescript": "ts"}.get(value, value)
    return value if value in _SUPPORTED_LANGUAGES else None


def _add_paths(counts: Counter[str], values: object) -> None:
    items = values if isinstance(values, list) else []
    if isinstance(values, str):
        try:
            parsed = json.loads(values)
        except ValueError:
            parsed = []
        items = parsed if isinstance(parsed, list) else []
    for item in items:
        if not isinstance(item, str):
            continue
        path = item.split("::", 1)[0]
        for suffix, language in _EXTENSION_LANGUAGE.items():
            if path.lower().endswith(suffix):
                counts[language] += 1
                break


def derive_task_language(task: Mapping[str, object]) -> str | None:
    """Derive language from task-owned metadata, failing closed when unknown."""
    for key in ("repo_language", "language"):
        declared = normalize_language(task.get(key))
        if declared:
            return declared

    counts: Counter[str] = Counter()
    for field in ("patch", "test_patch"):
        value = task.get(field)
        if not isinstance(value, str):
            continue
        for path in _DIFF_PATH.findall(value):
            path = path.split("\t", 1)[0]
            for suffix, language in _EXTENSION_LANGUAGE.items():
                if path.lower().endswith(suffix):
                    counts[language] += 1
                    break

    if not counts:
        _add_paths(counts, task.get("FAIL_TO_PASS"))
        _add_paths(counts, task.get("PASS_TO_PASS"))
    if not counts:
        return None
    return sorted(counts, key=lambda language: (-counts[language], language))[0]


__all__ = ["derive_task_language", "normalize_language"]
