"""gt-index runs at the lowest CPU priority (gt_engine.indexer._low_priority).

DeepSWE campaign 2026-09-29, same model and same days for both arms: the
agent's own commands took p90 22.6 s per step with GT against 8.6 s without,
while a background graph refresh ran up to 58 minutes per task
(dynamodb-toolbox-lazy-recursive-schemas). The rebuild competed with the
agent's builds and tests for CPU; at nice 19 the agent's work goes first.
"""
from __future__ import annotations

from gt_engine import indexer

ARGV = ["/opt/gt/gt-index", "-root", "/app", "-output", "/tmp/g.db"]


def test_index_command_is_wrapped_in_nice_on_posix(monkeypatch):
    monkeypatch.setattr(indexer.os, "name", "posix")
    monkeypatch.setattr(indexer.shutil, "which", lambda name: "/usr/bin/nice" if name == "nice" else None)
    monkeypatch.delenv(indexer.INDEX_NICE_ENV, raising=False)

    assert indexer._low_priority(ARGV) == ["/usr/bin/nice", "-n", "19", *ARGV]


def test_no_wrapper_when_nice_is_missing(monkeypatch):
    monkeypatch.setattr(indexer.os, "name", "posix")
    monkeypatch.setattr(indexer.shutil, "which", lambda _name: None)

    assert indexer._low_priority(ARGV) == ARGV


def test_no_wrapper_on_windows(monkeypatch):
    monkeypatch.setattr(indexer.os, "name", "nt")
    monkeypatch.setattr(indexer.shutil, "which", lambda _name: "C:/nice.exe")

    assert indexer._low_priority(ARGV) == ARGV


def test_env_switch_turns_the_wrapper_off(monkeypatch):
    monkeypatch.setattr(indexer.os, "name", "posix")
    monkeypatch.setattr(indexer.shutil, "which", lambda _name: "/usr/bin/nice")
    monkeypatch.setenv(indexer.INDEX_NICE_ENV, "0")

    assert indexer._low_priority(ARGV) == ARGV
