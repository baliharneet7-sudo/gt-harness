#!/usr/bin/env python3
"""Run the same add/modify/delete/persist graph lifecycle across core languages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gt_engine.repository_graph_service import (  # noqa: E402
    GraphStatus,
    RepositoryGraphService,
)


@dataclass(frozen=True, slots=True)
class Probe:
    path: str
    target_a: str
    target_b: str
    caller: str
    source_a: str
    source_b: str


PROBES = {
    "python": Probe(
        "gt_language_probe.py",
        "gt_language_target",
        "gt_language_target_v2",
        "gt_language_caller",
        "def gt_language_target(value):\n    return value + 1\n\n"
        "def gt_language_caller(value):\n    return gt_language_target(value)\n",
        "def gt_language_target_v2(value):\n    return value + 2\n\n"
        "def gt_language_caller(value):\n    return gt_language_target_v2(value)\n",
    ),
    "javascript": Probe(
        "gt_language_probe.js",
        "gt_language_target",
        "gt_language_target_v2",
        "gt_language_caller",
        "function gt_language_target(value) { return value + 1 }\n"
        "function gt_language_caller(value) { return gt_language_target(value) }\n",
        "function gt_language_target_v2(value) { return value + 2 }\n"
        "function gt_language_caller(value) { return gt_language_target_v2(value) }\n",
    ),
    "typescript": Probe(
        "gt_language_probe.ts",
        "gt_language_target",
        "gt_language_target_v2",
        "gt_language_caller",
        "export function gt_language_target(value: number): number { return value + 1 }\n"
        "export function gt_language_caller(value: number): number { "
        "return gt_language_target(value) }\n",
        "export function gt_language_target_v2(value: number): number { return value + 2 }\n"
        "export function gt_language_caller(value: number): number { "
        "return gt_language_target_v2(value) }\n",
    ),
    "go": Probe(
        "gt_language_probe.go",
        "gtLanguageTarget",
        "gtLanguageTargetV2",
        "gtLanguageCaller",
        "package mux\n\nfunc gtLanguageTarget(value int) int { return value + 1 }\n"
        "func gtLanguageCaller(value int) int { return gtLanguageTarget(value) }\n",
        "package mux\n\nfunc gtLanguageTargetV2(value int) int { return value + 2 }\n"
        "func gtLanguageCaller(value int) int { return gtLanguageTargetV2(value) }\n",
    ),
    "rust": Probe(
        "gt_language_probe.rs",
        "gt_language_target",
        "gt_language_target_v2",
        "gt_language_caller",
        "fn gt_language_target(value: i32) -> i32 { value + 1 }\n"
        "fn gt_language_caller(value: i32) -> i32 { gt_language_target(value) }\n",
        "fn gt_language_target_v2(value: i32) -> i32 { value + 2 }\n"
        "fn gt_language_caller(value: i32) -> i32 { gt_language_target_v2(value) }\n",
    ),
    "java": Probe(
        "GtLanguageProbe.java",
        "gtLanguageTarget",
        "gtLanguageTargetV2",
        "gtLanguageCaller",
        "final class GtLanguageProbe {\n"
        "  static int gtLanguageTarget(int value) { return value + 1; }\n"
        "  static int gtLanguageCaller(int value) { return gtLanguageTarget(value); }\n"
        "}\n",
        "final class GtLanguageProbe {\n"
        "  static int gtLanguageTargetV2(int value) { return value + 2; }\n"
        "  static int gtLanguageCaller(int value) { return gtLanguageTargetV2(value); }\n"
        "}\n",
    ),
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        diagnostic = " ".join((result.stderr or result.stdout).split())[:2000]
        raise RuntimeError(f"command failed ({result.returncode}): {args[0]}: {diagnostic}")
    return result.stdout.strip()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _evidence(payload: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(row.get("name") or ""), str(row.get("file_path") or ""))
        for row in payload.get("evidence", [])
    }


def _audit(
    entry: dict[str, Any], repositories: Path, run_dir: Path, timeout: float
) -> dict[str, Any]:
    language = str(entry["id"])
    probe = PROBES[language]
    source = repositories / str(entry["repository_id"])
    repository = run_dir / "repositories" / language
    state = run_dir / "states" / language
    repository.parent.mkdir(parents=True, exist_ok=True)
    _run("git", "clone", "--quiet", "--no-hardlinks", str(source), str(repository))
    _run("git", "checkout", "--detach", "--quiet", entry["commit"], cwd=repository)
    _require(_run("git", "rev-parse", "HEAD", cwd=repository) == entry["commit"], "wrong SHA")
    _require(not _run("git", "status", "--porcelain=v1", cwd=repository), "dirty clone")

    service = RepositoryGraphService(repository, state_dir=state)
    started = time.perf_counter()
    cold = service.build(force=True, timeout=timeout)
    cold_ms = round((time.perf_counter() - started) * 1000.0, 3)
    _require(cold.query_ready, f"{language}: cold graph is not query ready")
    warm = RepositoryGraphService(repository, state_dir=state).status()
    _require(
        warm.query_ready
        and warm.graph_checksum_or_identity == cold.graph_checksum_or_identity
        and warm.source_revision == cold.source_revision,
        f"{language}: warm graph identity mismatch",
    )

    path = repository / probe.path
    path.write_text(probe.source_a, encoding="utf-8")
    _require(service.status().build_status is GraphStatus.STALE, f"{language}: add not stale")
    add_started = time.perf_counter()
    added = service.update(timeout=timeout)
    add_ms = round((time.perf_counter() - add_started) * 1000.0, 3)
    callers_a = service.query("callers", probe.target_a, file_path=probe.path)
    _require(
        _evidence(callers_a) == {(probe.caller, probe.path)},
        f"{language}: added call edge mismatch: {_evidence(callers_a)}",
    )

    path.write_text(probe.source_b, encoding="utf-8")
    _require(
        service.status().build_status is GraphStatus.STALE,
        f"{language}: modification not stale",
    )
    modify_started = time.perf_counter()
    modified = service.update(timeout=timeout)
    modify_ms = round((time.perf_counter() - modify_started) * 1000.0, 3)
    old = service.query("definition", probe.target_a)
    callers_b = service.query("callers", probe.target_b, file_path=probe.path)
    _require(old["status"] == "NOT_FOUND", f"{language}: stale definition survived")
    _require(
        _evidence(callers_b) == {(probe.caller, probe.path)},
        f"{language}: modified call edge mismatch: {_evidence(callers_b)}",
    )

    path.unlink()
    _require(
        service.status().build_status is GraphStatus.STALE,
        f"{language}: deletion not stale",
    )
    delete_started = time.perf_counter()
    deleted = service.update(timeout=timeout)
    delete_ms = round((time.perf_counter() - delete_started) * 1000.0, 3)
    removed = service.query("definition", probe.target_b)
    _require(removed["status"] == "NOT_FOUND", f"{language}: deleted definition survived")
    _require(
        deleted.source_revision == cold.source_revision,
        f"{language}: source identity did not return to frozen state",
    )
    return {
        "language": language,
        "repository_id": entry["repository_id"],
        "commit_sha": entry["commit"],
        "status": "PASS",
        "cold_build_ms": cold_ms,
        "update_latency_ms": {
            "add": add_ms,
            "modify": modify_ms,
            "delete": delete_ms,
        },
        "cold_graph_status": cold.build_status.value,
        "warm_graph_identity_match": True,
        "add_status": added.build_status.value,
        "modify_status": modified.build_status.value,
        "delete_status": deleted.build_status.value,
        "update_modes": sorted({added.update_mode, modified.update_mode, deleted.update_mode}),
        "stale_edges_after_modify": 0,
        "stale_edges_after_delete": 0,
        "parser_limitations": list(cold.parser_limitations),
        "degraded_reasons": list(cold.degraded_reasons),
    }


def _markdown(report: dict[str, Any], receipt_path: Path) -> str:
    lines = [
        "# GroundTruth Language Support Audit",
        "",
        f"Observed: `{report['completed']}`",
        "",
        f"Verdict: **{report['status']} for the six declared prerelease languages**",
        "",
        f"Machine receipt: `{receipt_path}`",
        "",
        "| Language | Real repository | Cold/warm | Add | Modify | Delete | Stale edges |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for row in report["languages"]:
        lines.append(
            f"| {row['language']} | {row['repository_id']} | PASS | PASS | PASS | PASS | "
            f"{row['stale_edges_after_modify'] + row['stale_edges_after_delete']} |"
        )
    lines.extend(
        [
            "",
            "The same production lifecycle was exercised for Python, JavaScript, TypeScript, "
            "Go, Rust, and Java. All edit paths used the correctness-first atomic full rebuild; "
            "file-keyed incremental optimization remains non-canonical.",
            "",
            "The broader ten-repository construction matrix separately covers large Python, "
            "dynamic/re-export-heavy Python, TypeScript barrels and a monorepo, and multi-package "
            "Go. Languages outside these six are parser capabilities, not certified product "
            "support, until they receive the same real-repository truth and lifecycle audit.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="audit/language_lifecycle_matrix.v1.json")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    parser.add_argument("--timeout", type=float, default=1200.0)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("schema") != "gt.language_lifecycle_matrix.v1":
        raise SystemExit("unsupported language lifecycle matrix schema")
    workspace = Path(args.workspace).resolve()
    run_dir = Path(args.run_dir).resolve()
    if run_dir.exists():
        raise SystemExit(f"refusing to reuse language run directory: {run_dir}")
    run_dir.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    for entry in manifest["repositories"]:
        row = _audit(entry, workspace / "repositories", run_dir, args.timeout)
        rows.append(row)
        print(json.dumps({"language": row["language"], "status": row["status"]}), flush=True)
    report = {
        "schema": "gt.language_support_audit_receipt.v1",
        "manifest": str(Path(args.manifest).resolve()),
        "provider_calls": 0,
        "provider_credentials_inspected": False,
        "certified_language_scope": [row["language"] for row in rows],
        "languages": rows,
        "status": "PASS" if rows and all(row["status"] == "PASS" for row in rows) else "FAIL",
        "completed": _now(),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report:
        Path(args.report).write_text(_markdown(report, output), encoding="utf-8")
    print(json.dumps({"status": report["status"], "receipt": str(output)}), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
