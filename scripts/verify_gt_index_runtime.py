#!/usr/bin/env python3
"""Provider-free proof that the paid host can build and query a GT graph."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gt_engine.indexer import IndexBuildStatus  # noqa: E402
from gt_engine.repository_intelligence import inspect_index  # noqa: E402


def verify() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gt-index-fixture-") as root_dir:
        root = Path(root_dir)
        (root / "fixture.py").write_text(
            "def target(value: int) -> int:\n"
            "    return value + 1\n\n"
            "def caller() -> int:\n"
            "    return target(1)\n",
            encoding="utf-8",
        )
        receipt = inspect_index(root, state_dir=root / ".state")
        if receipt.status is not IndexBuildStatus.AVAILABLE or not receipt.graph_db:
            raise RuntimeError(
                "repository index unavailable: "
                f"status={receipt.status.value} error={receipt.error_type or 'none'}"
            )
        graph = Path(receipt.graph_db)
        connection = sqlite3.connect(f"file:{graph.resolve().as_posix()}?mode=ro", uri=True)
        try:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            definition_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM nodes WHERE name IN ('target','caller')"
                ).fetchone()[0]
            )
            call_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM edges e "
                    "JOIN nodes src ON src.id=e.source_id "
                    "JOIN nodes tgt ON tgt.id=e.target_id "
                    "WHERE e.type='CALLS' AND src.name='caller' AND tgt.name='target'"
                ).fetchone()[0]
            )
        finally:
            connection.close()
        if quick_check.lower() != "ok":
            raise RuntimeError(f"graph quick_check failed: {quick_check}")
        if definition_count < 2:
            raise RuntimeError(f"fixture definitions missing: {definition_count}")
        if call_count < 1:
            raise RuntimeError(f"directed CALLS edge missing: {call_count}")
        return {
            "status": receipt.status.value,
            "graph_revision": receipt.graph_revision,
            "binary_sha256": receipt.binary_sha256,
            "elapsed_ms": receipt.elapsed_ms,
            "definition_count": definition_count,
            "call_count": call_count,
        }


def main() -> int:
    try:
        result = verify()
    except Exception as exc:  # noqa: BLE001 - CLI must expose one fail-closed result
        print(f"REPOSITORY_SUBSTRATE_FAILED {type(exc).__name__}: {exc}")
        return 1
    print("REPOSITORY_SUBSTRATE_PROVEN")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
