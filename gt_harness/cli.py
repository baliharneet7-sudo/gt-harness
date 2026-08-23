"""GT-Harness command-line product boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from gt_engine.repository_graph_service import (
    SUPPORTED_QUERY_MODES,
    GraphNotReadyError,
    GraphReceipt,
    RepositoryGraphService,
    compute_repository_identity,
    public_graph_receipt,
)
from gt_harness.indexer_setup import ensure_source_indexer, find_go


def _emit(value: object, *, pretty: bool = True) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2 if pretty else None))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gt-harness",
        description="Model-agnostic benchmark harness with GroundTruth repository intelligence.",
    )
    parser.add_argument("--version", action="version", version="gt-harness 0.9.0")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Verify runtime, indexer, and product dependencies.")
    doctor.add_argument("--no-build", action="store_true", help="Inspect Go without compiling.")

    graph = sub.add_parser("graph", help="Build, inspect, or query the repository graph.")
    graph_sub = graph.add_subparsers(dest="graph_command", required=True)
    for name in ("build", "status"):
        item = graph_sub.add_parser(name)
        item.add_argument("--root", default=".")
        item.add_argument("--state-dir", default=None)
        item.add_argument(
            "--verbose",
            action="store_true",
            help="Emit the complete persisted graph receipt.",
        )
        if name == "build":
            item.add_argument("--force", action="store_true")
            item.add_argument("--timeout", type=float, default=600.0)
    query = graph_sub.add_parser("query")
    query.add_argument("mode", choices=SUPPORTED_QUERY_MODES)
    query.add_argument("symbol")
    query.add_argument("--root", default=".")
    query.add_argument("--state-dir", default=None)
    query.add_argument("--limit", type=int, default=50)
    query.add_argument("--file", default=None, help="Disambiguate a symbol by repository path.")
    query.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="Minimum relationship confidence (default: 0.5).",
    )
    query.add_argument("--refresh", action="store_true")

    mcp = sub.add_parser("mcp", help="Serve the production repository-intelligence MCP.")
    mcp.add_argument("--root", default=".")
    mcp.add_argument("--state-dir", default=None)
    mcp.add_argument("--transport", choices=("stdio", "streamable-http", "sse"), default="stdio")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8799)

    run = sub.add_parser("run", help="Run the common coding-agent scaffold.")
    run.add_argument("task")
    run.add_argument("--model", required=True, help="Exact model identifier for both arms.")
    run.add_argument("--base-url", default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--max-iterations", type=int, default=30)
    run.add_argument("--time-budget-seconds", type=float, default=None)
    run.add_argument("--treatment", choices=("bare", "groundtruth"), default="bare")
    run.add_argument("--root", default=".")
    run.add_argument("--state-dir", default=None, help="Private graph/runtime state directory.")
    run.add_argument("--run-id", default=None)
    run.add_argument("--task-id", default=None)
    run.add_argument("--trial-id", default="1")
    run.add_argument(
        "--output",
        default=None,
        help="Run receipt path (default: .groundtruth/runs/<run-id>.json).",
    )

    compare = sub.add_parser("compare", help="Compare completed benchmark treatment receipts.")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--treatment", required=True)
    compare.add_argument("--output", default=None)
    sub.add_parser("certify", help="Evaluate product and benchmark release gates.")
    return parser


def _doctor(*, build: bool) -> int:
    go = find_go()
    receipt = ensure_source_indexer() if build else None
    checks: dict[str, object] = {
        "schema": "gt.doctor.v1",
        "python": {
            "status": "READY" if sys.version_info >= (3, 12) else "FAILED",
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "git": {
            "status": "READY" if shutil.which("git") else "FAILED",
            "path": shutil.which("git") or "",
        },
        "go": {"status": "READY" if go else "FAILED", "path": str(go or "")},
        "indexer": (
            receipt.as_dict()
            if receipt is not None
            else {"status": "NOT_BUILT", "diagnostic": "--no-build requested"}
        ),
        "provider_credentials_required": False,
        "provider_calls": 0,
    }
    ready = all(
        isinstance(checks[name], dict) and checks[name]["status"] == "READY"
        for name in ("python", "git", "go")
    )
    if receipt is not None:
        ready = ready and receipt.status == "READY"
    checks["status"] = "READY" if ready else "FAILED"
    _emit(checks)
    return 0 if ready else 1


def _graph_receipt_output(
    service: RepositoryGraphService, receipt: GraphReceipt, *, verbose: bool
) -> dict[str, object]:
    value = receipt.as_dict()
    if verbose:
        return value
    return public_graph_receipt(receipt, receipt_path=service.receipt_path)


def _graph(args: argparse.Namespace) -> int:
    service = RepositoryGraphService(args.root, state_dir=args.state_dir)
    if args.graph_command == "build":
        try:
            receipt = service.build(force=args.force, timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001 - product boundary must fail explicitly
            _emit(
                {
                    "schema": "gt.graph_receipt_error.v1",
                    "status": "FAILED",
                    "query_ready": False,
                    "error_type": type(exc).__name__,
                    "error": " ".join(str(exc).split())[:2000],
                    "repository": str(service.root),
                    "receipt_path": str(service.receipt_path),
                }
            )
            return 1
        _emit(_graph_receipt_output(service, receipt, verbose=args.verbose))
        return 0 if receipt.query_ready else 1
    if args.graph_command == "status":
        receipt = service.status()
        _emit(_graph_receipt_output(service, receipt, verbose=args.verbose))
        return 0 if receipt.query_ready else 1
    if args.refresh and not service.status().query_ready:
        service.build()
    try:
        _emit(
            service.query(
                args.mode,
                args.symbol,
                limit=args.limit,
                file_path=args.file,
                min_confidence=args.min_confidence,
            )
        )
        return 0
    except (GraphNotReadyError, ValueError) as exc:
        _emit({"schema": "gt.graph_query.v1", "status": "FAILED", "error": str(exc)})
        return 1


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _run_repository_identity(root: Path) -> dict[str, object]:
    identity = compute_repository_identity(root)
    return {
        "repository": identity.repository,
        "commit_sha": identity.commit_sha,
        "branch": identity.branch,
        "working_tree_state": identity.working_tree_state,
        "source_revision": identity.source_revision,
        "files_discovered": identity.files_discovered,
        "graph_input_files": identity.graph_input_files,
        "source_bytes": identity.source_bytes,
    }


def _run_agent(args: argparse.Namespace) -> int:
    from gt_harness.treatments import BareTreatment, GroundTruthTreatment
    from nano.agent import Agent
    from nano.cli import _print_event, build_provider
    from nano.prompts import SYSTEM_PROMPT
    from nano.tools import TOOLS

    root = Path(args.root).resolve()
    temperature = getattr(args, "temperature", None)
    requested_run_id = getattr(args, "run_id", None)
    output_value = getattr(args, "output", None)
    state_dir = getattr(args, "state_dir", None)
    generated_run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    run_id = str(requested_run_id or generated_run_id)
    task_fingerprint = hashlib.sha256(args.task.encode("utf-8")).hexdigest()
    task_id = str(getattr(args, "task_id", None) or f"task-{task_fingerprint[:16]}")
    trial_id = str(getattr(args, "trial_id", "1") or "1")
    base_url = getattr(args, "base_url", None)
    run_configuration = {
        "model": args.model,
        "base_url_configured": bool(base_url),
        "base_url_sha256": (
            hashlib.sha256(str(base_url).encode("utf-8")).hexdigest() if base_url else None
        ),
        "temperature": temperature,
        "max_iterations": int(args.max_iterations),
        "time_budget_seconds": args.time_budget_seconds,
        "agent_scaffold": "nano.agent.Agent",
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "tool_policy_sha256": _sha256_json(TOOLS),
    }
    repository_start = _run_repository_identity(root)
    output_path = (
        Path(output_value).resolve()
        if output_value
        else root / ".groundtruth" / "runs" / f"{run_id}.json"
    )
    treatment = (
        GroundTruthTreatment(root, state_dir=state_dir)
        if args.treatment == "groundtruth"
        else BareTreatment()
    )
    started = _now()
    started_clock = time.perf_counter()
    try:
        provider = build_provider(
            model=args.model,
            base_url=base_url,
            temperature=temperature,
        )
        agent = Agent(
            provider=provider,
            system=SYSTEM_PROMPT,
            max_iterations=args.max_iterations,
            on_event=_print_event,
            treatment=treatment,
            time_budget_seconds=args.time_budget_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - setup failure must still leave a receipt
        receipt = {
            "schema": "gt.run_receipt.v1",
            "run_id": run_id,
            "task_id": task_id,
            "task_fingerprint": task_fingerprint,
            "trial_id": trial_id,
            "status": "ERROR",
            "error_type": type(exc).__name__,
            "started": started,
            "completed": _now(),
            "duration_ms": round((time.perf_counter() - started_clock) * 1000, 3),
            "repository": str(root),
            **run_configuration,
            "repository_start": repository_start,
            "repository_end": _run_repository_identity(root),
            "treatment": args.treatment,
            "resolved": None,
            "provider_calls": 0,
        }
        _write_json_atomic(output_path, receipt)
        _emit({**receipt, "receipt_path": str(output_path)})
        return 1
    result = agent.run(args.task)
    treatment_receipt = next(
        (
            dict(row["receipt"])
            for row in reversed(result.transcript)
            if row.get("type") == "treatment_receipt" and isinstance(row.get("receipt"), dict)
        ),
        None,
    )
    provider_calls = sum(1 for row in result.transcript if row.get("type") == "assistant")
    receipt = {
        "schema": "gt.run_receipt.v1",
        "run_id": run_id,
        "task_id": task_id,
        "task_fingerprint": task_fingerprint,
        "trial_id": trial_id,
        "status": "COMPLETED" if result.stop_reason == "end_turn" else "ERROR",
        "started": started,
        "completed": _now(),
        "duration_ms": round((time.perf_counter() - started_clock) * 1000, 3),
        "repository": str(root),
        **run_configuration,
        "repository_start": repository_start,
        "repository_end": _run_repository_identity(root),
        "treatment": args.treatment,
        "resolved": None,
        "stop_reason": result.stop_reason,
        "iterations": result.iterations,
        "provider_calls": provider_calls,
        "input_tokens": result.total_input_tokens,
        "output_tokens": result.total_output_tokens,
        "cached_tokens": result.total_cache_read_tokens,
        "treatment_receipt": treatment_receipt,
        "treatment_receipt_present": treatment_receipt is not None,
        "transcript": result.transcript,
    }
    if treatment_receipt is None:
        receipt["status"] = "ERROR"
        receipt["error_type"] = "treatment_receipt_missing"
    _write_json_atomic(output_path, receipt)
    _emit(
        {
            "schema": receipt["schema"],
            "run_id": run_id,
            "status": receipt["status"],
            "stop_reason": result.stop_reason,
            "provider_calls": provider_calls,
            "receipt_path": str(output_path),
            "treatment_receipt_present": treatment_receipt is not None,
        }
    )
    return 0 if result.stop_reason == "end_turn" and treatment_receipt is not None else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor(build=not args.no_build)
    if args.command == "graph":
        return _graph(args)
    if args.command == "mcp":
        from gt_harness.mcp_server import run_server

        return run_server(
            root=args.root,
            state_dir=args.state_dir,
            transport=args.transport,
            host=args.host,
            port=args.port,
        )
    if args.command == "run":
        return _run_agent(args)
    if args.command == "compare":
        from gt_harness.comparison import ComparisonError, compare_receipt_paths

        try:
            report = compare_receipt_paths(args.baseline, args.treatment)
        except ComparisonError as exc:
            _emit({"schema": "gt.paired_comparison.v1", "status": "FAILED", "error": str(exc)})
            return 1
        if args.output:
            _write_json_atomic(Path(args.output).resolve(), report)
        _emit(report)
        return 0 if report["status"] == "COMPLETE" else 1
    print(f"{args.command}: blocked until its evidence gate is complete", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
