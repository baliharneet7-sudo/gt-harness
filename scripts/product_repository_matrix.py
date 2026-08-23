#!/usr/bin/env python3
"""Build and reopen GT graphs for an exact, provider-free real-repository matrix."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gt_engine.repository_graph_service import RepositoryGraphService  # noqa: E402


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run(*argv: str, cwd: Path | None = None, timeout: float = 600.0) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        diagnostic = " ".join((completed.stderr or completed.stdout).split())[:1000]
        raise RuntimeError(f"command failed ({completed.returncode}): {argv[0]}: {diagnostic}")
    return completed.stdout.strip()


def _checkout(entry: dict[str, Any], destination: Path) -> None:
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise RuntimeError(f"existing matrix path is not a Git repository: {destination}")
        remote = _run("git", "remote", "get-url", "origin", cwd=destination)
        head = _run("git", "rev-parse", "HEAD", cwd=destination)
        status = _run("git", "status", "--porcelain=v1", cwd=destination)
        if remote != entry["url"] or head != entry["commit"] or status:
            raise RuntimeError(
                "existing matrix checkout does not match its frozen remote, commit, and clean state"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run("git", "init", "-q", str(destination))
    _run("git", "remote", "add", "origin", entry["url"], cwd=destination)
    _run(
        "git",
        "fetch",
        "--depth=1",
        "--filter=blob:none",
        "origin",
        entry["commit"],
        cwd=destination,
        timeout=1200,
    )
    _run("git", "checkout", "--detach", "--quiet", "FETCH_HEAD", cwd=destination)
    head = _run("git", "rev-parse", "HEAD", cwd=destination)
    if head != entry["commit"]:
        raise RuntimeError(f"checkout identity mismatch: {head} != {entry['commit']}")


def _database_metrics(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return {
            "nodes_by_language": {
                str(language or "UNKNOWN"): int(count)
                for language, count in connection.execute(
                    "SELECT language,COUNT(*) FROM nodes GROUP BY language ORDER BY language"
                )
            },
            "distinct_node_files": int(
                connection.execute("SELECT COUNT(DISTINCT file_path) FROM nodes").fetchone()[0]
            ),
            "edge_confidence": {
                "below_0_5": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM edges WHERE confidence < 0.5"
                    ).fetchone()[0]
                ),
                "at_least_0_5": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM edges WHERE confidence >= 0.5"
                    ).fetchone()[0]
                ),
                "at_least_0_9": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM edges WHERE confidence >= 0.9"
                    ).fetchone()[0]
                ),
            },
        }
    finally:
        connection.close()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 3)


class _ResourceMonitor:
    """Sample aggregate RSS and CPU for this audit process and active children."""

    def __init__(self) -> None:
        self.process = psutil.Process()
        self.stop_event = threading.Event()
        self.peak_rss_bytes = 0
        self.peak_cpu_seconds = 0.0
        initial = self.process.cpu_times()
        self.cpu_baseline_seconds = float(initial.user + initial.system)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self) -> None:
        rss = 0
        cpu = 0.0
        processes = [self.process]
        try:
            processes.extend(self.process.children(recursive=True))
        except (psutil.Error, OSError):
            pass
        for process in processes:
            try:
                rss += int(process.memory_info().rss)
                times = process.cpu_times()
                cpu += float(times.user + times.system)
            except (psutil.Error, OSError):
                continue
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        self.peak_cpu_seconds = max(self.peak_cpu_seconds, cpu)

    def _run(self) -> None:
        while not self.stop_event.wait(0.01):
            self._sample()
        self._sample()

    def start(self) -> None:
        self._sample()
        self.thread.start()

    def stop(self) -> dict[str, Any]:
        self.stop_event.set()
        self.thread.join(timeout=5)
        return {
            "method": "psutil_process_tree_sampling_10ms",
            "peak_rss_bytes": self.peak_rss_bytes,
            "cpu_seconds": round(
                max(0.0, self.peak_cpu_seconds - self.cpu_baseline_seconds), 3
            ),
        }


def _audit_repository(
    entry: dict[str, Any],
    repositories: Path,
    states: Path,
    timeout: float,
    query_repetitions: int,
    warm_repetitions: int,
) -> dict[str, Any]:
    started = _now()
    wall = time.perf_counter()
    repository = repositories / str(entry["id"])
    state = states / str(entry["id"])
    _checkout(entry, repository)
    clone_completed = time.perf_counter()
    service = RepositoryGraphService(repository, state_dir=state)
    monitor = _ResourceMonitor()
    monitor.start()
    receipt = service.build(force=True, timeout=timeout)
    resources = monitor.stop()
    build_completed = time.perf_counter()
    reopened = RepositoryGraphService(repository, state_dir=state)
    warm_start = time.perf_counter()
    warm = reopened.status()
    warm_start_ms = (time.perf_counter() - warm_start) * 1000.0
    warm_latencies: list[float] = []
    for _iteration in range(max(1, warm_repetitions)):
        warm_started = time.perf_counter()
        warm = reopened.status()
        warm_latencies.append((time.perf_counter() - warm_started) * 1000.0)
    query_receipts: list[dict[str, Any]] = []
    query_latencies: list[float] = []
    for query in entry.get("smoke_queries", []):
        samples: list[float] = []
        result: dict[str, Any] = {}
        for _iteration in range(max(1, query_repetitions)):
            query_started = time.perf_counter()
            result = reopened.query(
                str(query["mode"]),
                str(query["symbol"]),
                file_path=query.get("file"),
            )
            latency = (time.perf_counter() - query_started) * 1000.0
            samples.append(latency)
            query_latencies.append(latency)
        expected_file = str(query.get("expected_file") or "")
        matched = any(
            str(row.get("file_path") or "") == expected_file for row in result["evidence"]
        )
        query_receipts.append(
            {
                "mode": query["mode"],
                "symbol": query["symbol"],
                "expected_file": expected_file,
                "status": result["status"],
                "count": result["count"],
                "expected_file_found": matched,
                "latency_ms": {
                    "count": len(samples),
                    "p50": round(median(samples), 3),
                    "p95": _percentile(samples, 0.95),
                },
                "evidence_files": sorted(
                    {str(row.get("file_path") or "") for row in result["evidence"]}
                )[:20],
            }
        )
    identity_match = receipt.commit_sha == entry["commit"] == warm.commit_sha
    graph_match = (
        receipt.query_ready
        and warm.query_ready
        and receipt.graph_checksum_or_identity == warm.graph_checksum_or_identity
        and receipt.source_revision == warm.source_revision
    )
    queries_match = all(row["expected_file_found"] for row in query_receipts)
    status = "PASS" if identity_match and graph_match and queries_match else "FAIL"
    return {
        "id": entry["id"],
        "category": entry["category"],
        "url": entry["url"],
        "expected_commit": entry["commit"],
        "claimed_languages_under_test": entry["languages"],
        "status": status,
        "started": started,
        "completed": _now(),
        "checkout_duration_ms": round((clone_completed - wall) * 1000.0, 3),
        "build_wall_duration_ms": round((build_completed - clone_completed) * 1000.0, 3),
        "warm_status_duration_ms": round(warm_start_ms, 3),
        "warm_status_latency_ms": {
            "first_process_check": round(warm_start_ms, 3),
            "count": len(warm_latencies),
            "p50": round(median(warm_latencies), 3),
            "p95": _percentile(warm_latencies, 0.95),
        },
        "build_resources": resources,
        "total_duration_ms": round((time.perf_counter() - wall) * 1000.0, 3),
        "identity_match": identity_match,
        "warm_graph_match": graph_match,
        "build_receipt": receipt.as_dict(),
        "warm_receipt_status": warm.build_status.value,
        "database_metrics": (
            _database_metrics(Path(receipt.persistent_graph_path)) if receipt.query_ready else None
        ),
        "queries": query_receipts,
        "query_latency_ms": {
            "count": len(query_latencies),
            "p50": round(median(query_latencies), 3) if query_latencies else None,
            "p95": _percentile(query_latencies, 0.95),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="audit/real_repository_matrix.v1.json")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--query-repetitions", type=int, default=5)
    parser.add_argument("--warm-repetitions", type=int, default=5)
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "gt.real_repository_matrix.v1":
        raise SystemExit("unsupported repository matrix schema")
    selected = set(args.only)
    workspace = Path(args.workspace).resolve()
    repositories = workspace / "repositories"
    states = workspace / "states"
    rows: list[dict[str, Any]] = []
    for entry in manifest["repositories"]:
        if selected and entry["id"] not in selected:
            continue
        try:
            row = _audit_repository(
                entry,
                repositories,
                states,
                args.timeout,
                args.query_repetitions,
                args.warm_repetitions,
            )
        except Exception as exc:  # noqa: BLE001 - audit failures must be receipted
            row = {
                "id": entry["id"],
                "category": entry["category"],
                "url": entry["url"],
                "expected_commit": entry["commit"],
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": " ".join(str(exc).split())[:2000],
            }
        rows.append(row)
        print(json.dumps({"id": row["id"], "status": row["status"]}), flush=True)
    report = {
        "schema": "gt.real_repository_matrix_receipt.v1",
        "manifest": str(manifest_path),
        "started_from_clean_frozen_checkouts": True,
        "provider_calls": 0,
        "provider_credentials_inspected": False,
        "repositories": rows,
        "status": "PASS" if rows and all(row["status"] == "PASS" for row in rows) else "FAIL",
        "completed": _now(),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "receipt": str(output)}), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
