#!/usr/bin/env python3
"""Fail closed unless a workflow and exact commit are release-authorized."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def audit_release_workflow(
    manifest: dict,
    *,
    workflow: str,
    runtime_sha: str,
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
    if runtime_sha != expected_sha:
        failures.append("runtime_sha_not_active_release")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="eval/release/active_release.json")
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--runtime-sha", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    failures = audit_release_workflow(
        manifest,
        workflow=args.workflow,
        runtime_sha=args.runtime_sha,
    )
    print(json.dumps({"status": "PASS" if not failures else "BLOCKED", "failures": failures}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
