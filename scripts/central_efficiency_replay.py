#!/usr/bin/env python3
"""Replay archived receipts through outcome-preserving GT policy boundaries."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.gt_central_agent import MiniSweCentralAgent, _provider_request_receipt
from gt_engine.central_runtime import (
    ValidationAuthority,
    classify_validation_command,
    explicit_check_commands,
)
from gt_engine.provider_view import (
    RequestBudget,
    provider_compaction_required,
    provider_request_budget,
)

_FAILURE_FEATURES = frozenset({"covering_red", "submit_refusal", "GT_SS_SUBMIT_RED"})


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _task_name(trajectory_path: Path) -> str:
    trial = trajectory_path.parent.parent.name
    return trial.split("__", 1)[0]


def _request_budget(row: dict[str, Any]) -> RequestBudget | None:
    payload = dict(row.get("request_budget") or {})
    payload.pop("within_limit", None)
    required = {
        "context_limit_tokens",
        "counted_tokens",
        "conservative_tokens",
        "effective_tokens",
        "hard_prompt_limit",
        "remaining_tokens",
        "counter_source",
    }
    if not required.issubset(payload):
        return None
    return RequestBudget(**{key: payload[key] for key in required})


def _last_model_request(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    prefix: list[dict[str, Any]] = []
    latest: list[dict[str, Any]] | None = None
    for message in messages:
        if message.get("role") == "assistant":
            latest = list(prefix)
        prefix.append(message)
    return latest


def replay_run(
    root: Path,
    *,
    reserve_tokens: int = 131_072,
    model: Any | None = None,
    model_name: str = "deepseek-v4-flash",
    context_limit_tokens: int = 1_048_576,
    hard_ratio: float = 0.90,
) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    invalid_receipts = 0
    invalid_actions: set[tuple[str, int]] = set()
    declared_preserved = 0
    avoided_partial_execs = 0
    projected_partial_execs = 0
    projected_epochs = 0

    for trajectory_path in sorted(root.rglob("miniswe_trajectory.json")):
        receipt_path = trajectory_path.with_name("central_receipt.json")
        if not receipt_path.exists():
            continue
        task = _task_name(trajectory_path)
        trajectory = _load(trajectory_path)
        receipt = _load(receipt_path)
        messages = list(trajectory.get("messages") or ())
        instruction = next(
            (
                str(message.get("content") or "")
                for message in messages
                if message.get("role") == "user"
            ),
            "",
        )
        checks = explicit_check_commands(instruction)
        validation_log = (receipt.get("features") or {}).get("validation_log") or []
        authority_by_action = {
            int(row.get("action") or 0): classify_validation_command(
                str(row.get("command") or ""), checks
            ).authority
            for row in validation_log
        }
        task_invalid = 0
        task_declared = 0
        for feature_receipt in (receipt.get("features") or {}).get("receipts") or ():
            if (
                not feature_receipt.get("model_visible")
                or feature_receipt.get("boundary") != "test_result"
                or feature_receipt.get("feature_id") not in _FAILURE_FEATURES
            ):
                continue
            action = int(feature_receipt.get("action") or 0)
            if authority_by_action.get(action) is ValidationAuthority.DECLARED:
                task_declared += 1
            else:
                task_invalid += 1
                invalid_actions.add((task, action))
        invalid_receipts += task_invalid
        declared_preserved += task_declared

        metrics = receipt.get("metrics") or {}
        old_completion_execs = int(metrics.get("completion_probe_execs") or 0)
        partial = str(metrics.get("completion_plan_status") or "") != "complete"
        if partial:
            avoided_partial_execs += old_completion_execs
        else:
            projected_partial_execs += 0

        call_contexts = list(receipt.get("model_call_contexts") or ())
        budget_source = "recorded_transformed_request"
        budgets: list[RequestBudget] = []
        last_request = _last_model_request(messages)
        if model is not None and last_request is not None:
            provider_messages, _, _, _ = _provider_request_receipt(model, last_request)
            raw_budget = provider_request_budget(
                provider_messages,
                model_name=model_name,
                context_limit_tokens=context_limit_tokens,
                hard_ratio=hard_ratio,
            )
            # Runtime guidance is injected into a copy rather than the durable
            # trajectory. Inflate the reconstructed final request by the
            # largest archived advisory as a conservative upper bound.
            advisory_reserve = max(
                (int(row.get("runtime_advisory_chars") or 0) for row in call_contexts),
                default=0,
            )
            budgets = [
                RequestBudget(
                    context_limit_tokens=raw_budget.context_limit_tokens,
                    counted_tokens=raw_budget.counted_tokens,
                    conservative_tokens=raw_budget.conservative_tokens + advisory_reserve,
                    effective_tokens=raw_budget.effective_tokens + advisory_reserve,
                    hard_prompt_limit=raw_budget.hard_prompt_limit,
                    remaining_tokens=raw_budget.remaining_tokens - advisory_reserve,
                    counter_source=raw_budget.counter_source + "+advisory_upper_bound",
                )
            ]
            budget_source = "reconstructed_raw_final_provider_request"
        else:
            budgets = [
                budget
                for row in call_contexts
                if (budget := _request_budget(row)) is not None
            ]
        needs_epoch = any(
            provider_compaction_required(budget, reserve_tokens=reserve_tokens)
            for budget in budgets
        )
        projected_epochs += int(needs_epoch)
        tasks[task] = {
            "invalid_visible_failure_receipts": task_invalid,
            "declared_visible_failure_receipts_preserved": task_declared,
            "old_completion_probe_execs": old_completion_execs,
            "projected_completion_probe_execs": 0 if partial else old_completion_execs,
            "minimum_provider_headroom_tokens": min(
                (budget.remaining_tokens for budget in budgets), default=None
            ),
            "provider_budget_evidence": budget_source,
            "projected_compaction_epoch": needs_epoch,
        }

    return {
        "task_count": len(tasks),
        "tasks": tasks,
        "invalid_visible_failure_receipts": invalid_receipts,
        "invalid_visible_failure_actions": len(invalid_actions),
        "declared_visible_failure_receipts_preserved": declared_preserved,
        "avoided_partial_completion_probe_execs": avoided_partial_execs,
        "projected_partial_completion_probe_execs": projected_partial_execs,
        "projected_compaction_epochs": projected_epochs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--reserve-tokens", type=int, default=131_072)
    parser.add_argument("--model-name", default="deepseek-v4-flash")
    parser.add_argument("--context-limit-tokens", type=int, default=1_048_576)
    parser.add_argument("--hard-ratio", type=float, default=0.90)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        model = MiniSweCentralAgent(
            logs_dir=Path(directory), model_name=args.model_name
        )._build_model()
        result = replay_run(
            args.run_root.resolve(),
            reserve_tokens=args.reserve_tokens,
            model=model,
            model_name=args.model_name,
            context_limit_tokens=args.context_limit_tokens,
            hard_ratio=args.hard_ratio,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["task_count"]:
        print("ARCHIVED_EFFICIENCY_REPLAY_EMPTY")
        return 2
    print("ARCHIVED_EFFICIENCY_REPLAY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
