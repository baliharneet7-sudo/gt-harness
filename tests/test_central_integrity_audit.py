"""Tests for the provider-free benchmark-integrity audit boundary.

The audit proves GT reads only the three legal evidence sources (task
instruction, workspace repository source, observed execution results) and never
grader-only artifacts.  These tests exercise the static source boundary and the
per-receipt evidence-provenance checks without invoking a provider.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.central_integrity_audit import (
    GRADER_ONLY_MARKERS,
    audit_run_root,
)
from scripts.central_trajectory_audit import LEGAL_EVIDENCE_ORIGINS


def test_direct_integrity_audit_invocation_bootstraps_project_imports():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "central_integrity_audit.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "benchmark-integrity audit" in result.stdout


def test_grader_markers_are_specific_to_hidden_artifacts():
    # The marker set must be specific to grader-only artifacts, not generic
    # repository paths (a repo's own tests/ directory is a legal source).
    assert "test_outputs.py" in GRADER_ONLY_MARKERS
    assert "reward.txt" in GRADER_ONLY_MARKERS
    assert "ctrf.json" in GRADER_ONLY_MARKERS
    assert "/solution/" in GRADER_ONLY_MARKERS


def test_legal_evidence_origins_are_closed_over_the_three_sources():
    # Legal origins map to instruction / checkout source / observed execution.
    assert {"task_start", "preexisting_repository", "observed_external"} <= LEGAL_EVIDENCE_ORIGINS
    # No grader-derived origin may be legal.
    assert "grader" not in LEGAL_EVIDENCE_ORIGINS
    assert "reference_solution" not in LEGAL_EVIDENCE_ORIGINS


def test_static_source_boundary_passes_on_clean_runtime():
    report = audit_run_root(Path("."))
    assert report["static"]["source_boundary_proven"] is True
    assert report["static"]["violations"] == []
    assert report["static"]["checked_files"], "static audit scanned no runtime files"


def _write_bundle(root: Path, *, facts_path: str = "app.py", origin: str | None = None) -> Path:
    task = root / "trial-task-demo" / "agent"
    task.mkdir(parents=True)
    trajectory = {
        "info": {"exit_status": "Submitted"},
        "messages": [
            {"role": "user", "content": "Fix it."},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "inspect",
                "extra": {"actions": [{"command": "cat app.py", "tool_call_id": "call-1"}]},
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "ok",
                "extra": {"returncode": 0, "raw_output": "print(1)"},
            },
        ],
    }
    (task / "miniswe_trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    request_hash = "h"
    guidance = {
        "feature_id": "GT_LOC_RESLOT",
        "evidence_action": 1,
        "first_eligible_call": 1,
        "delivered_before_call": 1,
        "delivered_before_model_query": True,
        "one_step_late": False,
        "not_predictive": True,
        "request_payload_sha256": request_hash,
        "provider_messages_sha256": request_hash,
        "message_index": 2,
        "facts": [{"path": facts_path, "line": 1, "symbol": "x"}],
        "chars": 20,
    }
    if origin is not None:
        guidance["claim_metadata"] = [{"claim_id": "c1", "origin": origin}]
    receipt = {
        "actions": 1,
        "model_call_contexts": [
            {
                "call": 1,
                "request_payload_sha256": request_hash,
                "provider_messages_sha256": request_hash,
                "provider_message_count": 3,
                "provider_changed_message_indices": [2],
                "dispatch_status": "response_received",
                "context_fact_candidates": 1,
                "context_facts_accounted": 1,
            }
        ],
        "features": {"effect_trace": []},
        "guidance_deliveries": [guidance],
    }
    (task / "central_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return task / "central_receipt.json"


def test_receipt_audit_certifies_clean_delivery(tmp_path):
    _write_bundle(tmp_path, facts_path="app.py")
    report = audit_run_root(tmp_path)
    assert report["audit_status"] == "INTEGRITY_CERTIFIED"
    assert report["failures"] == []


def test_receipt_audit_fails_closed_on_grader_fact_path(tmp_path):
    _write_bundle(tmp_path, facts_path="/tests/test_outputs.py")
    report = audit_run_root(tmp_path)
    assert report["audit_status"] == "INTEGRITY_FAILED"
    assert any("delivery_grader_fact_path" in item for item in report["failures"])


def test_receipt_audit_fails_closed_on_illegal_evidence_origin(tmp_path):
    _write_bundle(tmp_path, facts_path="app.py", origin="reference_solution")
    report = audit_run_root(tmp_path)
    assert report["audit_status"] == "INTEGRITY_FAILED"
    assert any("illegal_evidence_origin" in item for item in report["failures"])
