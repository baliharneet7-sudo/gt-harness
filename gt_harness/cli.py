"""GT-Harness command-line product boundary."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path

from gt_engine.repository_graph_service import (
    SUPPORTED_QUERY_MODES,
    GraphNotReadyError,
    GraphReceipt,
    RepositoryGraphService,
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
    query.add_argument("--refresh", action="store_true")

    mcp = sub.add_parser("mcp", help="Serve the production repository-intelligence MCP.")
    mcp.add_argument("--root", default=".")
    mcp.add_argument("--state-dir", default=None)
    mcp.add_argument("--transport", choices=("stdio", "streamable-http", "sse"), default="stdio")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8799)

    run = sub.add_parser("run", help="Run the common coding-agent scaffold.")
    run.add_argument("task")
    run.add_argument("--model", default="claude-opus-4-8")
    run.add_argument("--base-url", default=None)
    run.add_argument("--max-iterations", type=int, default=30)
    run.add_argument("--time-budget-seconds", type=float, default=None)
    run.add_argument("--treatment", choices=("bare", "groundtruth"), default="bare")
    run.add_argument("--root", default=".")

    sub.add_parser("compare", help="Compare completed benchmark treatment receipts.")
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
    keys = (
        "receipt_schema",
        "repository",
        "commit_sha",
        "working_tree_state",
        "source_revision",
        "graph_schema_version",
        "graph_builder_version",
        "build_started",
        "build_completed",
        "build_status",
        "files_discovered",
        "files_attempted",
        "files_indexed",
        "files_skipped",
        "files_failed",
        "symbols",
        "nodes_by_type",
        "edges_by_type",
        "coverage",
        "build_duration_ms",
        "persistent_graph_path",
        "graph_checksum_or_identity",
        "query_ready",
        "degraded_reasons",
        "skipped_reasons",
        "update_mode",
        "graph_bytes",
        "source_bytes",
    )
    output = {key: value[key] for key in keys}
    output["receipt_path"] = str(service.receipt_path)
    return output


def _graph(args: argparse.Namespace) -> int:
    service = RepositoryGraphService(args.root, state_dir=args.state_dir)
    if args.graph_command == "build":
        receipt = service.build(force=args.force, timeout=args.timeout)
        _emit(_graph_receipt_output(service, receipt, verbose=args.verbose))
        return 0 if receipt.query_ready else 1
    if args.graph_command == "status":
        receipt = service.status()
        _emit(_graph_receipt_output(service, receipt, verbose=args.verbose))
        return 0 if receipt.query_ready else 1
    if args.refresh and not service.status().query_ready:
        service.build()
    try:
        _emit(service.query(args.mode, args.symbol, limit=args.limit))
        return 0
    except (GraphNotReadyError, ValueError) as exc:
        _emit({"schema": "gt.graph_query.v1", "status": "FAILED", "error": str(exc)})
        return 1


def _run_agent(args: argparse.Namespace) -> int:
    from gt_harness.treatments import BareTreatment, GroundTruthTreatment
    from nano.agent import Agent
    from nano.cli import _print_event, build_provider
    from nano.prompts import SYSTEM_PROMPT

    treatment = (
        GroundTruthTreatment(Path(args.root).resolve())
        if args.treatment == "groundtruth"
        else BareTreatment()
    )
    provider = build_provider(model=args.model, base_url=args.base_url)
    agent = Agent(
        provider=provider,
        system=SYSTEM_PROMPT,
        max_iterations=args.max_iterations,
        on_event=_print_event,
        treatment=treatment,
        time_budget_seconds=args.time_budget_seconds,
    )
    result = agent.run(args.task)
    return 0 if result.stop_reason == "end_turn" else 1


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
    print(f"{args.command}: blocked until its evidence gate is complete", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
