from __future__ import annotations

from scripts.central_readiness_audit import audit


def test_readiness_rejects_an_incomplete_groundtruth_runtime_surface():
    result = audit()

    assert result["vendored_groundtruth_runtime_surface"] is True
