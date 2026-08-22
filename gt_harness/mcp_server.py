"""Production MCP backed exclusively by :class:`RepositoryGraphService`."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from gt_engine.repository_graph_service import (
    GraphNotReadyError,
    GraphStatus,
    RepositoryGraphService,
)


class RepositoryMCP:
    """Testable MCP controller; transport registration is a thin wrapper."""

    def __init__(self, service: RepositoryGraphService) -> None:
        self.service = service

    def prepare(self) -> dict[str, Any]:
        return self.service.build().as_dict()

    def status(self, *, verbose: bool = False) -> dict[str, Any]:
        value = self.service.status().as_dict()
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
            "coverage",
            "build_duration_ms",
            "graph_checksum_or_identity",
            "query_ready",
            "degraded_reasons",
            "skipped_reasons",
            "update_mode",
        )
        return {key: value[key] for key in keys}

    def _refresh_if_stale(self) -> None:
        receipt = self.service.status()
        if receipt.build_status in {GraphStatus.ABSENT, GraphStatus.STALE}:
            self.service.build()

    def query(
        self,
        mode: str,
        symbol: str,
        limit: int = 50,
        file_path: str = "",
        min_confidence: float = 0.5,
    ) -> dict[str, Any]:
        self._refresh_if_stale()
        try:
            return self.service.query(
                mode,
                symbol,
                limit=limit,
                file_path=file_path or None,
                min_confidence=min_confidence,
            )
        except (GraphNotReadyError, ValueError) as exc:
            receipt = self.service.status()
            return {
                "schema": "gt.graph_query.v1",
                "status": receipt.build_status.value,
                "query_ready": False,
                "error": str(exc),
                "degraded_reasons": list(receipt.degraded_reasons),
            }

    def context(self, task: str, limit: int = 12) -> dict[str, Any]:
        tokens = tuple(
            dict.fromkeys(
                token
                for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task or "")
                if token.lower() not in {"the", "and", "for", "from", "with", "this", "that"}
            )
        )[:12]
        rows: list[dict[str, Any]] = []
        identities: set[tuple[object, ...]] = set()
        bound = max(1, min(limit, 50))
        for token in tokens:
            result = self.query("search", token, limit=max(2, bound))
            for row in result.get("evidence", ()):
                identity = (row.get("file_path"), row.get("start_line"), row.get("qualified_name"))
                if identity not in identities:
                    identities.add(identity)
                    rows.append(row)
                if len(rows) >= bound:
                    break
            if len(rows) >= bound:
                break
        receipt = self.service.status()
        return {
            "schema": "gt.graph_context.v1",
            "task": task,
            "repository": receipt.repository,
            "commit_sha": receipt.commit_sha,
            "source_revision": receipt.source_revision,
            "build_status": receipt.build_status.value,
            "query_ready": receipt.query_ready,
            "evidence": rows,
            "count": len(rows),
            "degraded_reasons": list(receipt.degraded_reasons),
        }


def create_server(root: str | Path, *, state_dir: str | Path | None = None) -> FastMCP:
    controller = RepositoryMCP(RepositoryGraphService(root, state_dir=state_dir))
    controller.prepare()
    app = FastMCP(name="gt-harness")

    @app.tool(structured_output=False)
    async def gt_status(verbose: bool = False) -> dict[str, Any]:
        """Return the repository-bound graph receipt and explicit readiness state."""

        return controller.status(verbose=verbose)

    @app.tool(structured_output=False)
    async def gt_query(
        mode: str,
        symbol: str,
        limit: int = 50,
        file_path: str = "",
        min_confidence: float = 0.5,
    ) -> dict[str, Any]:
        """Query exact, confidence-bounded graph relationships with source evidence."""

        return controller.query(mode, symbol, limit, file_path, min_confidence)

    @app.tool(structured_output=False)
    async def gt_context(task: str, limit: int = 12) -> dict[str, Any]:
        """Return bounded graph-backed files and symbols relevant to an engineering task."""

        return controller.context(task, limit)

    @app.tool(structured_output=False)
    async def gt_impact(
        symbol: str,
        limit: int = 50,
        file_path: str = "",
        min_confidence: float = 0.5,
    ) -> dict[str, Any]:
        """Return source-evidenced reverse structural dependencies for a symbol."""

        return controller.query("impact", symbol, limit, file_path, min_confidence)

    return app


def run_server(
    *,
    root: str | Path,
    state_dir: str | Path | None = None,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8799,
) -> int:
    app = create_server(root, state_dir=state_dir)
    if transport != "stdio":
        app.settings.host = host
        app.settings.port = int(port)
    try:
        app.run(transport=transport)  # type: ignore[arg-type]
    except BrokenPipeError:
        return 0
    return 0


__all__ = ["RepositoryMCP", "create_server", "run_server"]
