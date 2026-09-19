"""Check that a host serves the baseline model's request surface before a paid run.

The frozen GT-off baselines ran on DeepSeek's own API while it served
DeepSeek-V4-Flash-0731 (fingerprint fp_a18b46594c_prod0820_fp8_kvcache_20260402).
DeepSeek retired that snapshot on 2026-09-10 and serves V4.1 Flash under the
old name, so the same model now has to come from third-party OpenRouter hosts.
A provider label is a claim, not proof. This probe replays reference requests
recorded in the baseline (config/model_identity_refs.v1.json, built by
scripts/extract_model_identity_refs.py) and checks what the host reports.

WHAT A SINGLE-HOST RUN PROVES, AND WHAT IT DOES NOT. The verdict is
CONFORMS / NONCONFORMING / UNRESOLVED, never "identity". The receipt's
``scope`` lists what the run checks, set before any call; ``proven`` equals
``scope`` only when the status is CONFORMS and is empty otherwise. CONFORMS
means:

- ``tokenizer_template_tools``: every replayed request (system + user + the
  bash tool schema) tokenised to exactly the baseline's prompt_tokens, so the
  tokenizer, the chat template and the tool serialisation match;
- ``thinking_on_every_replay``: every replay reported reasoning, as the
  baseline did on 89/89 first calls;
- ``fp8_requested`` (OpenRouter only): the request carried
  ``provider.quantizations`` = the route's expected quantization, with
  fallbacks off and required parameters on.

It does not prove the weights. A different checkpoint that shares the
tokenizer and template (V4.1 Flash plausibly does) passes every one of those
checks. The only weights-level signals here are:

- ``native_fingerprint`` (``api.deepseek.com`` override only): FAIL unless
  every response carries the baseline's ``system_fingerprint``. This is the
  DeepSeek-native control: V4.1 behind the old name should fail it;
- ``--compare``: greedy agreement across independent hosts (below). That is
  evidence, not proof.

Checks and severities (UNKNOWN is never a pass):

- ``tokenizer`` PASS/FAIL/UNKNOWN. ``--count`` refs replayed verbatim at
  temperature 0, max_tokens 64; ``usage.prompt_tokens`` must EQUAL the
  baseline's. Any difference, over or under, is a FAIL naming the task, the
  expected and the observed count. A missing count is UNKNOWN.
- ``thinking`` PASS/FAIL/UNKNOWN. A replay shows reasoning when
  ``usage.completion_tokens_details.reasoning_tokens > 0`` or it carries a
  non-empty ``reasoning``/``reasoning_content``. FAIL if any replay reported
  zero reasoning tokens and no reasoning text; PASS only if every replay
  showed reasoning; UNKNOWN otherwise.
- ``greedy`` DEFERRED here. Each replay records the sha256 of its first
  choice's content and reasoning text (both whitespace-stripped) and its tool
  calls (name and arguments; the random call id is excluded), beside
  ``completion_tokens`` and ``finish_reason``. Ref 0 is sent twice; if the two
  hashes differ the host is not deterministic at temperature 0 and the receipt
  says ``self_consistent: false``. A replay whose content, reasoning text and
  tool calls are all empty is not hashed (``sha256: null``): an empty output
  hashes to the same constant on every host. ``self_consistent`` is null when
  either of the two hashes is null.
- ``caching`` OK/WARNING, informational: ``cached_tokens`` (or
  ``prompt_cache_hit_tokens``) on the repeat of ref 0.
- ``served_identity`` INFO: ``model``, ``system_fingerprint`` and
  OpenRouter's ``provider`` from every response.

``--compare R1 R2 [...]`` compares probe receipts from different hosts; the
comparison and its majority rule live in scripts/model_identity_compare.py.

QUANTIZATION DIVERGENCE FROM provider_preflight. The probe sends
``provider.quantizations: ["fp8"]``, so OpenRouter only routes to endpoints it
lists as fp8. An endpoint OpenRouter lists as ``unknown`` is excluded: the
call fails (typically 404, no endpoints) and the probe is UNRESOLVED, rc 2.
scripts/provider_preflight.py treats an ``unknown`` tag as no evidence of
drift and admits it. So a route can clear the preflight and still be
unprobeable here; that is deliberate (an unknown format is not fp8) and must
be resolved by the operator, not by dropping the filter.

Spend: the planned input (the replayed refs' prompt_tokens plus the repeat) is
computed before any call and refused above ``--max-input-tokens``. Per-call
usage and an estimated cost at the route manifest's price are recorded.

Exit codes: 0 CONFORMS (or AGREES); 1 NONCONFORMING (or DISAGREES), including a
mismatch seen before a later network error; 2 UNRESOLVED (network error, error
body, missing usage, cap exceeded, missing key, invalid input). The receipt
(``gt.model_identity.v1``) is always written. The credential is read from the
environment, sent only in the Authorization header, never printed or persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Launched by path (python scripts/<name>.py) the repository root is not on
# sys.path and the shared annotation builder cannot be imported. Same
# membership-guarded bootstrap as scripts/provider_preflight.py.
if __package__ in (None, ""):
    import sys as _sys

    _REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
    if _REPOSITORY_ROOT not in _sys.path:
        _sys.path.insert(0, _REPOSITORY_ROOT)

from scripts.gh_annotations import gh_command
from scripts.provider_preflight import load_route

SCHEMA = "gt.model_identity.v1"
REFS_SCHEMA = "gt.model_identity_refs.v1"
BASELINE_FINGERPRINT = "fp_a18b46594c_prod0820_fp8_kvcache_20260402"
DEFAULT_COUNT = 5
DEFAULT_MAX_INPUT_TOKENS = 60_000
REPLAY_TEMPERATURE = 0
REPLAY_MAX_TOKENS = 64
REQUEST_TIMEOUT_SECONDS = 120

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
UNRESOLVED = "UNRESOLVED"
# (ok, bad) verdict words; UNRESOLVED is shared with --compare.
PROBE_VERDICTS = ("CONFORMS", "NONCONFORMING")
DOES_NOT_PROVE = ["weights"]

NO_CACHE_MESSAGE = "no prompt caching observed; cost estimates must assume full input price"

# OpenRouter provider slugs are lower-case words ("deepinfra", "streamlake").
_PROVIDER_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
# An override may only send a credential to the host that credential belongs
# to. Without the pairing, ``--base-url`` plus ``--key-env`` would post any
# secret in the environment to any URL.
_NATIVE_HOST = "api.deepseek.com"
_OVERRIDE_HOSTS = {
    _NATIVE_HOST: "DEEPSEEK_API_KEY",
    "openrouter.ai": "OPENROUTER_API_KEY",
}
_ERROR_CODES = {
    401: "provider_credential_rejected",
    402: "provider_billing_failure",
    429: "provider_rate_limited",
}


class ProbeError(RuntimeError):
    """A closed failure code carrying no response body and no credential."""


# --------------------------------------------------------------------------
# transport: the one function that touches the network
# --------------------------------------------------------------------------


def _error_body_code(error: Any) -> str:
    """A 200 whose body is ``{"error": ...}`` is a failure, not a response."""
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        return _ERROR_CODES.get(code, f"provider_error_{code}")
    return "provider_error_body"


def _post_chat(url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ProbeError(_ERROR_CODES.get(exc.code, f"provider_http_{exc.code}")) from exc
    # IncompleteRead and LineTooLong are HTTPException, not OSError.
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ProbeError("provider_transport_failed") from exc
    except ValueError as exc:
        raise ProbeError("provider_response_invalid") from exc
    if not isinstance(payload, dict):
        raise ProbeError("provider_response_invalid")
    if payload.get("error"):
        raise ProbeError(_error_body_code(payload["error"]))
    return payload


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_refs(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict) or doc.get("schema") != REFS_SCHEMA:
        raise ValueError("refs_schema_invalid")
    refs = doc.get("refs")
    if not isinstance(refs, list) or not refs or not isinstance(doc.get("tools"), list):
        raise ValueError("refs_shape_invalid")
    for ref in refs:
        if (
            not isinstance(ref, dict)
            or not isinstance(ref.get("task"), str)
            or (_int(ref.get("prompt_tokens")) or 0) < 1
            or not isinstance(ref.get("messages"), list)
            or not ref["messages"]
        ):
            raise ValueError("refs_shape_invalid")
    return doc


def planned_input_tokens(refs: dict[str, Any], count: int) -> int:
    """Replayed prompts plus the one repeat of ref 0."""
    chosen = refs["refs"][:count]
    return sum(ref["prompt_tokens"] for ref in chosen) + chosen[0]["prompt_tokens"]


def _override_endpoint(args: argparse.Namespace) -> dict[str, Any]:
    if args.provider:
        raise ProbeError("provider_with_override")
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme != "https" or parsed.hostname not in _OVERRIDE_HOSTS:
        raise ProbeError("override_host_not_allowed")
    if _OVERRIDE_HOSTS[parsed.hostname] != args.key_env:
        raise ProbeError("override_key_env_not_allowed")
    return {
        "base_url": args.base_url.rstrip("/"),
        "model": args.model,
        "credential_env": args.key_env,
        "provider_routing": None,
        "override": True,
        "native": parsed.hostname == _NATIVE_HOST,
    }


def _endpoint(route: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Where to send, what to call it, which credential, and how to route."""
    overrides = (args.base_url, args.model, args.key_env)
    if any(overrides) and not all(overrides):
        raise ProbeError("override_incomplete")
    if all(overrides):
        return _override_endpoint(args)
    slug = args.provider or route["provider_routing"]["only"][0]
    if not _PROVIDER_SLUG.fullmatch(slug):
        raise ProbeError("provider_slug_invalid")
    routing: dict[str, Any] = {"only": [slug]}
    # Enforce the served numeric format, not just record it: a relace/fp4
    # endpoint under the identical model name scored 0/20 against 17/20.
    if route.get("expected_quantization"):
        routing["quantizations"] = [route["expected_quantization"]]
    routing.update(allow_fallbacks=False, require_parameters=True)
    return {
        "base_url": str(route["base_url"]).rstrip("/"),
        "model": route["model"],
        "credential_env": route["credential_env"],
        "provider_routing": routing,
        "override": False,
        "native": False,
    }


def _scope(endpoint: dict[str, Any]) -> list[str]:
    """What a CONFORMS verdict would establish; claimed only as ``proven``."""
    scope = ["tokenizer_template_tools", "thinking_on_every_replay"]
    if (endpoint.get("provider_routing") or {}).get("quantizations"):
        scope.append("fp8_requested")
    if endpoint.get("native"):
        scope.append("native_fingerprint_is_baseline")
    return scope


# --------------------------------------------------------------------------
# response reading (provider-written, so defensive)
# --------------------------------------------------------------------------


def _first_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        return _dict(choices[0])
    return {}


def _message(payload: dict[str, Any]) -> dict[str, Any] | None:
    message = _first_choice(payload).get("message")
    return message if isinstance(message, dict) else None


def _reasoning_text(message: dict[str, Any] | None) -> str:
    for key in ("reasoning_content", "reasoning"):
        value = (message or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _greedy_hash(message: dict[str, Any] | None) -> str | None:
    if message is None:
        return None
    calls = []
    tool_calls = message.get("tool_calls")
    for call in tool_calls if isinstance(tool_calls, list) else []:
        function = _dict(_dict(call).get("function"))
        if function:
            calls.append([_str(function.get("name")), _str(function.get("arguments"))])
    content = message.get("content")
    canonical = {
        "content": content.strip() if isinstance(content, str) else "",
        "reasoning": _reasoning_text(message),
        "tool_calls": calls,
    }
    if not any(canonical.values()):
        # Empty everywhere is the same constant on every host: not evidence.
        return None
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _call_record(
    index: int,
    ref: dict[str, Any],
    purpose: str,
    payload: dict[str, Any],
    pricing: dict[str, Any] | None,
) -> dict[str, Any]:
    usage = _dict(payload.get("usage"))
    prompt_details = _dict(usage.get("prompt_tokens_details"))
    cached = _int(prompt_details.get("cached_tokens"))
    if cached is None:
        cached = _int(usage.get("prompt_cache_hit_tokens"))
    prompt_tokens = _int(usage.get("prompt_tokens"))
    completion_tokens = _int(usage.get("completion_tokens"))
    message = _message(payload)
    cost = None
    if pricing and prompt_tokens is not None and completion_tokens is not None:
        cost = (
            prompt_tokens * pricing["prompt_usd_per_token"]
            + completion_tokens * pricing["completion_usd_per_token"]
        )
    reported_cost = usage.get("cost")
    return {
        "index": index,
        "task": ref["task"],
        "purpose": purpose,
        "expected_prompt_tokens": ref["prompt_tokens"],
        "usage_present": bool(usage),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": _int(
            _dict(usage.get("completion_tokens_details")).get("reasoning_tokens")
        ),
        "reasoning_text_present": bool(_reasoning_text(message)),
        "cached_tokens": cached,
        "finish_reason": _str(_first_choice(payload).get("finish_reason")),
        # Strings only: these are set members and receipt fields downstream.
        "model": _str(payload.get("model")),
        "system_fingerprint": _str(payload.get("system_fingerprint")),
        "provider": _str(payload.get("provider")),
        "greedy_sha256": _greedy_hash(message),
        "estimated_cost_usd": cost,
        "reported_cost_usd": (
            reported_cost
            if isinstance(reported_cost, (int, float)) and not isinstance(reported_cost, bool)
            else None
        ),
    }


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def _tokenizer_check(chosen: list[dict[str, Any]], replays: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches, unknown = [], []
    for position, ref in enumerate(chosen):
        got = replays[position]["prompt_tokens"] if position < len(replays) else None
        if got is None:
            unknown.append(ref["task"])
        elif got != ref["prompt_tokens"]:
            mismatches.append({"task": ref["task"], "expected": ref["prompt_tokens"], "got": got})
    if not chosen:
        severity, message = UNKNOWN, "no refs were selected; nothing was compared"
    elif mismatches:
        severity = FAIL
        message = "prompt_tokens differ from the baseline: " + "; ".join(
            f"{m['task']} expected {m['expected']} got {m['got']}" for m in mismatches
        )
    elif unknown:
        severity, message = UNKNOWN, "no prompt_tokens observed for: " + ", ".join(unknown)
    else:
        severity, message = PASS, f"prompt_tokens equal the baseline on all {len(chosen)} refs"
    return {
        "severity": severity,
        "message": message,
        "mismatches": mismatches,
        "unobserved": unknown,
    }


def _thinking_check(count: int, replays: list[dict[str, Any]]) -> dict[str, Any]:
    shown = [r for r in replays if (r["reasoning_tokens"] or 0) > 0 or r["reasoning_text_present"]]
    absent = [
        r["task"] for r in replays if r["reasoning_tokens"] == 0 and not r["reasoning_text_present"]
    ]
    if absent:
        severity = FAIL
        message = (
            "thinking off on " + ", ".join(absent) + "; the baseline reported "
            "reasoning tokens on 89/89 first calls"
        )
    elif count and len(shown) == count:
        severity, message = PASS, f"reasoning observed on all {count} replays"
    else:
        severity, message = UNKNOWN, "reasoning not reported on every replay"
    return {"severity": severity, "message": message, "tasks_without_reasoning": absent}


def _self_consistent(calls: list[dict[str, Any]]) -> bool | None:
    first = next((c for c in calls if c["purpose"] == "replay"), None)
    repeat = next((c for c in calls if c["purpose"] == "cache_repeat"), None)
    if not first or not repeat or not first["greedy_sha256"] or not repeat["greedy_sha256"]:
        return None
    return first["greedy_sha256"] == repeat["greedy_sha256"]


def _caching_check(repeat: dict[str, Any] | None) -> dict[str, Any]:
    cached = repeat["cached_tokens"] if repeat else None
    if cached:
        return {"severity": "OK", "cached_tokens": cached, "message": "prompt caching observed"}
    if repeat is None:
        message = "cache repeat not performed; " + NO_CACHE_MESSAGE
    elif cached is None:
        message = "no cached-token field reported; " + NO_CACHE_MESSAGE
    else:
        message = NO_CACHE_MESSAGE
    return {"severity": "WARNING", "cached_tokens": cached, "message": message}


def _distinct(calls: list[dict[str, Any]], key: str) -> list[Any]:
    return list(dict.fromkeys(c[key] for c in calls))


def _served_identity(calls: list[dict[str, Any]], baseline_fingerprint: Any) -> dict[str, Any]:
    fingerprints = [f for f in _distinct(calls, "system_fingerprint") if f is not None]
    # A missing fingerprint does not match, as in the native_fingerprint check.
    matches = all(c["system_fingerprint"] == baseline_fingerprint for c in calls) if calls else None
    return {
        "severity": "INFO",
        "models": [m for m in _distinct(calls, "model") if m is not None],
        "system_fingerprints": fingerprints,
        "providers": [p for p in _distinct(calls, "provider") if p is not None],
        "baseline_fingerprint": baseline_fingerprint,
        "fingerprint_matches_baseline": matches,
    }


def _native_fingerprint_check(calls: list[dict[str, Any]]) -> dict[str, Any]:
    observed = _distinct(calls, "system_fingerprint")
    if not calls:
        severity = UNKNOWN
    elif observed == [BASELINE_FINGERPRINT]:
        severity = PASS
    else:
        severity = FAIL
    return {
        "severity": severity,
        "expected": BASELINE_FINGERPRINT,
        "observed": observed,
        "message": "every response must carry the baseline's system_fingerprint",
    }


def _checks(
    chosen: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    baseline_fingerprint: Any,
    native: bool,
) -> dict[str, Any]:
    replays = [c for c in calls if c["purpose"] == "replay"]
    repeat = next((c for c in calls if c["purpose"] == "cache_repeat"), None)
    checks = {
        "tokenizer": _tokenizer_check(chosen, replays),
        "thinking": _thinking_check(len(chosen), replays),
        "greedy": {
            "severity": "DEFERRED",
            "message": "decided across hosts by --compare",
            "self_consistent": _self_consistent(calls),
            "hashes": [
                {
                    "task": r["task"],
                    "sha256": r["greedy_sha256"],
                    "completion_tokens": r["completion_tokens"],
                    "finish_reason": r["finish_reason"],
                }
                for r in replays
            ],
        },
        "caching": _caching_check(repeat),
        "served_identity": _served_identity(calls, baseline_fingerprint),
    }
    if native:
        checks["native_fingerprint"] = _native_fingerprint_check(calls)
    return checks


def _verdict(
    checks: dict[str, Any],
    error_code: str | None,
    names: tuple[str, ...],
    words: tuple[str, str],
) -> tuple[str, int]:
    severities = [checks[name]["severity"] for name in names if name in checks]
    if FAIL in severities:
        return words[1], 1
    if error_code or UNKNOWN in severities or not severities:
        return UNRESOLVED, 2
    return words[0], 0


# --------------------------------------------------------------------------
# probe mode
# --------------------------------------------------------------------------


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _send(
    endpoint: dict[str, Any],
    api_key: str,
    chosen: list[dict[str, Any]],
    tools: list[Any],
    pricing: dict[str, Any] | None,
    calls: list[dict[str, Any]],
) -> None:
    """Replay each ref, then repeat ref 0; append a record per completed call."""
    url = endpoint["base_url"] + "/chat/completions"
    plan = [(ref, "replay") for ref in chosen] + [(chosen[0], "cache_repeat")]
    for index, (ref, purpose) in enumerate(plan):
        body: dict[str, Any] = {
            "model": endpoint["model"],
            "messages": ref["messages"],
            "tools": tools,
            "temperature": REPLAY_TEMPERATURE,
            "max_tokens": REPLAY_MAX_TOKENS,
        }
        if endpoint["provider_routing"] is not None:
            body["provider"] = endpoint["provider_routing"]
        payload = _post_chat(url, api_key, body)
        try:
            record = _call_record(index, ref, purpose, payload, pricing)
        except Exception as exc:  # provider-written shape; never a traceback
            raise ProbeError("provider_response_invalid") from exc
        calls.append(record)


def _prepare(args: argparse.Namespace, receipt: dict[str, Any]) -> tuple[Any, ...]:
    """Everything decided before the first call; raises ProbeError to refuse."""
    try:
        route, digest = load_route(args.route)
    except (OSError, ValueError) as exc:
        raise ProbeError("provider_route_invalid") from exc
    receipt.update(route_id=route["route_id"], route_sha256=digest)
    try:
        refs = load_refs(args.refs)
    except (OSError, ValueError) as exc:
        raise ProbeError("refs_invalid") from exc
    receipt.update(baseline_id=refs.get("baseline_id"), served_snapshot=refs.get("served_snapshot"))
    if args.count < 1 or args.count > len(refs["refs"]):
        raise ProbeError("refs_count_exceeds_available")
    endpoint = _endpoint(route, args)
    receipt.update(endpoint, scope=_scope(endpoint))
    pricing = None if endpoint["override"] else route.get("pricing")
    receipt["pricing_source"] = "route_manifest" if pricing else None
    # The manifest's price is its own provider's. Under --provider it is
    # still applied (an estimate beats none) but the receipt says whose.
    receipt["pricing_provider"] = route["provider_routing"]["only"][0] if pricing else None
    planned = planned_input_tokens(refs, args.count)
    receipt["planned_input_tokens"] = planned
    if pricing:
        receipt["planned_cost_usd"] = (
            planned * pricing["prompt_usd_per_token"]
            + (args.count + 1) * REPLAY_MAX_TOKENS * pricing["completion_usd_per_token"]
        )
    if planned > args.max_input_tokens:
        raise ProbeError("spend_cap_exceeded")
    return endpoint, refs, pricing


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "probe",
        "route_path": str(args.route),
        "route_id": None,
        "route_sha256": None,
        "refs_path": str(args.refs),
        "refs_sha256": _sha256(args.refs),
        "count": args.count,
        "max_input_tokens": args.max_input_tokens,
        "planned_input_tokens": None,
        "planned_cost_usd": None,
        "replay_temperature": REPLAY_TEMPERATURE,
        "replay_max_tokens": REPLAY_MAX_TOKENS,
        "base_url": None,
        "model": None,
        "provider_routing": None,
        "override": None,
        "native": None,
        "credential_env": None,
        "pricing_source": None,
        "pricing_provider": None,
        "scope": [],
        "proven": [],
        "does_not_prove": DOES_NOT_PROVE,
        "calls": [],
    }
    calls: list[dict[str, Any]] = receipt["calls"]
    chosen: list[dict[str, Any]] = []
    baseline_fingerprint = None
    error_code: str | None = None
    try:
        endpoint, refs, pricing = _prepare(args, receipt)
        baseline_fingerprint = refs.get("system_fingerprint")
        chosen = refs["refs"][: args.count]
        api_key = os.environ.get(endpoint["credential_env"], "")
        if not api_key:
            raise ProbeError("provider_credential_missing")
        _send(endpoint, api_key, chosen, refs["tools"], pricing, calls)
    except ProbeError as exc:
        error_code = str(exc)
    checks = _checks(chosen, calls, baseline_fingerprint, bool(receipt["native"]))
    names = ("tokenizer", "thinking", "native_fingerprint")
    status, exit_code = _verdict(checks, error_code, names, PROBE_VERDICTS)
    costs = [c["estimated_cost_usd"] for c in calls]
    receipt.update(
        status=status,
        exit_code=exit_code,
        error_code=error_code,
        provider_calls=len(calls),
        self_consistent=checks["greedy"]["self_consistent"],
        proven=receipt["scope"] if exit_code == 0 else [],
        checks=checks,
        totals={
            "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in calls),
            "completion_tokens": sum(c["completion_tokens"] or 0 for c in calls),
            "estimated_cost_usd": (
                sum(costs) if costs and all(c is not None for c in costs) else None
            ),
        },
    )
    return receipt


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _write_receipt(output: Path, receipt: dict[str, Any]) -> None:
    """Replace atomically: a half-written gate must never be read as a verdict."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)


def _annotate(receipt: dict[str, Any]) -> None:
    checks = receipt["checks"]
    summary = {
        "schema": receipt["schema"],
        "mode": receipt["mode"],
        "status": receipt["status"],
        "error_code": receipt["error_code"],
        "does_not_prove": receipt["does_not_prove"],
        "severities": {name: check["severity"] for name, check in checks.items()},
    }
    print(json.dumps(summary, sort_keys=True))
    failed = [
        f"{name}: {check.get('message') or check['severity']}"
        for name, check in checks.items()
        if check["severity"] == FAIL
    ]
    if receipt["exit_code"] == 1:
        print(
            gh_command(
                "error",
                "Model conformance",
                f"model probe {receipt['status']}: " + " | ".join(failed),
            )
        )
    elif receipt["status"] == UNRESOLVED:
        print(
            gh_command(
                "warning",
                "Model conformance",
                f"model probe unresolved: error={receipt['error_code'] or 'none'}",
            )
        )
    caching = checks.get("caching")
    if caching and caching["severity"] == "WARNING" and receipt["provider_calls"]:
        print(gh_command("warning", "Model conformance caching", caching["message"]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--route", type=Path)
    parser.add_argument("--provider")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--key-env")
    parser.add_argument("--refs", type=Path, default=Path("config/model_identity_refs.v1.json"))
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--max-input-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS)
    parser.add_argument("--compare", nargs="+", type=Path, metavar="RECEIPT")
    parser.add_argument("--json", type=Path, required=True, dest="output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.compare is not None:
        # Imported here, not at module load: model_identity_compare imports
        # this module's primitives, so a top-level import would be a cycle.
        from scripts.model_identity_compare import run_compare

        receipt = run_compare(args.compare)
    elif args.route is None:
        parser.error("--route is required unless --compare is given")
    else:
        receipt = run_probe(args)
    _write_receipt(args.output, receipt)
    _annotate(receipt)
    return int(receipt["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
