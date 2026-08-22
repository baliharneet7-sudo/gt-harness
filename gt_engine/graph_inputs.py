"""Canonical policy for files that can change repository graph semantics."""

from __future__ import annotations

from pathlib import PurePosixPath

from gt_engine.language_registry import is_indexable_source

GRAPH_METADATA_NAMES = frozenset(
    {
        "build.gradle",
        "build.gradle.kts",
        "cargo.lock",
        "cargo.toml",
        "cmakelists.txt",
        "composer.json",
        "composer.lock",
        "configure.ac",
        "gemfile",
        "gemfile.lock",
        "go.mod",
        "go.sum",
        "go.work",
        "go.work.sum",
        "gradle.properties",
        "makefile",
        "meson.build",
        "mix.exs",
        "mix.lock",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pom.xml",
        "pyproject.toml",
        "pytest.ini",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
        "settings.gradle",
        "settings.gradle.kts",
        "tox.ini",
        "tsconfig.json",
        "yarn.lock",
    }
)


def is_graph_metadata(path: str) -> bool:
    """Return whether a file can alter parsing, imports, or validation discovery."""

    name = PurePosixPath(str(path or "").replace("\\", "/")).name.lower()
    return name in GRAPH_METADATA_NAMES or (
        name.startswith("requirements-") and name.endswith(".txt")
    )


def is_graph_input(path: str, content: str | bytes | None = None) -> bool:
    """Return whether a file participates in graph identity."""

    return is_graph_metadata(path) or is_indexable_source(path, content)


__all__ = ["GRAPH_METADATA_NAMES", "is_graph_input", "is_graph_metadata"]
