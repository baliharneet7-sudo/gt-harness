from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.resolve_harbor_budget import (
    SUPERVISOR_GRACE_SECONDS,
    TASK_CONFIG_IDENTITY,
    canonical_task_config_bytes,
    resolve_budget,
)


def test_supervisor_reserve_covers_observed_container_startup_and_finalization() -> None:
    # Both ends measured on run 34305004976: 100s from step start to the journal
    # opening, and 68s from session close to step end. 168s observed. The
    # reserve must cover that with margin, and must not exceed it so far that it
    # hands back minutes of the benchmark's own budget -- seven tasks in run
    # 34312022821 hit our line rather than the benchmark's 5400.
    assert SUPERVISOR_GRACE_SECONDS >= 200
    assert SUPERVISOR_GRACE_SECONDS <= 300


def test_task_config_identity_is_checkout_line_ending_independent(
    tmp_path: Path,
) -> None:
    canonical = b'[agent]\ntimeout_sec = 300\n\n[metadata]\nlanguage = "go"\n'
    windows_checkout = canonical.replace(b"\n", b"\r\n")
    expected = hashlib.sha256(canonical).hexdigest()

    linux_path = tmp_path / "linux.toml"
    windows_path = tmp_path / "windows.toml"
    linux_path.write_bytes(canonical)
    windows_path.write_bytes(windows_checkout)

    linux = resolve_budget(linux_path, multiplier=1.0)
    windows = resolve_budget(windows_path, multiplier=1.0)
    assert linux["task_config_identity"] == TASK_CONFIG_IDENTITY
    assert windows["task_config_identity"] == TASK_CONFIG_IDENTITY
    assert linux["task_config_sha256"] == expected
    assert windows["task_config_sha256"] == expected


def test_task_config_identity_rejects_ambiguous_bare_carriage_return() -> None:
    with pytest.raises(ValueError, match="bare CR"):
        canonical_task_config_bytes(b"[agent]\rtimeout_sec = 300\n")
