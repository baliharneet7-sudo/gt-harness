from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from gt_harness.indexer_setup import ensure_source_indexer


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _payload(result) -> dict[str, object]:
    if result.structuredContent:
        return dict(result.structuredContent)
    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    return json.loads(text)


async def _call(session: ClientSession, name: str, arguments: dict[str, object]):
    return await asyncio.wait_for(session.call_tool(name, arguments), timeout=20)


@pytest.mark.asyncio
@pytest.mark.real_graph
@pytest.mark.timeout(60)
async def test_stdio_mcp_builds_updates_and_reuses_the_production_graph(tmp_path: Path) -> None:
    setup = ensure_source_indexer()
    assert setup.status == "READY", setup.as_dict()
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "gt@example.invalid")
    _git(root, "config", "user.name", "GT Test")
    (root / "core.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    (root / "caller.py").write_text(
        "from core import target\n\ndef invoke():\n    return target()\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")

    environment = dict(os.environ)
    environment["GT_INDEX_BINARY"] = setup.binary_path
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gt_harness.cli", "mcp", "--root", str(root)],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=environment,
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=20)
            tools = await asyncio.wait_for(session.list_tools(), timeout=20)
            assert {tool.name for tool in tools.tools} == {
                "gt_status",
                "gt_query",
                "gt_context",
                "gt_impact",
            }
            first = _payload(await _call(session, "gt_status", {}))
            assert first["query_ready"] is True
            assert "graph_input_hashes" not in first
            definition = _payload(
                await _call(session, "gt_query", {"mode": "definition", "symbol": "target"})
            )
            assert definition["count"] == 1
            first_identity = first["graph_checksum_or_identity"]
            first_started = first["build_started"]

            (root / "caller.py").write_text("def invoke():\n    return 2\n", encoding="utf-8")
            callers = _payload(
                await _call(session, "gt_query", {"mode": "callers", "symbol": "target"})
            )
            assert callers["count"] == 0
            updated = _payload(await _call(session, "gt_status", {}))
            assert updated["query_ready"] is True
            assert updated["update_mode"] == "incremental"
            assert updated["graph_checksum_or_identity"] != first_identity
            updated_started = updated["build_started"]

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=20)
            warm = _payload(await _call(session, "gt_status", {}))
            assert warm["query_ready"] is True
            assert warm["build_started"] != first_started
            assert warm["build_started"] == updated_started
            warm_identity = warm["graph_checksum_or_identity"]
            repeated = _payload(await _call(session, "gt_status", {}))
            assert repeated["graph_checksum_or_identity"] == warm_identity
