"""Benchmark treatments for the common coding-agent scaffold.

Treatments may add bounded evidence and record receipts.  They cannot select,
rewrite, reject, retry, or execute an agent action and they make no provider
calls.  This keeps model, prompt, tool policy, and step budget arm-neutral.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gt_engine.context_composer import compose_repository_context
from gt_engine.repository_graph_service import GraphStatus, RepositoryGraphService


@dataclass(slots=True)
class BareTreatment:
    treatment_id: str = field(default="bare", init=False)

    def prepare(self, task: str) -> str:
        return ""

    def before_model_call(self, iteration: int) -> str:
        return ""

    def after_action(
        self,
        name: str,
        arguments: dict[str, Any],
        output: str,
        is_error: bool,
    ) -> None:
        return None

    def finalize(self, result: Any) -> dict[str, Any]:
        return {
            "schema": "gt.treatment_receipt.v1",
            "treatment": self.treatment_id,
            "provider_calls": 0,
            "treatment_provider_calls": 0,
            "graph_available": False,
            "graph_status": "NOT_APPLICABLE",
            "delivery_count": 0,
            "delivery_calls": [],
            "evidence_items_delivered": 0,
            "graph_query_count": 0,
            "action_count": 0,
            "degraded_reasons": [],
            "errors": [],
        }


@dataclass(slots=True)
class GroundTruthTreatment(BareTreatment):
    root: str | Path = "."
    state_dir: str | Path | None = None
    start_char_budget: int = 12_000
    update_char_budget: int = 4_000
    treatment_id: str = field(default="groundtruth", init=False)
    service: RepositoryGraphService = field(init=False, repr=False)
    task: str = field(default="", init=False)
    delivery_count: int = field(default=0, init=False)
    query_count: int = field(default=0, init=False)
    action_count: int = field(default=0, init=False)
    evidence_items_delivered: int = field(default=0, init=False)
    last_source_revision: str = field(default="", init=False)
    delivery_calls: list[int] = field(default_factory=list, init=False)
    errors: list[str] = field(default_factory=list, init=False)
    receipts: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.state_dir is None:
            override = str(os.environ.get("GT_STATE_DIR") or "").strip()
            if override:
                self.state_dir = override
        self.service = RepositoryGraphService(self.root, state_dir=self.state_dir)

    def _context(self, *, limit: int) -> dict[str, Any]:
        composition = compose_repository_context(self.service, self.task, limit=limit)
        self.query_count += int(composition["query_count"])
        for error in composition["query_errors"]:
            self.errors.append(f"context_query_failed:{error}")
        return composition

    def _render(self, *, update: bool, budget: int, delivered_before_call: int) -> str:
        receipt = self.service.status()
        if not receipt.query_ready:
            self.receipts.append(receipt.as_dict())
            self.errors.append(f"graph_not_ready:{receipt.build_status.value}")
            return ""
        try:
            composition = self._context(limit=12 if not update else 6)
            evidence = list(composition["evidence"])
        except Exception as exc:  # noqa: BLE001 - recorded degradation remains non-blocking
            self.errors.append(f"query_failed:{type(exc).__name__}")
            composition = {
                "schema": "gt.graph_context_composition.v1",
                "task_tokens": [],
                "anchor_count": 0,
                "query_count": 0,
                "truncated": False,
                "query_errors": [type(exc).__name__],
            }
            evidence = []
        payload = {
            "schema": "gt.agent_context.v2",
            "kind": "repository_update" if update else "repository_start",
            "repository": receipt.repository,
            "commit_sha": receipt.commit_sha,
            "source_revision": receipt.source_revision,
            "graph_identity": receipt.graph_checksum_or_identity,
            "graph_status": receipt.build_status.value,
            "limitations": list(receipt.degraded_reasons),
            "composition_schema": composition["schema"],
            "task_tokens": composition["task_tokens"],
            "anchor_count": composition["anchor_count"],
            "graph_query_count": composition["query_count"],
            "truncated": composition["truncated"],
            "evidence": evidence,
        }
        def encode() -> str:
            return (
                "<groundtruth-repository-context>\n"
                + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n</groundtruth-repository-context>"
            )

        rendered = encode()
        while payload["evidence"] and len(rendered) > budget:
            payload["evidence"].pop()
            payload["truncated"] = True
            rendered = encode()
        if len(rendered) > budget or not payload["evidence"]:
            if evidence and len(rendered) > budget:
                self.errors.append("context_budget_too_small")
            return ""
        self.delivery_count += bool(evidence)
        if payload["evidence"]:
            self.delivery_calls.append(delivered_before_call)
            self.evidence_items_delivered += len(payload["evidence"])
        self.last_source_revision = receipt.source_revision
        self.receipts.append(receipt.as_dict())
        return rendered

    def prepare(self, task: str) -> str:
        self.task = task
        try:
            receipt = self.service.build()
        except Exception as exc:  # noqa: BLE001 - treatment cannot terminate the agent
            self.errors.append(f"graph_build_failed:{type(exc).__name__}")
            return ""
        self.receipts.append(receipt.as_dict())
        return self._render(
            update=False,
            budget=max(0, self.start_char_budget),
            delivered_before_call=1,
        )

    def before_model_call(self, iteration: int) -> str:
        if iteration <= 1:
            return ""
        observed = self.service.status()
        if observed.build_status is not GraphStatus.STALE:
            return ""
        try:
            rebuilt = self.service.build()
        except Exception as exc:  # noqa: BLE001 - recorded degradation remains non-blocking
            self.errors.append(f"graph_update_failed:{type(exc).__name__}")
            return ""
        self.receipts.append(rebuilt.as_dict())
        if not rebuilt.query_ready:
            return ""
        return self._render(
            update=True,
            budget=max(0, self.update_char_budget),
            delivered_before_call=iteration,
        )

    def after_action(
        self,
        name: str,
        arguments: dict[str, Any],
        output: str,
        is_error: bool,
    ) -> None:
        # Observation only. The action and its output are intentionally immutable.
        self.action_count += 1

    def finalize(self, result: Any) -> dict[str, Any]:
        receipt = self.service.status()
        return {
            "schema": "gt.treatment_receipt.v1",
            "treatment": self.treatment_id,
            "provider_calls": 0,
            "treatment_provider_calls": 0,
            "graph_available": receipt.query_ready,
            "graph_status": receipt.build_status.value,
            "graph_receipt_schema": receipt.receipt_schema,
            "graph_receipt_path": str(self.service.receipt_path),
            "graph_commit_sha": receipt.commit_sha,
            "graph_builder_version": receipt.graph_builder_version,
            "graph_identity": receipt.graph_checksum_or_identity,
            "source_revision": receipt.source_revision,
            "delivery_count": self.delivery_count,
            "delivery_calls": list(self.delivery_calls),
            "evidence_items_delivered": self.evidence_items_delivered,
            "graph_query_count": self.query_count,
            "action_count": self.action_count,
            "degraded_reasons": list(receipt.degraded_reasons),
            "errors": list(dict.fromkeys(self.errors)),
        }


__all__ = ["BareTreatment", "GroundTruthTreatment"]
