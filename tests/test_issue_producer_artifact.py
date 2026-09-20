"""The producer receipt must describe the binary it was handed.

The issuer used to hardcode `graph_schema_version` and the capability list.
That is a receipt asserting a fact it never read: after the producer moved to
`v15.4-callsite-actuals` the issuer would still have stamped
`v15.2-trust-tier` on it, and a receipt that lies about the artifact is worse
than no receipt.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import issue_producer_artifact as issuer


def _source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "go.mod").write_text("module example\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=src, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.x", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=src, check=True, capture_output=True,
    )
    return src


def _binary(tmp_path: Path, sidecar: dict[str, object] | None) -> Path:
    binary = tmp_path / "gt-index-linux-amd64"
    binary.write_bytes(b"ELF-ish bytes")
    if sidecar is not None:
        binary.with_suffix(binary.suffix + ".build-info.json").write_text(
            json.dumps(sidecar), encoding="utf-8"
        )
    return binary


SIDECAR = {
    "schema": "gt-index.build.v1",
    "graph_schema_version": "v15.4-callsite-actuals",
    "capabilities": ["cfg_uses", "callsite_actuals"],
}


def test_receipt_takes_the_schema_version_from_the_binarys_build_info(tmp_path: Path) -> None:
    receipt = issuer.issue(
        source=_source(tmp_path), binary=_binary(tmp_path, SIDECAR),
        output=tmp_path / "receipt.json", goos="linux", goarch="amd64",
        cgo=True, tags="netgo,osusergo,sqlite_fts5", toolchain="go1.22.5",
    )
    assert receipt["graph_schema_version"] == "v15.4-callsite-actuals"
    assert receipt["capabilities"] == ["cfg_uses", "callsite_actuals"]


def test_a_binary_with_no_build_info_is_refused(tmp_path: Path) -> None:
    with pytest.raises(issuer.ProducerArtifactError) as raised:
        issuer.issue(
            source=_source(tmp_path), binary=_binary(tmp_path, None),
            output=tmp_path / "receipt.json", goos="linux", goarch="amd64",
            cgo=True, tags="netgo,osusergo,sqlite_fts5", toolchain="go1.22.5",
        )
    assert "build-info" in str(raised.value)


def test_a_build_info_missing_the_schema_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(issuer.ProducerArtifactError):
        issuer.issue(
            source=_source(tmp_path),
            binary=_binary(tmp_path, {"schema": "gt-index.build.v1"}),
            output=tmp_path / "receipt.json", goos="linux", goarch="amd64",
            cgo=True, tags="netgo,osusergo,sqlite_fts5", toolchain="go1.22.5",
        )
