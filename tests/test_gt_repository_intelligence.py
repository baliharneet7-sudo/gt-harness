from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gt_engine.indexer import IndexBuildStatus
from gt_engine.repository_intelligence import (
    RepositorySession,
    discover_project_checks,
    inspect_index,
    inspect_repository,
)


def test_project_checks_are_repository_backed_not_guessed(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "go.mod").write_text("module example.test/demo\n")

    assert discover_project_checks(tmp_path) == ("pytest -q", "go test ./...")


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
    transition = SimpleNamespace(
        changed_paths=("src/greeter.py",),
        deleted=(),
        after_contents={"src/greeter.py": "def greet():\n    return 'HI'\n"},
        sensor_healthy=True,
    )
    assert session.apply_transition(transition, source_revision="s2") is True
    second = session.refresh(source_revision="s2")

    assert second.available is True
    assert session.source_revision == "s2"
    assert "'HI'" in (mirror / "src" / "greeter.py").read_text()
    assert [row["source_revision"] for row in session.refresh_log] == ["s1", "s2"]


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
