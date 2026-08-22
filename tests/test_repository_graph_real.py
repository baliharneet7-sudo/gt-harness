from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from gt_engine.repository_graph_service import GraphStatus, RepositoryGraphService


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.mark.real_graph
def test_real_index_build_query_stale_and_rebuild(tmp_path: Path) -> None:
    binary = Path(os.environ.get("GT_INDEX_BINARY", ""))
    if not binary.is_file():
        pytest.skip("run the source-built gt-index and set GT_INDEX_BINARY")

    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "gt@example.invalid")
    _git(root, "config", "user.name", "GT Test")
    (root / "core.py").write_text(
        "def target(value: int) -> int:\n    return value + 1\n", encoding="utf-8"
    )
    (root / "caller.py").write_text(
        "from core import target\n\ndef invoke() -> int:\n    return target(4)\n",
        encoding="utf-8",
    )
    (root / "test_core.py").write_text(
        "from caller import invoke\n\ndef test_invoke():\n    assert invoke() == 5\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")

    service = RepositoryGraphService(root)
    first = service.build(force=True, timeout=180)
    assert first.build_status in {
        GraphStatus.READY,
        GraphStatus.READY_WITH_DECLARED_LIMITATIONS,
    }, first.as_dict()
    assert first.query_ready
    assert first.files_attempted == 3
    assert first.files_indexed == 3
    assert first.coverage == 1.0
    assert not any(row["path"].startswith(".groundtruth/") for row in first.excluded_directories)
    definitions = service.query("definition", "target")
    assert any(row["file_path"] == "core.py" for row in definitions["evidence"])
    callers = service.query("callers", "target")
    assert any(row["name"] == "invoke" for row in callers["evidence"])
    restarted = RepositoryGraphService(root)
    warm = restarted.status()
    assert warm.query_ready
    assert warm.graph_checksum_or_identity == first.graph_checksum_or_identity
    assert restarted.query("definition", "target")["evidence"] == definitions["evidence"]

    (root / "caller.py").write_text("def invoke() -> int:\n    return 5\n", encoding="utf-8")
    assert service.status().build_status is GraphStatus.STALE
    second = service.build(timeout=180)
    assert second.query_ready, second.as_dict()
    assert second.update_mode == "full_fallback_unproven_incremental_parity"
    assert not service.query("callers", "target")["evidence"]

    (root / "feature.py").write_text(
        "from core import target\n\ndef feature():\n    return target(8)\n",
        encoding="utf-8",
    )
    added = service.build(timeout=180)
    assert added.query_ready, added.as_dict()
    assert added.update_mode == "full_fallback_unproven_incremental_parity"
    assert any(
        row["file_path"] == "feature.py"
        for row in service.query("definition", "feature")["evidence"]
    )

    (root / "feature.py").unlink()
    deleted = service.build(timeout=180)
    assert deleted.query_ready, deleted.as_dict()
    assert deleted.update_mode == "full_fallback_unproven_incremental_parity"
    assert not service.query("definition", "feature")["evidence"]

    (root / "core.py").rename(root / "engine.py")
    renamed = service.build(timeout=180)
    assert renamed.query_ready, renamed.as_dict()
    assert renamed.update_mode == "full_fallback_unproven_incremental_parity"
    target_definitions = service.query("definition", "target")["evidence"]
    assert any(row["file_path"] == "engine.py" for row in target_definitions)
    assert not any(row["file_path"] == "core.py" for row in target_definitions)
