from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from gt_engine.indexer import IndexBuildStatus
from gt_engine.language_registry import LANGUAGE_CAPABILITIES
from gt_engine.repository_intelligence import (
    RepositorySession,
    discover_project_checks,
    graph_gate_failures,
    inspect_index,
    inspect_repository,
)
from scripts.verify_gt_index_runtime import verify as verify_gt_index_runtime


def test_project_checks_are_repository_backed_not_guessed(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "go.mod").write_text("module example.test/demo\n")

    assert discover_project_checks(tmp_path) == ("pytest -q", "go test ./...")


def test_shipped_index_fixture_covers_every_registered_parser_language():
    result = verify_gt_index_runtime()
    expected = {
        "bash" if capability.name == "shell" else capability.name
        for capability in LANGUAGE_CAPABILITIES
        if capability.structural_index
    }

    assert expected <= set(result["language_file_counts"])


def test_repository_intelligence_returns_task_linked_source_anchor(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    source = tmp_path / "src"
    source.mkdir()
    (source / "greeter.py").write_text("def greet(name: str) -> str:\n    return f'hello {name}'\n")

    evidence = inspect_repository(
        tmp_path,
        "Change greet so it returns an uppercase greeting.",
        state_dir=tmp_path / ".state",
    )

    assert evidence.available is True
    assert evidence.graph_revision
    assert any(item["path"].endswith("greeter.py") for item in evidence.anchors)
    assert evidence.definitions
    assert evidence.references == ()
    assert evidence.callers == ()
    assert evidence.project_checks == ("pytest -q",)
    assert evidence.index is not None
    assert evidence.index.schema_valid is True
    assert evidence.index.node_count > 0
    assert "nodes_fts" in evidence.index.fts_tables


def test_non_code_repository_has_explicit_index_abstention(tmp_path: Path):
    (tmp_path / "README.md").write_text("documentation only")

    receipt = inspect_index(tmp_path, state_dir=tmp_path / ".state")

    assert receipt.status is IndexBuildStatus.NO_SUPPORTED_SOURCE
    assert receipt.graph_db is None
    assert receipt.error_type is None


def test_repository_intelligence_abstains_for_non_code_repository(tmp_path: Path):
    (tmp_path / "README.md").write_text("documentation only")

    evidence = inspect_repository(tmp_path, "Update the documentation")

    assert evidence.available is False
    assert evidence.anchors == ()


def test_repository_session_persists_and_refreshes_captured_source(tmp_path: Path):
    mirror = tmp_path / "mirror"
    state = tmp_path / "state"
    (mirror / "src").mkdir(parents=True)
    (mirror / "src" / "greeter.py").write_text("def greet():\n    return 'hi'\n")
    session = RepositorySession(
        root=mirror,
        state_dir=state,
        instruction="Change greet to return uppercase text.",
    )

    first = session.refresh(source_revision="s1")
    assert first.available is True
    first_graph_revision = first.graph_revision
    transition = SimpleNamespace(
        changed_paths=("src/greeter.py",),
        deleted=(),
        after_contents={"src/greeter.py": "def greet():\n    return 'HI'\n"},
        sensor_healthy=True,
    )
    assert session.apply_transition(transition, source_revision="s2") is True
    second = session.refresh(source_revision="s2")

    assert second.available is True
    assert second.graph_revision != first_graph_revision
    assert session.source_revision == "s2"
    assert "'HI'" in (mirror / "src" / "greeter.py").read_text()
    assert [row["source_revision"] for row in session.refresh_log] == ["s1", "s2"]
    assert [row["mode"] for row in session.refresh_log] == ["full", "incremental"]
    assert second.index is not None and second.index.graph_db
    assert second.index.source_revision == "s2"
    assert graph_gate_failures(second) == ()
    manifest = json.loads(Path(second.index.graph_db).with_suffix(".manifest.json").read_text())
    assert manifest["refresh_mode"] == "incremental"
    assert manifest["changed_paths"] == ["src/greeter.py"]
    assert manifest["source_revision"] == "s2"

    cached = session.refresh(source_revision="s2")
    assert cached.graph_revision == second.graph_revision
    assert session.refresh_log[-1]["mode"] == "revision_cache_hit"
    assert session.refresh_log[-1]["elapsed_ms"] == 0.0


def test_repository_session_invalidates_when_changed_source_was_not_captured(tmp_path: Path):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "app.py").write_text("x = 1\n")
    session = RepositorySession(
        root=mirror,
        state_dir=tmp_path / "state",
        instruction="Change x.",
    )
    session.refresh(source_revision="s1")
    transition = SimpleNamespace(
        changed_paths=("app.py",),
        deleted=(),
        after_contents={},
        sensor_healthy=True,
    )

    assert session.apply_transition(transition, source_revision="s2") is False
    assert session.fresh is False
    assert session.evidence.available is False
    assert session.evidence.status == "mirror_incomplete"


def test_current_graph_with_empty_retrieval_is_healthy_substrate(tmp_path: Path):
    (tmp_path / "decomp.c").write_text(
        "int decode(void) { return 0; }\n",
        encoding="utf-8",
    )

    evidence = inspect_repository(
        tmp_path,
        "Create data.comp containing the requested artifact.",
        state_dir=tmp_path / ".state",
        source_revision="s1",
    )
    session = RepositorySession(
        root=tmp_path,
        state_dir=tmp_path / ".session-state",
        instruction="Create data.comp containing the requested artifact.",
    )
    refreshed = session.refresh(source_revision="s1")

    assert evidence.index is not None and evidence.index.schema_valid is True
    assert evidence.index.node_count > 0
    assert evidence.retrieval_disposition == "empty"
    assert evidence.substrate_ready is True
    assert graph_gate_failures(evidence) == ()
    assert refreshed.substrate_ready is True
    assert refreshed.index_current is True
    assert graph_gate_failures(refreshed) == ()
