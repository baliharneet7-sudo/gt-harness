"""Arm-neutral trajectory metrics and strict GT efficiency gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from gt_engine.central_runtime import is_check_command, is_submit_command, normalize_command

PRIMARY_RESOURCES = (
    "total_tokens",
    "api_calls",
    "actions",
    "assistant_steps",
    "normalized_cost_usd",
)
# Frozen DeepSeek V4 Flash experiment rates per million tokens. Provider cost
# was configured as ignore_errors and is often zero, so this normalized metric
# is the cross-arm comparable resource measure.
PRICE_INPUT_CACHE_HIT = 0.0028
PRICE_INPUT_CACHE_MISS = 0.14
PRICE_OUTPUT = 0.28
_SEARCH = re.compile(r"(?:^|[;&|()\s/])(?:rg|grep|find|ack|ag)(?:$|\s)", re.I)
_READ = re.compile(r"(?:^|[;&|()\s/])(?:cat|head|tail|less|more|nl)(?:$|\s)", re.I)
_EDIT = re.compile(
    r"(?:apply_patch|sed\s+-i|perl\s+-i|python(?:3)?\s+-c|ruby\s+-i|"
    r"\b(?:touch|tee|cp|mv)\b|>>|\becho\b.*>)",
    re.I,
)
_CENSORED = {
    "LimitsExceeded",
    "StepLimitExceeded",
    "CostLimitExceeded",
    "WallTimeExceeded",
    "ModelTimeout",
    "Cancelled",
}


def normalized_token_cost(cache_miss: int, cache_hit: int, output: int) -> float:
    return (
        cache_miss * PRICE_INPUT_CACHE_MISS
        + cache_hit * PRICE_INPUT_CACHE_HIT
        + output * PRICE_OUTPUT
    ) / 1_000_000


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"messages": payload}
    if not isinstance(payload, dict):
        raise ValueError(f"trajectory must be an object or list: {path}")
    return payload


def _returncode(message: dict[str, Any]) -> int | None:
    extra = message.get("extra") or {}
    value = extra.get("returncode")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    match = re.search(r"<returncode>\s*(-?\d+)\s*</returncode>", str(message.get("content") or ""))
    return int(match.group(1)) if match else None


def _category(command: str) -> str:
    if is_submit_command(command):
        return "submit"
    if is_check_command(command):
        return "check"
    if _EDIT.search(command):
        return "edit"
    if _SEARCH.search(command):
        return "search"
    if _READ.search(command):
        return "read"
    return "other"


def _receipt_ladder(receipt: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, int]:
    delivered = referenced = acted = 0
    for row in (receipt.get("features") or {}).get("receipts") or []:
        if not row.get("model_visible") or row.get("decision") != "DELIVERED":
            continue
        delivered += 1
        payload = row.get("payload") or {}
        anchors: list[str] = []
        for key in ("path", "command"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                anchors.append(value.strip())
        for key in ("changed_paths", "blockers"):
            value = payload.get(key)
            if isinstance(value, list):
                anchors.extend(str(item) for item in value if str(item).strip())
        if not anchors:
            continue
        later = [item for item in actions if item["index"] > int(row.get("action") or 0)]
        if any(any(anchor in item["reasoning"] for anchor in anchors) for item in later):
            referenced += 1
        if any(any(anchor in item["command"] for anchor in anchors) for item in later):
            acted += 1
    return {
        "guidance_l1_delivered": delivered,
        "guidance_l2_referenced": referenced,
        "guidance_l3_acted": acted,
    }


def extract_trajectory(
    path: Path,
    *,
    task: str | None = None,
    reward: int | float | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Extract the same resource and behavior metrics from GT-off or GT-on."""
    payload = _load_json(path)
    messages = payload.get("messages") or []
    tool_results: dict[str, list[int | None]] = {}
    for message in messages:
        if message.get("role") == "tool":
            tool_results.setdefault(str(message.get("tool_call_id") or ""), []).append(
                _returncode(message)
            )
    tool_result_cursors: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    command_counts: Counter[str] = Counter()
    action_rows: list[dict[str, Any]] = []
    input_tokens = output_tokens = cache_tokens = cache_miss_tokens = 0
    provider_cost = 0.0
    context_chars_sent = 0
    running_context_chars = 0
    first: dict[str, int | None] = {
        name: None for name in ("search", "read", "edit", "check", "submit")
    }

    for message in messages:
        content = str(message.get("content") or "")
        if message.get("role") != "assistant":
            running_context_chars += len(content)
            continue
        counts["assistant_steps"] += 1
        context_chars_sent += running_context_chars
        extra = message.get("extra") or {}
        usage = (extra.get("response") or {}).get("usage") or {}
        input_tokens += int(usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
        hit = int(
            usage.get("prompt_cache_hit_tokens")
            or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            or 0
        )
        cache_tokens += hit
        cache_miss_tokens += int(usage.get("prompt_cache_miss_tokens") or 0)
        provider_cost += float(extra.get("cost") or 0.0)
        counts["api_calls"] += 1
        actions = extra.get("actions") or []
        if not actions:
            counts["no_action_assistant_steps"] += 1
        reasoning = str(message.get("reasoning_content") or content)
        for action in actions:
            counts["actions"] += 1
            command = str(action.get("command") or action.get("cmd") or "")
            normalized = normalize_command(command)
            category = _category(normalized)
            counts[f"{category}_actions"] += 1
            if category in first and first[category] is None:
                first[category] = counts["actions"]
            command_counts[normalized] += 1
            if command_counts[normalized] > 1:
                counts["repeated_commands"] += 1
            tool_id = str(action.get("tool_call_id") or "")
            cursor = tool_result_cursors[tool_id]
            candidates = tool_results.get(tool_id) or []
            returncode = candidates[cursor] if cursor < len(candidates) else None
            tool_result_cursors[tool_id] += 1
            if returncode is not None:
                counts["successful_actions" if returncode == 0 else "failed_actions"] += 1
            action_rows.append(
                {
                    "index": counts["actions"],
                    "command": command,
                    "reasoning": reasoning,
                    "returncode": returncode,
                }
            )
        running_context_chars += len(content)

    if cache_miss_tokens == 0:
        cache_miss_tokens = max(0, input_tokens - cache_tokens)
    total_tokens = input_tokens + output_tokens
    normalized_cost = normalized_token_cost(cache_miss_tokens, cache_tokens, output_tokens)
    exit_status = str((payload.get("info") or {}).get("exit_status") or "")
    censored = exit_status in _CENSORED
    result: dict[str, Any] = {
        "task": task or path.name.removesuffix("_trajectory.json"),
        "reward": reward,
        "solved": None if reward is None else bool(reward),
        "exit_status": exit_status,
        "censored": censored,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_tokens": cache_tokens,
        "uncached_input_tokens": cache_miss_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_rate": round(cache_tokens / input_tokens, 6) if input_tokens else 0.0,
        "provider_cost_usd": provider_cost,
        "normalized_cost_usd": normalized_cost,
        "normalized_pricing": "deepseek-v4-flash-frozen-2026",
        "context_chars_sent": context_chars_sent,
        "model_output_chars": sum(
            len(str(message.get("content") or ""))
            + len(str(message.get("reasoning_content") or ""))
            for message in messages
            if message.get("role") == "assistant"
        ),
        **counts,
        "steps_to_first_search": first["search"],
        "steps_to_first_read": first["read"],
        "steps_to_first_edit": first["edit"],
        "steps_to_first_check": first["check"],
        "steps_to_submit": first["submit"],
    }
    result["api_calls"] = max(
        result.get("api_calls", 0),
        int(((payload.get("info") or {}).get("model_stats") or {}).get("api_calls") or 0),
    )
    result["wasted_action_proxy"] = (
        result.get("failed_actions", 0)
        + result.get("repeated_commands", 0)
        + result.get("no_action_assistant_steps", 0)
    )
    for key in (
        "api_calls",
        "assistant_steps",
        "actions",
        "successful_actions",
        "failed_actions",
        "search_actions",
        "read_actions",
        "edit_actions",
        "check_actions",
        "submit_actions",
        "other_actions",
        "repeated_commands",
        "no_action_assistant_steps",
    ):
        result.setdefault(key, 0)
    if receipt_path and receipt_path.exists():
        receipt = _load_json(receipt_path)
        feature_summary = receipt.get("features") or {}
        call_contexts = receipt.get("model_call_contexts") or []
        result.update(_receipt_ladder(receipt, action_rows))
        result.update(
            {
                "guidance_events": int(feature_summary.get("guidance_events") or 0),
                "guidance_chars": int(feature_summary.get("guidance_chars") or 0),
                "guidance_candidates": int(feature_summary.get("guidance_candidates") or 0),
                "guidance_suppressed": int(feature_summary.get("guidance_suppressed") or 0),
                "feature_receipts": sum(
                    int(value) for value in (feature_summary.get("produced_counts") or {}).values()
                ),
                "lifecycle": feature_summary.get("lifecycle") or {},
                "runtime_advisory_context_chars": sum(
                    int(item.get("runtime_advisory_chars") or 0) for item in call_contexts
                ),
                "stock_context_chars_from_receipt": sum(
                    int(item.get("stock_context_chars") or 0) for item in call_contexts
                ),
                "max_context_chars_from_receipt": max(
                    (int(item.get("context_chars") or 0) for item in call_contexts), default=0
                ),
            }
        )
    return result


def compare_arms(
    baseline: dict[str, dict[str, Any]], treatment: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Apply solve-preservation, censoring, and per-task Pareto gates."""
    tasks = sorted(set(baseline) & set(treatment))
    rows: dict[str, Any] = {}
    solve_regressions: list[str] = []
    censored_treatment: list[str] = []
    pareto_failures: list[str] = []
    comparable_solved: list[str] = []
    outcomes_complete = True
    for task in tasks:
        before, after = baseline[task], treatment[task]
        b_solved, a_solved = before.get("solved"), after.get("solved")
        if b_solved is None or a_solved is None:
            outcomes_complete = False
        if b_solved is True and a_solved is not True:
            solve_regressions.append(task)
        if after.get("censored"):
            censored_treatment.append(task)
        deltas = {
            metric: float(after.get(metric, 0) or 0) - float(before.get(metric, 0) or 0)
            for metric in PRIMARY_RESOURCES
        }
        pareto = None
        if b_solved is True and a_solved is True:
            comparable_solved.append(task)
            pareto = all(delta <= 0 for delta in deltas.values()) and any(
                delta < 0 for delta in deltas.values()
            )
            if not pareto:
                pareto_failures.append(task)
        rows[task] = {
            "baseline_solved": b_solved,
            "treatment_solved": a_solved,
            "deltas": deltas,
            "strict_pareto": pareto,
        }
    gate_passed = (
        bool(tasks)
        and outcomes_complete
        and not (solve_regressions or censored_treatment or pareto_failures)
        and bool(comparable_solved)
    )
    return {
        "tasks": rows,
        "task_count": len(tasks),
        "outcomes_complete": outcomes_complete,
        "comparable_solved": comparable_solved,
        "solve_regressions": solve_regressions,
        "censored_treatment": censored_treatment,
        "pareto_failures": pareto_failures,
        "gate_passed": gate_passed,
    }


def render_delta_markdown(name: str, comparison: dict[str, Any]) -> str:
    lines = [
        f"# Deep delta: {name}",
        "",
        f"Gate: **{'PASS' if comparison['gate_passed'] else 'FAIL'}**",
        "",
        "Delta is treatment minus baseline; positive resource deltas are regressions.",
        "",
        "| task | outcome | tokens | calls | actions | steps | cost | Pareto |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for task, row in comparison["tasks"].items():
        delta = row["deltas"]
        lines.append(
            f"| {task} | {row['baseline_solved']}→{row['treatment_solved']} "
            f"| {delta['total_tokens']:+,.0f} | {delta['api_calls']:+,.0f} "
            f"| {delta['actions']:+,.0f} | {delta['assistant_steps']:+,.0f} "
            f"| ${delta['normalized_cost_usd']:+.6f} | {row['strict_pareto']} |"
        )
    return "\n".join(lines) + "\n"
