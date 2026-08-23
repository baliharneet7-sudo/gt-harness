"""Production MCP backed exclusively by :class:`RepositoryGraphService`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from gt_engine.context_composer import compose_repository_context
from gt_engine.repository_graph_service import (
    GraphStatus,
    RepositoryGraphService,
    public_graph_receipt,
)


class RepositoryMCP:
    """Testable MCP controller; transport registration is a thin wrapper."""

    def __init__(self, service: RepositoryGraphService) -> None:
        self.service = service
        self.startup_errors: list[str] = []

    def prepare(self) -> dict[str, Any]:
        return self.service.build().as_dict()

    def status(self, *, verbose: bool = False) -> dict[str, Any]:
        receipt = self.service.status()
        value = receipt.as_dict()
        if verbose:
            value["startup_errors"] = list(self.startup_errors)
            return value
        output = public_graph_receipt(receipt, receipt_path=self.service.receipt_path)
        output["startup_errors"] = list(self.startup_errors)
        return output

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
        try:
            self._refresh_if_stale()
            return self.service.query(
                mode,
                symbol,
                limit=limit,
                file_path=file_path or None,
                min_confidence=min_confidence,
            )
        except Exception as exc:  # noqa: BLE001 - MCP must return explicit failure, not exit
            receipt = self.service.status()
            return {
                "schema": "gt.graph_query.v1",
                "status": receipt.build_status.value,
                "query_ready": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "repository": receipt.repository,
                "commit_sha": receipt.commit_sha,
                "source_revision": receipt.source_revision,
                "graph_identity": receipt.graph_checksum_or_identity,
                "degraded_reasons": list(receipt.degraded_reasons),
            }

    def context(self, task: str, limit: int = 12) -> dict[str, Any]:
        try:
            self._refresh_if_stale()
            composition = compose_repository_context(self.service, task, limit=limit)
        except Exception as exc:  # noqa: BLE001 - readiness failure stays observable
            composition = {
                "task_tokens": [],
                "anchor_count": 0,
                "query_count": 0,
                "evidence": [],
                "count": 0,
                "truncated": False,
                "query_errors": [f"context:{type(exc).__name__}:{exc}"],
                "min_confidence": 0.5,
            }
        composition_schema = composition.pop("schema", "gt.graph_context_composition.v1")
        receipt = self.service.status()
        return {
            "schema": "gt.graph_context.v2",
            "task": task,
            "repository": receipt.repository,
            "commit_sha": receipt.commit_sha,
            "source_revision": receipt.source_revision,
            "graph_identity": receipt.graph_checksum_or_identity,
            "graph_builder_version": receipt.graph_builder_version,
            "build_status": receipt.build_status.value,
            "query_ready": receipt.query_ready,
            **composition,
            "composition_schema": composition_schema,
            "degraded_reasons": list(receipt.degraded_reasons),
        }


def create_server(root: str | Path, *, state_dir: str | Path | None = None) -> FastMCP:
    controller = RepositoryMCP(RepositoryGraphService(root, state_dir=state_dir))
    try:
        controller.prepare()
    except Exception as exc:  # noqa: BLE001 - initialization remains observable via MCP
        controller.startup_errors.append(
            f"{type(exc).__name__}: {' '.join(str(exc).split())[:1000]}"
        )
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
