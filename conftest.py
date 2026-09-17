"""Refuse to collect a suite running against the wrong producer.

Every local result today has been a statement about whichever ``groundtruth``
the interpreter happened to resolve, and this interpreter resolved an editable
checkout at a revision the benchmark never installs. The visible half of that is
a set of suites that fail here and pass in CI. The invisible half is worse:
tests that pass locally against the checkout and would fail against the pinned
wheel, and the reverse. Neither half is interpretable, so neither is evidence.

This is the same defect class the ticket spent a day removing - a vendored
source tree that was not the source of the pinned binary, a readiness receipt
from one commit presented for a run on another. Each was fixed by binding the
artifact to its declaration and refusing on mismatch. The interpreter gets the
same treatment rather than a note in a docstring saying it is known to be wrong.

The chain is derived end to end, with nothing hand-written on either side:

    config/deepswe_product_bundle_v1.json  groundtruth.wheel_sha256
      -> the wheel file's own bytes                     (sha256 equality)
      -> the RECORD inside that wheel                   (zip member)
      -> the RECORD of the installed distribution       (dist-info)

The last comparison is what actually decides. RECORD lists every installed file
with its digest, so equality means the installed distribution is byte-for-byte
the wheel the benchmark installs. An editable install cannot pass it: its RECORD
carries a ``.pth`` and a finder module and none of the package files, so the
mismatch names itself.

pip's ``direct_url.json`` is deliberately not used. It records what pip was
asked to install, which is a declaration; RECORD records what landed, which is
the fact. Preferring the declaration over the artifact is exactly how
``vendor/gt-index-src`` produced two confidently wrong conclusions.

An interpreter with no ``groundtruth`` at all passes without comment, and that
is deliberate rather than a gap. The hazard here is a producer that is PRESENT
AND WRONG, because that one answers, and its answers are indistinguishable from
the right producer's until something downstream disagrees. An absent producer is
not silent: anything needing it fails to import, loudly, at the line that needs
it. Refusing on absence would also block suites in this root that never touch
the producer and are correct without it, which is how a gate earns a bypass.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata as _metadata
import json
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent
_BUNDLE = _ROOT / "config" / "deepswe_product_bundle_v1.json"
_DISTRIBUTION = "groundtruth-mcp"


def _record_digests(text: str) -> dict[str, str]:
    """RECORD as {installed path: digest}, minus its own unhashable entry."""
    digests: dict[str, str] = {}
    for row in csv.reader(text.splitlines()):
        if not row:
            continue
        path, digest = row[0], (row[1] if len(row) > 1 else "")
        if path.endswith("/RECORD") or not digest:
            continue
        digests[path.replace("\\", "/")] = digest
    return digests


def _refuse(reason: str) -> None:
    raise pytest.UsageError(
        f"producer identity gate refused: {reason}\n"
        f"  the suite would measure a producer the benchmark never installs.\n"
        f"  install the pinned wheel into this interpreter:\n"
        f"    python -m pip install --force-reinstall "
        f"{_BUNDLE.parent.parent / 'vendor'}/groundtruth_mcp-1.0.0-py3-none-any.whl"
    )


def pytest_configure(config: pytest.Config) -> None:
    try:
        installed = _metadata.distribution(_DISTRIBUTION)
    except _metadata.PackageNotFoundError:
        return

    bundle = json.loads(_BUNDLE.read_text(encoding="utf-8"))["groundtruth"]
    wheel = _ROOT / bundle["wheel_path"]
    if not wheel.is_file():
        _refuse(f"the pinned wheel is missing at {bundle['wheel_path']}")

    actual_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if actual_sha != bundle["wheel_sha256"]:
        _refuse(
            f"the vendored wheel is not the declared one\n"
            f"  declared {bundle['wheel_sha256']}\n"
            f"  actual   {actual_sha}"
        )

    with zipfile.ZipFile(wheel) as archive:
        record_member = next(
            (name for name in archive.namelist() if name.endswith(".dist-info/RECORD")),
            None,
        )
        if record_member is None:
            _refuse("the pinned wheel carries no dist-info/RECORD")
        expected = _record_digests(archive.read(record_member).decode("utf-8"))

    installed_record = installed.read_text("RECORD")
    if installed_record is None:
        _refuse(f"the installed {_DISTRIBUTION} carries no RECORD")
    found = _record_digests(installed_record)

    missing = sorted(set(expected) - set(found))
    differing = sorted(name for name in set(expected) & set(found) if expected[name] != found[name])
    if missing or differing:
        detail = []
        if missing:
            detail.append(f"{len(missing)} file(s) absent, first {missing[0]}")
        if differing:
            detail.append(f"{len(differing)} file(s) differ, first {differing[0]}")
        _refuse(
            f"the installed {_DISTRIBUTION} is not the pinned wheel: " + "; ".join(detail)
        )
