"""DeepSeek Mini-SWE baseline and GT feature-audit primitives.

This module is deliberately independent of the nano bridge.  It validates the
frozen 83/300 DeepSeek GT-off population and audits provider-bound GT rows
without treating transcript text as attribution evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASELINE_RESOLVED_FLOOR = 83
BASELINE_TOTAL_TASKS = 300
FEATURE_IDS = (
    "obligations",
    "localization",
    "caller_contract",
    "def_partition",
    "newfile_precedent",
    "signature_delta",
    "syntax_result",
    "covering_red",
    "recovery",
    "submit_refusal",
    "GT_LOC_RESLOT",
    "GT_EDIT_CHECK",
    "GT_CERT_DELIVERY",
    "GT_CHANGE_SURFACE",
    "GT_PATCH_DELTA",
    "GT_HYPOTHESIS",
    "GT_SS_SUBMIT_RED",
)
_DEEPSEEK_RE = re.compile(r"deepseek-v4-flash", re.IGNORECASE)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Baseline:
    root: Path
    model: str
    resolved_floor: int
    total_tasks: int
    results: Mapping[str, str]


@dataclass(frozen=True)
class AttributionAudit:
    ok: bool
    issues: tuple[str, ...]
    by_feature: Mapping[str, Mapping[str, Any]]


def load_baseline(root: str | Path) -> Baseline:
    """Load and validate the frozen DeepSeek 83/300 baseline metadata."""
    root = Path(root)
    summary_path = root / "SUMMARY.md"
    results_path = root / "results_300.json"
    if not summary_path.is_file() or not results_path.is_file():
        raise ValueError("baseline requires SUMMARY.md and results_300.json")
    summary = summary_path.read_text(encoding="utf-8", errors="replace")
    if not _DEEPSEEK_RE.search(summary):
        raise ValueError("baseline must be the DeepSeek V4 Flash GT-off baseline")
    match = re.search(r"Real baseline.*?(\d+)\s*/\s*(\d+)", summary, re.I | re.S)
    if not match:
        raise ValueError("baseline summary does not declare a resolved floor")
    resolved, total = int(match.group(1)), int(match.group(2))
    if resolved != BASELINE_RESOLVED_FLOOR or total != BASELINE_TOTAL_TASKS:
        raise ValueError(
            f"expected frozen floor {BASELINE_RESOLVED_FLOOR}/{BASELINE_TOTAL_TASKS}, "
            f"got {resolved}/{total}"
        )
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(results, dict):
        raise ValueError("results_300.json must contain an object")
    return Baseline(root, "deepseek-v4-flash", resolved, total, results)


def select_tasks(results: Mapping[str, Any], task_ids: Iterable[str]) -> list[str]:
    """Validate the immutable ten-task smoke selection and return sorted IDs."""
    selected = list(task_ids)
    if len(selected) != 10 or len(set(selected)) != 10:
        raise ValueError("smoke selection must contain exactly 10 unique tasks")
    unknown = sorted(set(selected) - set(results))
    if unknown:
        raise ValueError(f"unknown baseline task(s): {', '.join(unknown)}")
    return sorted(selected)


def validate_tb2_smoke(
    manifest: Mapping[str, Any], baseline_results: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the separate Terminal-Bench ten-task DeepSeek comparator."""
    tasks = list(manifest.get("tasks") or ())
    if len(tasks) != 10 or len(set(tasks)) != 10:
        raise ValueError("TB2 smoke manifest must contain exactly 10 unique tasks")
    if manifest.get("model") != "deepseek-v4-flash":
        raise ValueError("TB2 smoke must use deepseek-v4-flash")
    if float(manifest.get("temperature", -1)) != 1.0:
        raise ValueError("TB2 smoke temperature must be 1.0")
    if float(manifest.get("timeout_multiplier", -1)) != 1.0:
        raise ValueError("TB2 smoke timeout multiplier must be 1.0")
    missing = sorted(set(tasks) - set(baseline_results))
    if missing:
        raise ValueError(f"TB2 baseline missing tasks: {', '.join(missing)}")
    ungraded = sorted(task for task in tasks if baseline_results[task] in {None, "not_graded"})
    return {"task_count": len(tasks), "tasks": sorted(tasks), "ungraded": ungraded}


def _required(row: Mapping[str, Any], key: str, index: int) -> Any:
    value = row.get(key)
    if value in (None, ""):
        raise ValueError(f"row {index}: missing {key}")
    return value


def audit_attribution(rows: Iterable[Mapping[str, Any]]) -> AttributionAudit:
    """Audit structural provider/action/receipt joins for all 17 identities."""
    rows = list(rows)
    issues: list[str] = []
    by_feature: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        try:
            feature = str(_required(row, "feature_id", index))
            if feature not in FEATURE_IDS:
                issues.append(f"row {index}: unknown feature {feature}")
                continue
            if feature in by_feature:
                issues.append(f"duplicate feature {feature}")
                continue
            status = str(_required(row, "status", index))
            if status not in {
                "confirmed",
                "not_consumed",
                "inconsistent",
                "absent",
                "ineligible",
                "blocked",
                "forbidden_execution",
            }:
                issues.append(f"row {index}: invalid status {status}")
            trigger = int(_required(row, "trigger_iteration", index))
            delivery = int(_required(row, "delivery_iteration", index))
            if delivery < trigger:
                issues.append(f"row {index}: delivery before trigger")
            payload_hash = str(_required(row, "payload_sha256", index))
            if not _HASH_RE.fullmatch(payload_hash):
                issues.append(f"row {index}: invalid payload hash")
            for key in ("provider_request_id", "action_id", "receipt_id"):
                _required(row, key, index)
            by_feature[feature] = dict(row)
        except (TypeError, ValueError) as exc:
            issues.append(str(exc))
    missing = sorted(set(FEATURE_IDS) - set(by_feature))
    issues.extend(f"missing feature {feature}" for feature in missing)
    return AttributionAudit(not issues, tuple(issues), by_feature)


def payload_sha256(payload: bytes | str) -> str:
    """Hash the exact normalized provider payload for an attribution receipt."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
