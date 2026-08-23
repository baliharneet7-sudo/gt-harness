#!/usr/bin/env python3
"""Fail closed unless a workflow and exact commit are release-authorized."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_CONTRACT_FIELDS = (
    "model",
    "base_url",
    "provider_secret",
    "temperature",
    "timeout_multiplier",
    "concurrency",
)


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    return [str(path).replace("\\", "/").lstrip("./") for path in paths]


def audit_release_workflow(
    manifest: dict,
    *,
    workflow: str,
    runtime_sha: str,
    runtime_is_descendant: bool | None = None,
    changed_paths: Iterable[str] = (),
    benchmark_inputs: dict[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    if manifest.get("schema") not in {"gt.release_manifest.v1", "gt.release_manifest.v2"}:
        failures.append("release_manifest_schema_invalid")
    if manifest.get("benchmark_authorized") is not True:
        failures.append("benchmark_not_authorized")
    allowed = {str(item) for item in manifest.get("authorized_workflows") or ()}
    if workflow not in allowed:
        failures.append("workflow_not_authorized")
    expected_sha = str(manifest.get("runtime_commit") or "")
    if re.fullmatch(r"[0-9a-f]{40}", runtime_sha) is None:
        failures.append("runtime_sha_invalid")
    elif runtime_sha != expected_sha:
        if runtime_is_descendant is None:
            failures.append("runtime_sha_not_active_release")
        elif runtime_is_descendant is not True:
            failures.append("runtime_sha_not_descendant_of_active_implementation")
        else:
            allowed = set(_normalize_paths(manifest.get("allowed_post_runtime_paths") or ()))
            changed = set(_normalize_paths(changed_paths))
            if not changed or not allowed or not changed <= allowed:
                failures.append("release_contains_unapproved_runtime_changes")

    contract = manifest.get("benchmark_contract")
    if contract is not None:
        if not isinstance(contract, dict):
            failures.append("benchmark_contract_invalid")
        elif benchmark_inputs is None:
            failures.append("benchmark_contract_inputs_missing")
        else:
            if str(contract.get("workflow") or "") != workflow:
                failures.append("benchmark_contract_workflow_mismatch")
            for field in _CONTRACT_FIELDS:
                if str(benchmark_inputs.get(field) or "") != str(contract.get(field) or ""):
                    failures.append(f"benchmark_contract_{field}_mismatch")
            expected_tasks = [str(item) for item in contract.get("task_ids") or ()]
            actual_tasks = [str(item) for item in benchmark_inputs.get("task_ids") or ()]
            if actual_tasks != expected_tasks:
                failures.append("benchmark_contract_task_ids_mismatch")
    return failures


def _git_release_delta(expected_sha: str, runtime_sha: str) -> tuple[bool, list[str]]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_sha, runtime_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        return False, []
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{expected_sha}..{runtime_sha}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return True, [line for line in diff.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="eval/release/active_release.json")
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--runtime-sha", required=True)
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--provider-secret")
    parser.add_argument("--task-ids")
    parser.add_argument("--temperature")
    parser.add_argument("--timeout-multiplier")
    parser.add_argument("--concurrency")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    expected_sha = str(manifest.get("runtime_commit") or "")
    is_descendant: bool | None = None
    changed_paths: list[str] = []
    if args.runtime_sha != expected_sha:
        is_descendant, changed_paths = _git_release_delta(expected_sha, args.runtime_sha)
    supplied = any(
        value is not None
        for value in (
            args.model,
            args.base_url,
            args.provider_secret,
            args.task_ids,
            args.temperature,
            args.timeout_multiplier,
            args.concurrency,
        )
    )
    benchmark_inputs = None
    if supplied:
        benchmark_inputs = {
            "model": args.model or "",
            "base_url": args.base_url or "",
            "provider_secret": args.provider_secret or "",
            "task_ids": [item.strip() for item in (args.task_ids or "").split(",") if item.strip()],
            "temperature": args.temperature or "",
            "timeout_multiplier": args.timeout_multiplier or "",
            "concurrency": args.concurrency or "",
        }
    failures = audit_release_workflow(
        manifest,
        workflow=args.workflow,
        runtime_sha=args.runtime_sha,
        runtime_is_descendant=is_descendant,
        changed_paths=changed_paths,
        benchmark_inputs=benchmark_inputs,
    )
    print(
        json.dumps(
            {
                "status": "PASS" if not failures else "BLOCKED",
                "failures": failures,
                "runtime_sha": args.runtime_sha,
                "implementation_sha": expected_sha,
                "release_only_changed_paths": changed_paths,
            }
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
