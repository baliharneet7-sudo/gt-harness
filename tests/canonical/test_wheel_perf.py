"""The processes hot-path shim is output-identical to the certified wheel."""
from __future__ import annotations

import sqlite3

from gt_engine import wheel_perf


def test_shim_equals_the_wheel_on_a_real_producer_graph(polyglot_repo):
    wheel_perf.uninstall()
    original = wheel_perf.original()
    assert original is not None
    connection = sqlite3.connect(str(polyglot_repo.graph))
    try:
        expected = original(connection)
        actual = wheel_perf.fast_stable_id_to_nodes(connection)
    finally:
        connection.close()
    assert expected, "fixture graph produced no stable ids"
    assert actual == expected


def test_install_is_idempotent_and_reversible():
    from groundtruth.runtime import processes

    wheel_perf.uninstall()
    before = processes._stable_id_to_nodes
    assert wheel_perf.install() and wheel_perf.install()
    assert processes._stable_id_to_nodes is wheel_perf.fast_stable_id_to_nodes
    wheel_perf.uninstall()
    assert processes._stable_id_to_nodes is before


def test_memoized_process_detection_equals_the_wheel(polyglot_repo):
    from groundtruth.runtime import deterministic_queries, processes

    wheel_perf.uninstall()
    expected = processes.detect_processes(str(polyglot_repo.graph))
    assert wheel_perf.install()
    try:
        assert deterministic_queries.detect_processes is wheel_perf.memo_detect_processes
        first = processes.detect_processes(str(polyglot_repo.graph))
        second = processes.detect_processes(str(polyglot_repo.graph))
        assert first is second
        assert first == expected
    finally:
        wheel_perf.uninstall()
    assert processes.detect_processes is not wheel_perf.memo_detect_processes
