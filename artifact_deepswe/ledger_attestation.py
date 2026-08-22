"""Content attestation for harvested GroundTruth runtime ledgers.

The Live Lite collector must distinguish a regenerated per-task ledger from a
byte-for-byte copy of another task's receipt.  This module is deliberately
small and deterministic: it records the ledger hash, byte count, line count,
task-scoped basename, and writer-failure count.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "gt.runtime_ledger_attestation.v1"


def _digest(path: Path) -> tuple[str, int, int]:
    data = path.read_bytes()
    lines = data.count(b"\n")
    return hashlib.sha256(data).hexdigest(), len(data), lines


def write_attestation(
    ledger_path: str | Path,
    attestation_path: str | Path,
    *,
    write_failures: int = 0,
) -> None:
    ledger = Path(ledger_path)
    target = Path(attestation_path)
    digest, byte_count, line_count = _digest(ledger)
    document = {
        "schema": SCHEMA,
        "ledger_basename": ledger.name,
        "ledger_sha256": digest,
        "byte_count": byte_count,
        "line_count": line_count,
        "write_failures": int(write_failures),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def validate_attestation(
    ledger_path: str | Path,
    attestation_path: str | Path,
) -> bool:
    ledger = Path(ledger_path)
    attestation = Path(attestation_path)
    try:
        document: dict[str, Any] = json.loads(attestation.read_text(encoding="utf-8"))
        digest, byte_count, line_count = _digest(ledger)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False
    return (
        document.get("schema") == SCHEMA
        and document.get("ledger_basename") == ledger.name
        and document.get("ledger_sha256") == digest
        and document.get("byte_count") == byte_count
        and document.get("line_count") == line_count
        and isinstance(document.get("write_failures"), int)
        and document["write_failures"] >= 0
    )
