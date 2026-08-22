from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_does_not_depend_on_opaque_groundtruth_artifacts() -> None:
    """The official product must be buildable from the checked-in source tree."""

    assert (ROOT / "src" / "groundtruth" / "__init__.py").is_file()
    assert (ROOT / "vendor" / "gt-index-src" / "go.mod").is_file()
    assert not list((ROOT / "vendor").glob("groundtruth_mcp-*.whl"))
    assert not (ROOT / "vendor" / "gt-index-linux-amd64").exists()


def test_groundtruth_source_provenance_is_content_addressed() -> None:
    provenance = tomllib.loads(
        (ROOT / "vendor" / "GROUNDTRUTH_SOURCE.toml").read_text(encoding="utf-8")
    )
    assert provenance["source_repository"] == "https://github.com/harneet2512/groundtruth"
    assert provenance["source_commit"] == "61cfdbce2c42751c11028e46e863b3231f0bb70e"

    digest = hashlib.sha256()
    source_paths = [
        path
        for path in sorted((ROOT / "src" / "groundtruth").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    assert len(source_paths) == provenance["source_files"]
    for path in source_paths:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    assert digest.hexdigest() == provenance["source_tree_sha256"]


def test_gt_index_source_provenance_is_content_addressed() -> None:
    provenance = tomllib.loads(
        (ROOT / "vendor" / "GT_INDEX_SOURCE.toml").read_text(encoding="utf-8")
    )
    assert provenance["source_repository"] == "https://github.com/harneet2512/groundtruth"
    assert provenance["upstream_source_commit"] == ("61cfdbce2c42751c11028e46e863b3231f0bb70e")

    digest = hashlib.sha256()
    source_paths = [
        path
        for path in sorted((ROOT / "vendor" / "gt-index-src").rglob("*"))
        if path.is_file() and path.name not in {"gt-index", "gt-index.exe"}
    ]
    assert len(source_paths) == provenance["source_files"]
    for path in source_paths:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    assert digest.hexdigest() == provenance["source_tree_sha256"]


def test_official_package_and_cli_have_groundtruth_identity() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "gt-harness"
    assert config["project"]["scripts"]["gt-harness"] == "gt_harness.cli:main"
    assert "src/groundtruth" in config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
