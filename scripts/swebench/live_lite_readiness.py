#!/usr/bin/env python3
"""Provider-free readiness gate for the canonical SWE-bench Live Lite route."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks" / "live_lite_300_ids.json"
FULL_WORKFLOW = ROOT / ".github" / "workflows" / "swebench_live_lite_full.yml"
DISPATCH_WORKFLOW = ROOT / ".github" / "workflows" / "swebench_live_lite_dispatch.yml"
GT_CONFIG = ROOT / "artifact_deepswe" / "gt_integration" / "deepswe_gt_pier.yaml"
BASELINE_CONFIG = (
    ROOT / "artifact_deepswe" / "gt_integration" / "deepswe_gt_pier_baseline.yaml"
)


def _agent_limit(path: Path, field: str) -> str:
    match = re.search(
        rf"^\s*{re.escape(field)}:\s*([0-9.]+)\s*(?:#.*)?$",
        path.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"missing_{field}:{path.relative_to(ROOT).as_posix()}")
    return match.group(1)


def audit() -> dict[str, object]:
    errors: list[str] = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    task_ids = manifest.get("instance_ids")
    if not isinstance(task_ids, list):
        errors.append("manifest_instance_ids_missing")
        task_ids = []
    if len(task_ids) != 300:
        errors.append(f"manifest_task_count:{len(task_ids)}")
    if len(set(task_ids)) != len(task_ids):
        errors.append("manifest_duplicate_task_ids")
    if manifest.get("selected_count") != len(task_ids):
        errors.append("manifest_selected_count_mismatch")
    if manifest.get("n_total_in_split") != 300:
        errors.append("manifest_split_count_mismatch")

    full = FULL_WORKFLOW.read_text(encoding="utf-8")
    dispatch = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    model_input = re.search(
        r"^\s{6}model:\s*\n(?P<body>(?:\s{8,}.*\n)+)", full, flags=re.MULTILINE
    )
    if model_input is None or "required: true" not in model_input.group("body"):
        errors.append("model_input_not_required")
    if model_input is not None and re.search(
        r"^\s*default:", model_input.group("body"), re.MULTILINE
    ):
        errors.append("model_input_has_default")
    forbidden = (
        "DEEPSEEK_API_KEY",
        "TOKENROUTER_API_KEY",
        "api.deepseek.com",
        "api.tokenrouter.com",
    )
    for marker in forbidden:
        if marker in full or marker in dispatch:
            errors.append(f"non_openrouter_route:{marker}")
    for marker in (
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "model: ${{ inputs.model }}",
    ):
        if marker not in full and marker not in dispatch:
            errors.append(f"openrouter_contract_missing:{marker}")
    for marker in (
        "image_owner: harneet2512",
        'require_pinned_substrate: "1"',
        "secrets: inherit",
    ):
        if marker not in dispatch:
            errors.append(f"dispatch_contract_missing:{marker}")

    limits: dict[str, dict[str, str]] = {}
    for name, path in (("treatment", GT_CONFIG), ("control", BASELINE_CONFIG)):
        try:
            limits[name] = {
                "step_limit": _agent_limit(path, "step_limit"),
                "cost_limit": _agent_limit(path, "cost_limit"),
            }
        except ValueError as exc:
            errors.append(str(exc))
    if limits.get("treatment") != limits.get("control"):
        errors.append("control_treatment_limit_mismatch")

    return {
        "schema": "gt.live_lite.provider_free_readiness.v1",
        "status": "READY" if not errors else "NOT_READY",
        "provider_calls": 0,
        "task_count": len(task_ids),
        "unique_task_count": len(set(task_ids)),
        "control_treatment_limits": limits,
        "errors": errors,
    }


def main() -> int:
    receipt = audit()
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
