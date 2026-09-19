"""FS-023 workflow blob: the two tracked copies must stay one blob.

`.github/workflows/gt_finalstand_provider_free.yml` was retired into TWO
places at once:

  * `docs/historical-workflows/gt_finalstand_provider_free.yml` - pinned
    `text eol=lf`, and the copy whose LF bytes the FS-023 receipt's
    `workflow_definition_sha256` (f82ab72c...) binds;
  * `.github/workflows-archive/gt_finalstand_provider_free.yml` - the
    archive copy, NOT eol-pinned, so an autocrlf checkout hands it CRLF.

Two tracked copies of one hashed identity drift silently: edit the archive
copy and the receipt still verifies against the docs copy, so the provenance
record would attest a workflow definition nobody runs and nobody reads. These
tests are the only thing tying the two together, and they compare CONTENT
(CRLF normalised) rather than on-disk bytes, because only the docs copy is
eol-pinned.

Read-only: nothing here writes, and `gt_finalstand/receipts/fs023_provenance.json`
is opened for reading alone.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_COPY = _REPO_ROOT / "docs" / "historical-workflows" / "gt_finalstand_provider_free.yml"
_ARCHIVE_COPY = (
    _REPO_ROOT / ".github" / "workflows-archive" / "gt_finalstand_provider_free.yml"
)
_RECEIPT = _REPO_ROOT / "gt_finalstand" / "receipts" / "fs023_provenance.json"


def _lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"FS-023 artefact absent from this checkout: {path}")
    return path


def test_docs_and_archive_copies_are_one_blob():
    """Both tracked copies carry byte-identical content once CRLF is normalised."""
    docs = _lf_bytes(_require(_DOCS_COPY))
    archive = _lf_bytes(_require(_ARCHIVE_COPY))
    assert docs == archive, (
        "docs/historical-workflows and .github/workflows-archive hold DIFFERENT "
        "copies of gt_finalstand_provider_free.yml; the FS-023 receipt binds only "
        "the docs copy, so the archive copy is an unattested fork "
        f"(docs sha256={hashlib.sha256(docs).hexdigest()}, "
        f"archive sha256={hashlib.sha256(archive).hexdigest()})"
    )


def test_docs_copy_lf_digest_matches_fs023_receipt():
    """The docs copy's LF digest IS `workflow_definition_sha256` in the receipt."""
    docs = _lf_bytes(_require(_DOCS_COPY))
    receipt = json.loads(_require(_RECEIPT).read_text(encoding="utf-8"))
    assert receipt["schema"] == "gt.fs023.provenance.v1"
    assert hashlib.sha256(docs).hexdigest() == receipt["workflow_definition_sha256"]


def test_docs_copy_is_checked_out_with_lf_endings():
    """`docs/historical-workflows/.gitattributes` pins eol=lf; the checkout must obey.

    `scripts/finalstand_offline.py` hashes the workflow file RAW, so a CRLF
    checkout of the docs copy produces a digest that does not match the pinned
    f82ab72c... - the eol pin is load-bearing, not cosmetic.
    """
    assert b"\r\n" not in _require(_DOCS_COPY).read_bytes()
