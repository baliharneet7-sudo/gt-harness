#!/usr/bin/env python3
"""Provider-free proof that the paid host can build and query a GT graph."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gt_engine.indexer import IndexBuildStatus  # noqa: E402
from gt_engine.language_registry import LANGUAGE_CAPABILITIES  # noqa: E402
from gt_engine.repository_intelligence import inspect_repository  # noqa: E402


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
        # These two fixtures certify the parser-backed languages that are easy
        # to accidentally advertise in the host registry while leaving the
        # shipped gt-index binary unable to produce symbols.  Keep them small,
        # source-only, and deterministic: the graph gate must prove the actual
        # binary, not just the Python capability table.
        (root / "fixture.scm").write_text(
            "(define (target value) (+ value 1))\n"
            "(define (caller) (target 1))\n",
            encoding="utf-8",
        )
        (root / "fixture.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FIXTURE.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM HELPER-PARA.\n"
            "           STOP RUN.\n"
            "       HELPER-PARA.\n"
            "           DISPLAY \"ok\".\n",
            encoding="utf-8",
        )
        (root / "fixture.r").write_text(
            "target <- function(value) { value + 1 }\n"
            "caller <- function() { target(1) }\n",
            encoding="utf-8",
        )
        (root / "fixture.v").write_text(
            "module target(input value, output out);\n"
            "  assign out = value;\n"
            "endmodule\n"
            "module caller(input value, output out);\n"
            "  target instance(.value(value), .out(out));\n"
            "endmodule\n",
            encoding="utf-8",
        )
        # Exercise every parser that the host registry advertises.  These
        # files are deliberately separate from the semantic Python/COBOL/
        # Scheme fixtures above: file_hashes proves binary language dispatch,
        # while the named fixtures prove definitions and CALLS edges.
        language_root = root / "language_fixtures"
        for capability in LANGUAGE_CAPABILITIES:
            if not capability.structural_index:
                continue
            suffix = capability.suffixes[0]
            (language_root / f"fixture_{capability.name}{suffix}").parent.mkdir(
                parents=True, exist_ok=True
            )
            (language_root / f"fixture_{capability.name}{suffix}").write_text(
                "/* parser coverage fixture */\n", encoding="utf-8"
            )
        source_revision = "fixture-source-r0"
        evidence = inspect_repository(
            root,
            "Change target so caller uses the indexed definition.",
            state_dir=root / ".state",
            source_revision=source_revision,
        )
        receipt = evidence.index
        if receipt is None:
            raise RuntimeError("repository evidence did not retain index receipt")
        if receipt.status is not IndexBuildStatus.AVAILABLE or not receipt.graph_db:
            raise RuntimeError(
                "repository index unavailable: "
                f"status={receipt.status.value} error={receipt.error_type or 'none'}"
            )
        graph = Path(receipt.graph_db)
        manifest_path = graph.with_suffix(".manifest.json")
        if not manifest_path.is_file():
            raise RuntimeError("graph certification manifest missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("graph_sha256") != receipt.graph_revision:
            raise RuntimeError("graph certification revision mismatch")
        if manifest.get("source_revision") != source_revision:
            raise RuntimeError("graph/source revision binding missing")
        connection = sqlite3.connect(f"file:{graph.resolve().as_posix()}?mode=ro", uri=True)
        try:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            definition_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM nodes WHERE name IN ('target','caller')"
                ).fetchone()[0]
            )
            language_counts = dict(
                connection.execute(
                    "SELECT language, COUNT(*) FROM nodes GROUP BY language"
                ).fetchall()
            )
            language_file_counts = dict(
                connection.execute(
                    "SELECT language, COUNT(*) FROM file_hashes GROUP BY language"
                ).fetchall()
            )
            cobol_count = int(language_counts.get("cobol", 0))
            scheme_count = int(language_counts.get("scheme", 0))
            r_count = int(language_counts.get("r", 0))
            verilog_count = int(language_counts.get("verilog", 0))
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
        if not receipt.schema_valid or receipt.node_count < 2:
            raise RuntimeError("index receipt did not certify the graph schema/nodes")
        if receipt.source_files != receipt.indexable_files:
            raise RuntimeError("fixture source coverage was not complete")
        if cobol_count < 1 or scheme_count < 2:
            raise RuntimeError(
                "certified language parser coverage missing: "
                f"cobol={cobol_count} scheme={scheme_count}"
            )
        if r_count < 2 or verilog_count < 2:
            raise RuntimeError(
                "native language parser coverage missing: "
                f"r={r_count} verilog={verilog_count}"
            )
        expected_languages = {
            "bash" if capability.name == "shell" else capability.name
            for capability in LANGUAGE_CAPABILITIES
            if capability.structural_index
        }
        missing_languages = sorted(expected_languages - set(language_file_counts))
        if missing_languages:
            raise RuntimeError(
                "registered parser languages missing from binary: "
                + ", ".join(missing_languages)
            )
        return {
            "status": receipt.status.value,
            "graph_revision": receipt.graph_revision,
            "binary_sha256": receipt.binary_sha256,
            "elapsed_ms": receipt.elapsed_ms,
            "schema_valid": receipt.schema_valid,
            "source_files": receipt.source_files,
            "indexable_files": receipt.indexable_files,
            "node_count": receipt.node_count,
            "edge_count": receipt.edge_count,
            "fts_tables": list(receipt.fts_tables),
            "definition_count": definition_count,
            "call_count": call_count,
            "language_counts": language_counts,
            "language_file_counts": language_file_counts,
            "source_revision": source_revision,
            "frontier_anchors": len(evidence.anchors),
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
