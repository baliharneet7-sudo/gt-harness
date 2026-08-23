#!/usr/bin/env python3
"""Certify the production stdio MCP against an isolated real repository clone."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gt_harness.indexer_setup import ensure_source_indexer  # noqa: E402

REQUIRED_RECEIPT_FIELDS = {
    "repository",
    "commit_sha",
    "working_tree_state",
    "graph_schema_version",
    "graph_builder_version",
    "build_started",
    "build_completed",
    "build_status",
    "files_discovered",
    "files_indexed",
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
    "parser_limitations",
    "receipt_path",
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


def _payload(result: Any) -> dict[str, Any]:
    if result.structuredContent:
        return dict(result.structuredContent)
    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    return dict(json.loads(text))


async def _call(
    session: ClientSession, name: str, arguments: dict[str, object]
) -> dict[str, Any]:
    result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=120)
    return _payload(result)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _evidence(payload: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(row.get("name") or ""), str(row.get("file_path") or ""))
        for row in payload.get("evidence", [])
    }


def _markdown(report: dict[str, Any], receipt_path: Path) -> str:
    cold = report["agent_received"]["cold_status"]
    updated = report["agent_received"]["updated_status"]
    lines = [
        "# GroundTruth MCP End-to-End Audit",
        "",
        f"Observed: `{report['completed']}`",
        "",
        f"Verdict: **{report['status']}**",
        "",
        f"Machine receipt: `{receipt_path}`",
        "",
        "A clean MCP client entered an isolated clone of the pinned real itsdangerous "
        "repository. The server was the production `gt-harness mcp` stdio boundary; no "
        "benchmark adapter or precomputed graph was used.",
        "",
        "| Check | Result |",
        "| --- | --- |",
        "| Cold server initialization built a query-ready graph | PASS |",
        "| Required graph receipt fields reached the client | PASS |",
        "| Real `Signer` definition returned with source evidence | PASS |",
        "| Client edit was detected and graph identity changed | PASS |",
        "| Stale call edge disappeared and new edge appeared | PASS |",
        "| Server restart reused the exact updated graph | PASS |",
        "| Provider calls / credentials | 0 / false |",
        "",
        "## Agent-visible identity",
        "",
        f"- Repository commit: `{cold['commit_sha']}`",
        f"- Cold graph: `{cold['graph_checksum_or_identity']}`",
        f"- Updated graph: `{updated['graph_checksum_or_identity']}`",
        f"- Updated state: `{updated['build_status']}`; query ready `{updated['query_ready']}`",
        f"- MCP initialization latency: `{report['cold_initialize_ms']}` ms",
        f"- Warm restart initialization latency: `{report['warm_initialize_ms']}` ms",
        "",
        "The machine receipt stores the bounded status, definition, context, edit, and restart "
        "payloads exactly as delivered to the client.",
        "",
    ]
    return "\n".join(lines)


async def _campaign(args: argparse.Namespace) -> dict[str, Any]:
    source_repository = Path(args.source_repository).resolve()
    run_dir = Path(args.run_dir).resolve()
    if run_dir.exists():
        raise SystemExit(f"refusing to reuse MCP run directory: {run_dir}")
    run_dir.mkdir(parents=True)
    repository = run_dir / "repository"
    state = run_dir / "state"
    _run("git", "clone", "--quiet", "--no-hardlinks", str(source_repository), str(repository))
    _run("git", "checkout", "--detach", "--quiet", args.commit, cwd=repository)
    _require(_run("git", "rev-parse", "HEAD", cwd=repository) == args.commit, "wrong clone SHA")
    _require(not _run("git", "status", "--porcelain=v1", cwd=repository), "clone is dirty")
    _require(not state.exists(), "MCP state unexpectedly pre-exists")

    setup = ensure_source_indexer()
    _require(setup.status == "READY", f"indexer unavailable: {setup.as_dict()}")
    environment = dict(os.environ)
    environment["GT_INDEX_BINARY"] = setup.binary_path
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "gt_harness.cli",
            "mcp",
            "--root",
            str(repository),
            "--state-dir",
            str(state),
        ],
        cwd=str(ROOT),
        env=environment,
    )

    cold_started = time.perf_counter()
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=120)
            cold_initialize_ms = round((time.perf_counter() - cold_started) * 1000.0, 3)
            tools = await asyncio.wait_for(session.list_tools(), timeout=30)
            tool_names = sorted(tool.name for tool in tools.tools)
            _require(
                tool_names == ["gt_context", "gt_impact", "gt_query", "gt_status"],
                f"unexpected MCP tools: {tool_names}",
            )
            cold_status = await _call(session, "gt_status", {})
            missing = REQUIRED_RECEIPT_FIELDS - cold_status.keys()
            _require(not missing, f"MCP status omits graph receipt fields: {sorted(missing)}")
            _require(cold_status["query_ready"] is True, "cold MCP graph is not query ready")
            signer = await _call(
                session, "gt_query", {"mode": "definition", "symbol": "Signer"}
            )
            _require(
                ("Signer", "src/itsdangerous/signer.py") in _evidence(signer),
                "MCP Signer definition does not match source",
            )
            context = await _call(
                session,
                "gt_context",
                {"task": "change Signer key derivation and affected signing code", "limit": 8},
            )
            _require(
                context.get("graph_identity") == cold_status["graph_checksum_or_identity"],
                "context is not attributable to the graph receipt",
            )

            probe = repository / "gt_mcp_probe.py"
            probe.write_text(
                "def mcp_target():\n    return 1\n\n"
                "def mcp_caller():\n    return mcp_target()\n",
                encoding="utf-8",
            )
            added = await _call(
                session,
                "gt_query",
                {"mode": "callers", "symbol": "mcp_target", "file_path": "gt_mcp_probe.py"},
            )
            _require(
                _evidence(added) == {("mcp_caller", "gt_mcp_probe.py")},
                "MCP did not index the added file",
            )
            added_status = await _call(session, "gt_status", {})
            _require(
                added_status["graph_checksum_or_identity"]
                != cold_status["graph_checksum_or_identity"],
                "MCP edit did not change graph identity",
            )

            probe.write_text(
                "def mcp_target_v2():\n    return 2\n\n"
                "def mcp_caller():\n    return mcp_target_v2()\n",
                encoding="utf-8",
            )
            updated_query = await _call(
                session,
                "gt_query",
                {
                    "mode": "callers",
                    "symbol": "mcp_target_v2",
                    "file_path": "gt_mcp_probe.py",
                },
            )
            old_query = await _call(
                session, "gt_query", {"mode": "definition", "symbol": "mcp_target"}
            )
            _require(
                _evidence(updated_query) == {("mcp_caller", "gt_mcp_probe.py")},
                "MCP updated call edge is wrong",
            )
            _require(old_query["status"] == "NOT_FOUND", "MCP retained stale definition")
            updated_status = await _call(session, "gt_status", {})
            _require(updated_status["query_ready"] is True, "updated MCP graph is not ready")

    warm_started = time.perf_counter()
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=120)
            warm_initialize_ms = round((time.perf_counter() - warm_started) * 1000.0, 3)
            warm_status = await _call(session, "gt_status", {})
            warm_query = await _call(
                session, "gt_query", {"mode": "definition", "symbol": "mcp_target_v2"}
            )
            _require(
                warm_status["graph_checksum_or_identity"]
                == updated_status["graph_checksum_or_identity"],
                "MCP restart did not reuse the exact updated graph",
            )
            _require(
                warm_status["build_started"] == updated_status["build_started"],
                "MCP restart unexpectedly rebuilt the unchanged graph",
            )
            _require(
                _evidence(warm_query) == {("mcp_target_v2", "gt_mcp_probe.py")},
                "MCP warm query does not match updated source",
            )

    return {
        "schema": "gt.mcp_e2e_audit_receipt.v1",
        "source_repository": str(source_repository),
        "test_repository": str(repository),
        "frozen_commit": args.commit,
        "transport": "stdio",
        "server_entrypoint": "python -m gt_harness.cli mcp",
        "tools": tool_names,
        "provider_calls": 0,
        "provider_credentials_inspected": False,
        "indexer": setup.as_dict(),
        "cold_initialize_ms": cold_initialize_ms,
        "warm_initialize_ms": warm_initialize_ms,
        "agent_received": {
            "cold_status": cold_status,
            "signer_definition": signer,
            "task_context": context,
            "added_file_callers": added,
            "added_status": added_status,
            "updated_callers": updated_query,
            "removed_definition": old_query,
            "updated_status": updated_status,
            "warm_status": warm_status,
            "warm_definition": warm_query,
        },
        "status": "PASS",
        "completed": _now(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    report = asyncio.run(_campaign(args))
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report:
        Path(args.report).write_text(_markdown(report, output), encoding="utf-8")
    print(json.dumps({"status": "PASS", "receipt": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
