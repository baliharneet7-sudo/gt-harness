"""Run the exact one-call persistent-state bootstrap contract against a provider."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from eval.gt_central_agent import MiniSweCentralAgent
from gt_engine.persistent_execution_state import (
    BootstrapCatalog,
    BootstrapCatalogItem,
    CatalogItemKind,
)


def _catalog() -> BootstrapCatalog:
    return BootstrapCatalog(
        source_revision="bootstrap-canary-source-v1",
        graph_source_revision="bootstrap-canary-source-v1",
        graph_revision="bootstrap-canary-graph-v1",
        items=(
            BootstrapCatalogItem(
                item_id="focus:src/service.py:save_user",
                kind=CatalogItemKind.FOCUS,
                label="save_user at src/service.py",
                path="src/service.py",
                symbol="save_user",
                required=True,
                provenance=("bootstrap_canary",),
            ),
        ),
        complete=True,
    )


async def run_canary(*, model_name: str, timeout_sec: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gt-bootstrap-canary-") as logs_dir:
        agent = MiniSweCentralAgent(logs_dir=Path(logs_dir), model_name=model_name)
        model = agent._build_model()
        selection, receipt = await agent._run_persistent_state_bootstrap(
            model,
            instruction="Select the certified implementation focus.",
            catalog=_catalog(),
            timeout_sec=timeout_sec,
        )
        effective_model = str(
            getattr(getattr(model, "config", None), "model_name", "")
            or getattr(model, "model_name", "")
        )
    result: dict[str, object] = {
        "schema": "gt.persistent_bootstrap_canary.v1",
        "model_requested": model_name,
        "model_effective": effective_model,
        "selection_valid": selection.valid,
        "selection": selection.as_dict(),
        "receipt": receipt,
    }
    return result


def validate_canary(result: dict[str, object]) -> tuple[str, ...]:
    """Fail closed on every bootstrap property needed before task fan-out."""

    receipt = result.get("receipt")
    if not isinstance(receipt, dict):
        return ("receipt_missing",)
    failures: list[str] = []
    identity = receipt.get("response_identity") or {}
    contract = receipt.get("call_contract") or {}
    if result.get("selection_valid") is not True or receipt.get("status") != "selected":
        failures.append("selection_invalid")
    if receipt.get("response_received") is not True:
        failures.append("response_missing")
    if int(receipt.get("logical_calls") or 0) != 1 or int(
        receipt.get("provider_calls") or 0
    ) != 1:
        failures.append("not_exactly_one_call")
    if int(receipt.get("action_executions") or 0) != 0:
        failures.append("bootstrap_action_executed")
    if receipt.get("transport") != "direct_single_provider_call":
        failures.append("transport_not_direct_single_call")
    if "provider_query_marker_error" not in receipt or str(
        receipt.get("provider_query_marker_error") or ""
    ):
        failures.append("provider_query_marker_failed")
    if receipt.get("provider_error"):
        failures.append("provider_error")
    if contract.get("thinking_mode") != "disabled":
        failures.append("thinking_not_disabled")
    if contract.get("forced_tool") != "bash" or contract.get("tool_choice") != (
        "named_function"
    ):
        failures.append("forced_bash_contract_missing")
    if contract.get("num_retries") != 0:
        failures.append("provider_retry_enabled")

    def is_sha256(value: object) -> bool:
        text = str(value or "")
        return len(text) == 64 and all(character in "0123456789abcdef" for character in text)

    if not is_sha256(receipt.get("request_payload_sha256")) or not is_sha256(
        receipt.get("provider_messages_sha256")
    ):
        failures.append("request_hash_missing")
    if int(receipt.get("visible_catalog_count") or 0) <= 0 or not is_sha256(
        receipt.get("visible_catalog_ids_sha256")
    ):
        failures.append("visible_catalog_missing")
    response_model = str(identity.get("model") or "")
    effective_model = str(result.get("model_effective") or "")
    if not response_model:
        failures.append("served_model_missing")
    elif not effective_model or response_model.lower().split("/")[-1] != (
        effective_model.lower().split("/")[-1]
    ):
        failures.append("served_model_mismatch")
    if not str(identity.get("provider") or ""):
        failures.append("provider_identity_missing")
    return tuple(failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("MODEL") or "")
    parser.add_argument("--timeout-sec", type=float, default=45.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.model:
        parser.error("--model or MODEL is required")
    result = asyncio.run(run_canary(model_name=args.model, timeout_sec=args.timeout_sec))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    failures = validate_canary(result)
    if failures:
        print(json.dumps({"canary_failures": failures}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
