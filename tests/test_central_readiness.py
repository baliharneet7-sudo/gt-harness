from __future__ import annotations

from scripts.central_readiness_audit import audit


def test_readiness_rejects_an_incomplete_groundtruth_runtime_surface():
    result = audit()

    assert result["vendored_groundtruth_runtime_surface"] is True


def test_paid_central_workflow_installs_and_proves_repository_runtime():
    result = audit()

    assert result["paid_central_installs_vendored_groundtruth"] is True
    assert result["paid_central_exports_index_binary"] is True
    assert result["paid_central_executes_index_fixture"] is True
    assert result["paid_central_executes_language_contract"] is True
    assert result["provider_free_gate_covers_pinned_benchmark_languages"] is True
