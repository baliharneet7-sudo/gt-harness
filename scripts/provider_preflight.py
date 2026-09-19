"""Validate and probe the single versioned provider route without leaking account data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Launched by path (python scripts/<name>.py) the repository root is not on
# sys.path and the shared annotation builder cannot be imported; every
# workflow uses python -m, but the path form must keep working too.
#
# The membership test is not decoration (REVIEW-13 LOW-1). An unconditional
# insert grows sys.path every time anything re-enters this module, and a
# duplicated root shadows a path a caller deliberately prepended. Membership
# rather than ``sys.path[0]``: a root already anywhere on the path resolves
# the import, and moving it to the front would be the change nobody asked for.
if __package__ in (None, ""):
    import sys as _sys

    _REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
    if _REPOSITORY_ROOT not in _sys.path:
        _sys.path.insert(0, _REPOSITORY_ROOT)

from scripts.gh_annotations import gh_command

_SCHEMA = "gt.provider_route.v1"
_SHA40 = re.compile(r"[0-9a-f]{40}")
_REQUIRED_KEYS = {
    "schema",
    "route_id",
    "provider",
    "base_url",
    "model",
    "provider_routing",
    "requested_output_tokens",
    "credential_env",
    "credential_source_id",
    "availability",
    # Declared cohort pacing for the parallel dispatch: ordinal dispatch
    # stagger, per-attempt jitter bound, Retry-After cap, and the retry
    # attempt budget Mini-SWE's loop enforces. Attested in the run plan.
    "retry_pacing",
}
# Optional, absent from the older manifests that are still loaded by name:
# - pricing: pins the per-token price the funds estimate uses instead of the
#   OpenRouter catalog, for a route whose published price is known to drift.
# - expected_quantization: the served numeric format this route is certified
#   at. The frozen GT-off baseline ran DeepSeek's own fp8 deployment
#   (fingerprint fp_a18b46594c_prod0820_fp8_kvcache_20260402) while a GT-on
#   run reached a relace/fp4 endpoint under the identical model name and
#   scored 0/20 against 17/20, so the name alone is not the identity.
_OPTIONAL_KEYS = {"pricing", "expected_quantization"}
_PRICING_KEYS = {"prompt_usd_per_token", "completion_usd_per_token"}
_PACING_KEYS = {
    "dispatch_stagger_seconds",
    "retry_jitter_max_seconds",
    "retry_after_cap_seconds",
    "model_retry_attempts",
}
# Numeric formats we can read out of an OpenRouter endpoint tag
# ("deepinfra/fp8", "relace/fp4"). Anything else stays "unknown", which never
# trips the mismatch gate: an unreadable tag is not evidence of drift.
_KNOWN_QUANTIZATIONS = frozenset({"fp4", "fp8", "int8", "bf16"})

# Funds-estimate defaults, deliberately pessimistic. Observed TB2 usage on
# deepseek-v4-flash-0731 was 17.5M input / 145K output tokens per task (run
# 35296600960); a lighter task ran 4.4M / 80K. We default to the heavy
# observation because the failure we are gating is run 35383113823, where a
# key that held *some* credit passed `key_limit_available` and then lost three
# of four tasks to "This request requires more credits, or fewer max_tokens".
# expected_tasks defaults to 1 - the least a live run can spend - because the
# preflight cannot see the matrix; callers that know the cohort size pass
# --expected-tasks (or GT_PREFLIGHT_EXPECTED_TASKS) and get the real bound.
_DEFAULT_EXPECTED_TASKS = 1
_DEFAULT_TOKENS_IN_PER_TASK = 17_500_000
_DEFAULT_TOKENS_OUT_PER_TASK = 145_000
# Headroom for retries and for the concurrent in-flight reservation OpenRouter
# holds against the balance ("would exceed your available credits given your
# current in-flight requests", run 35383113823).
_DEFAULT_SAFETY_FACTOR = 1.25

# Authorized (model -> provider_routing) pairs. The route file selects ONE of
# these identities; a silent swap to an arbitrary model or provider fails
# here, which is the control property the hardcoded pin existed for.
#
# - deepseek-v4-flash-0731/relace: the HAR-83 benchmark route (the only model
#   whose results may be cited against the frozen GT-off baselines).
# - stealth/union-alpha/stealth: functional-verification route only. A $0
#   preview model served by OpenRouter's anonymous Stealth provider -
#   "does the machinery work" runs, never comparison evidence: the provider
#   is unnamed, the preview can be delisted, and its numbers cannot join a
#   matched cohort.
_AUTHORIZED_ROUTES = {
    "deepseek/deepseek-v4-flash-0731": {
        "only": ["deepinfra"],
        "allow_fallbacks": False,
        "require_parameters": True,
    },
    "stealth/union-alpha": {
        "only": ["stealth"],
        "allow_fallbacks": False,
        "require_parameters": True,
    },
    # union-alpha's stealth preview ended on 2026-09-17 and OpenRouter now
    # serves the same deployment under its revealed name. The provider tag is
    # "unbiased", not "stealth": routing it to the retired tag 404s.
    "unbiased/pareto": {
        "only": ["unbiased"],
        "allow_fallbacks": False,
        "require_parameters": True,
    },
    # Contributor tier, served by Meta's own endpoint (provider tag "meta").
    "meta/muse-spark-1.2-contributor": {
        "only": ["meta"],
        "allow_fallbacks": False,
        "require_parameters": True,
    },
}


class ProviderPreflightError(RuntimeError):
    """A closed provider failure carrying only non-sensitive progress metadata."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        # Whatever the probe had observed when it closed, so the receipt still
        # says how far the gate got and why it stopped.
        self.observation: dict[str, Any] | None = None


@dataclass(frozen=True)
class FundsBudget:
    """The cost model the run is priced against, before any task is dispatched."""

    expected_tasks: int = _DEFAULT_EXPECTED_TASKS
    tokens_in_per_task: int = _DEFAULT_TOKENS_IN_PER_TASK
    tokens_out_per_task: int = _DEFAULT_TOKENS_OUT_PER_TASK
    safety_factor: float = _DEFAULT_SAFETY_FACTOR

    @classmethod
    def resolve(
        cls,
        *,
        expected_tasks: int | None = None,
        tokens_in_per_task: int | None = None,
        tokens_out_per_task: int | None = None,
        safety_factor: float | None = None,
    ) -> FundsBudget:
        """Explicit argument wins, then the environment, then the default."""
        return cls(
            expected_tasks=_positive_int(
                expected_tasks, "GT_PREFLIGHT_EXPECTED_TASKS", _DEFAULT_EXPECTED_TASKS
            ),
            tokens_in_per_task=_positive_int(
                tokens_in_per_task,
                "GT_PREFLIGHT_TOKENS_IN_PER_TASK",
                _DEFAULT_TOKENS_IN_PER_TASK,
            ),
            tokens_out_per_task=_positive_int(
                tokens_out_per_task,
                "GT_PREFLIGHT_TOKENS_OUT_PER_TASK",
                _DEFAULT_TOKENS_OUT_PER_TASK,
            ),
            safety_factor=_positive_float(
                safety_factor, "GT_PREFLIGHT_SAFETY_FACTOR", _DEFAULT_SAFETY_FACTOR
            ),
        )


def _positive_int(value: int | None, env_name: str, default: int) -> int:
    if value is None:
        raw = os.environ.get(env_name, "").strip()
        if raw:
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError("provider_funds_budget_invalid") from exc
        else:
            value = default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("provider_funds_budget_invalid")
    return value


def _positive_float(value: float | None, env_name: str, default: float) -> float:
    if value is None:
        raw = os.environ.get(env_name, "").strip()
        if raw:
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError("provider_funds_budget_invalid") from exc
        else:
            value = default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("provider_funds_budget_invalid")
    return float(value)


def _number(value: Any) -> float | None:
    """OpenRouter reports credit as JSON numbers and prices as decimal strings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def load_route(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    route = json.loads(raw)
    if (
        not isinstance(route, dict)
        or not _REQUIRED_KEYS <= set(route)
        or not set(route) <= (_REQUIRED_KEYS | _OPTIONAL_KEYS)
    ):
        raise ValueError("provider_route_shape_invalid")
    if route["schema"] != _SCHEMA or route["provider"] != "openrouter":
        raise ValueError("provider_route_identity_invalid")
    if route["base_url"] != "https://openrouter.ai/api/v1":
        raise ValueError("provider_base_url_not_allowed")
    authorized_routing = _AUTHORIZED_ROUTES.get(route["model"])
    if authorized_routing is None:
        raise ValueError("provider_model_not_allowed")
    if route["provider_routing"] != authorized_routing:
        raise ValueError("provider_routing_not_allowed")
    if route["credential_env"] != "OPENROUTER_API_KEY":
        raise ValueError("provider_credential_env_not_allowed")
    requested_output = route["requested_output_tokens"]
    if (
        isinstance(requested_output, bool)
        or not isinstance(requested_output, int)
        or requested_output < 1
    ):
        raise ValueError("provider_output_reservation_invalid")
    availability = route["availability"]
    if availability != {
        "key_path": "/key",
        "models_path": "/models",
        "inference_path": "/chat/completions",
        "require_positive_key_limit_when_present": True,
    }:
        raise ValueError("provider_availability_contract_invalid")
    pacing = route["retry_pacing"]
    if not isinstance(pacing, dict) or set(pacing) != _PACING_KEYS:
        raise ValueError("provider_retry_pacing_invalid")
    if (
        isinstance(pacing["dispatch_stagger_seconds"], bool)
        or not isinstance(pacing["dispatch_stagger_seconds"], int)
        or pacing["dispatch_stagger_seconds"] < 0
        or isinstance(pacing["retry_jitter_max_seconds"], bool)
        or not isinstance(pacing["retry_jitter_max_seconds"], (int, float))
        or pacing["retry_jitter_max_seconds"] < 0
        or isinstance(pacing["retry_after_cap_seconds"], bool)
        or not isinstance(pacing["retry_after_cap_seconds"], (int, float))
        or pacing["retry_after_cap_seconds"] <= 0
        or isinstance(pacing["model_retry_attempts"], bool)
        or not isinstance(pacing["model_retry_attempts"], int)
        or not 1 <= pacing["model_retry_attempts"] <= 30
    ):
        raise ValueError("provider_retry_pacing_invalid")
    pricing = route.get("pricing")
    if pricing is not None:
        if not isinstance(pricing, dict) or set(pricing) != _PRICING_KEYS:
            raise ValueError("provider_pricing_block_invalid")
        for value in pricing.values():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            ):
                raise ValueError("provider_pricing_block_invalid")
    quantization = route.get("expected_quantization")
    if quantization is not None and quantization not in _KNOWN_QUANTIZATIONS:
        raise ValueError("provider_expected_quantization_invalid")
    return route, hashlib.sha256(raw).hexdigest()


def _get_json(url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        code = {
            401: "provider_credential_rejected",
            402: "provider_billing_failure",
            429: "provider_rate_limited",
        }.get(exc.code, "provider_preflight_http_failed")
        if code == "provider_preflight_http_failed":
            code = f"provider_preflight_http_{exc.code}"
        raise ProviderPreflightError(code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderPreflightError("provider_preflight_transport_failed") from exc
    if not isinstance(payload, dict):
        raise ProviderPreflightError("provider_preflight_response_invalid")
    return payload


def _post_json(url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
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
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        code = {
            401: "provider_credential_rejected",
            402: "provider_billing_failure",
            429: "provider_rate_limited",
        }.get(exc.code, "provider_canary_http_failed")
        if code == "provider_canary_http_failed":
            code = f"provider_canary_http_{exc.code}"
        raise ProviderPreflightError(code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderPreflightError("provider_canary_transport_failed") from exc
    if not isinstance(payload, dict):
        raise ProviderPreflightError("provider_canary_response_invalid")
    return payload


def _remaining_credit(key_data: dict[str, Any]) -> float | None:
    """Credit the key may still spend, or None when the key is unbounded.

    OpenRouter reports ``limit_remaining`` when a limit exists, and otherwise
    only ``limit``/``usage``; an unlimited key reports ``limit: null``.
    """
    remaining = _number(key_data.get("limit_remaining"))
    if remaining is not None:
        return remaining
    limit = _number(key_data.get("limit"))
    if limit is None:
        return None
    return limit - (_number(key_data.get("usage")) or 0.0)


def _unit_prices(
    route: dict[str, Any], model_row: dict[str, Any]
) -> tuple[float | None, float | None, str | None]:
    """USD per prompt/completion token, pinned by the route or read from the
    same /models row the context window came from."""
    pricing = route.get("pricing")
    if isinstance(pricing, dict):
        return (
            float(pricing["prompt_usd_per_token"]),
            float(pricing["completion_usd_per_token"]),
            "route_manifest:pricing",
        )
    catalog = model_row.get("pricing")
    if isinstance(catalog, dict):
        prompt = _number(catalog.get("prompt"))
        completion = _number(catalog.get("completion"))
        if prompt is not None and completion is not None:
            return prompt, completion, "openrouter:/models"
    return None, None, None


def _empty_funds(budget: FundsBudget) -> dict[str, Any]:
    """The funds block before anything has been priced.

    One definition: the probe, the pre-probe placeholder and the receipt
    builder all start from this shape, so a new field cannot reach the receipt
    through one path and be missing on another.
    """
    return {
        "sufficient": None,
        "verdict": None,
        "reason": None,
        "estimate_usd": None,
        "headroom_bucket": None,
        "expected_tasks": budget.expected_tasks,
        "pricing_source": None,
    }


def _empty_observation(budget: FundsBudget) -> dict[str, Any]:
    """What the probe has recorded before it has observed anything."""
    return {
        "checks": {
            "credential_valid": False,
            "key_limit_available": False,
            "model_visible": False,
            "model_canary_served": False,
        },
        "provider_inference_attempts": 0,
        "context_window_tokens": None,
        "context_window_source": None,
        "funds": _empty_funds(budget),
        "served_endpoint": None,
        "fingerprint_available": False,
    }


# Coarse headroom classes. The receipt is uploaded as a build artifact while
# pinning ``account_amounts_recorded: False``, so it may say how comfortably
# the key covers this run and nothing more. A *number* cannot: `estimate_usd`
# is published at full precision in the same receipt and is deterministic
# (published price x declared token budget x safety factor), so any ratio
# inverts to `available = ratio x estimate` - a two-decimal ratio pinned the
# balance to well under a cent for a thin key, which is exactly the key this
# field describes. A bucket is many-to-one in the balance by construction: the
# receipt is identical for every balance inside a class, which is the property
# tests/test_provider_preflight.py asserts behaviourally.
_HEADROOM_BUCKETS = (
    (1.0, "lt_1x"),
    (3.0, "1x_to_3x"),
    (10.0, "3x_to_10x"),
)
_HEADROOM_TOP_BUCKET = "ge_10x"


def _headroom_bucket(available: float | None, estimate: float | None) -> str | None:
    """Which coarse class the remaining credit falls in against the priced run.

    None when the comparison cannot be made at all: an unbounded key has no
    balance to classify, and a zero estimate (the $0 preview route) has no
    denominator, so neither reports a bucket rather than inventing one.
    """
    if available is None or estimate is None or estimate <= 0:
        return None
    ratio = available / estimate
    for bound, name in _HEADROOM_BUCKETS:
        if ratio < bound:
            return name
    return _HEADROOM_TOP_BUCKET


def _assess_funds(
    route: dict[str, Any],
    key_data: dict[str, Any],
    model_row: dict[str, Any],
    budget: FundsBudget,
) -> dict[str, Any]:
    """Price the whole run and compare it with the credit actually left.

    ``key_limit_available`` only proves the key holds *some* credit; run
    35383113823 cleared it and then died mid-run on per-request credit errors.
    """
    funds = _empty_funds(budget)
    prompt_price, completion_price, source = _unit_prices(route, model_row)
    available = _remaining_credit(key_data)
    if prompt_price is None or completion_price is None:
        # No published price: there is nothing to compare, and refusing here
        # would close the gate on a catalog omission rather than on a real
        # funding gap.
        funds["verdict"] = "pricing_unavailable"
        funds["reason"] = "provider_pricing_unavailable"
        return funds
    funds["pricing_source"] = source
    funds["estimate_usd"] = (
        budget.expected_tasks
        * (
            budget.tokens_in_per_task * prompt_price
            + budget.tokens_out_per_task * completion_price
        )
        * budget.safety_factor
    )
    if available is None:
        # An account-level key reports ``limit: null``: there is no ceiling to
        # price against, so the gate cannot run at all. That is a third
        # verdict, not a pass - the CLI prints it as a warning so a skipped
        # gate never reads as a cleared one.
        funds["verdict"] = "unbounded_key"
        funds["reason"] = "provider_key_limit_unbounded"
        return funds
    funds["sufficient"] = funds["estimate_usd"] <= available
    funds["verdict"] = "sufficient" if funds["sufficient"] else "insufficient"
    funds["headroom_bucket"] = _headroom_bucket(available, funds["estimate_usd"])
    return funds


def _quantization(tag: str | None, declared: Any) -> str:
    """fp8/fp4/bf16/int8 out of an endpoint tag such as "deepinfra/fp8"."""
    for token in re.split(r"[/_\-\s]+", (tag or "").lower()):
        if token in _KNOWN_QUANTIZATIONS:
            return token
    if isinstance(declared, str) and declared.strip().lower() in _KNOWN_QUANTIZATIONS:
        return declared.strip().lower()
    return "unknown"


def _row_provider_slugs(row: dict[str, Any]) -> set[str]:
    """Tags carry the provider slug before the "/" ("deepinfra/fp8"), and a
    provider with a single deployment is tagged with the bare slug."""
    return {
        str(candidate).split("/", 1)[0].strip().lower()
        for candidate in (
            row.get("tag"),
            row.get("provider_slug"),
            row.get("provider_name"),
        )
        if isinstance(candidate, str) and candidate.strip()
    }


def _endpoint_identity(row: dict[str, Any], pinned: str) -> dict[str, Any]:
    """The served deployment's identity, as far as the listing declares it."""
    tag = row.get("tag") if isinstance(row.get("tag"), str) else None
    context_length = row.get("context_length")
    prices = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
    return {
        "provider": pinned,
        "tag": tag,
        "quantization": _quantization(tag, row.get("quantization")),
        "context_length": (
            context_length
            if isinstance(context_length, int) and not isinstance(context_length, bool)
            else None
        ),
        "prompt_price": _number(prices.get("prompt")),
        "completion_price": _number(prices.get("completion")),
    }


def _served_endpoint(
    base: str, api_key: str, route: dict[str, Any]
) -> dict[str, Any] | None:
    """The endpoint the pinned provider slug actually resolves to.

    OpenRouter answers the canary with ``system_fingerprint: null``, so the
    only machine-readable identity beyond the model name is this listing.
    A failed or unparsable listing records nothing and fails nothing: the
    quantization gate fires on a positive observation, never on its absence.
    """
    only = route["provider_routing"]["only"]
    pinned = str(only[0]).strip().lower()
    # The listing hangs off the same catalog path the rest of the probe reads,
    # rather than a second hardcoded copy of it. ``safe="/"`` is deliberate:
    # the model id is a two-segment path ("deepseek/deepseek-v4-flash-0731")
    # that OpenRouter routes as :author/:slug, so the separator must survive
    # while anything else in a vendor slug is percent-encoded.
    models_path = str(route["availability"]["models_path"])
    model_path = urllib.parse.quote(str(route["model"]), safe="/")
    try:
        payload = _get_json(f"{base}{models_path}/{model_path}/endpoints", api_key)
    except ProviderPreflightError:
        return None
    data = payload.get("data")
    rows = data.get("endpoints") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and pinned in _row_provider_slugs(row):
            return _endpoint_identity(row, pinned)
    return None


def _probe_key(
    base: str, availability: dict[str, Any], api_key: str, checks: dict[str, bool]
) -> dict[str, Any]:
    """The key's own status row: a credential the provider accepts, holding a
    limit that is not already spent."""
    key_payload = _get_json(base + availability["key_path"], api_key)
    key_data = key_payload.get("data")
    if not isinstance(key_data, dict):
        raise ProviderPreflightError("provider_key_status_invalid")
    checks["credential_valid"] = True
    remaining = key_data.get("limit_remaining")
    if remaining is not None and (
        isinstance(remaining, bool)
        or not isinstance(remaining, (int, float))
        or remaining <= 0
    ):
        raise ProviderPreflightError("provider_key_cannot_fund_run")
    checks["key_limit_available"] = True
    return key_data


def _probe_model_row(
    base: str,
    availability: dict[str, Any],
    api_key: str,
    route: dict[str, Any],
    checks: dict[str, bool],
) -> dict[str, Any]:
    """Exactly one catalog row for the pinned model id, or nothing."""
    models_payload = _get_json(base + availability["models_path"], api_key)
    models = models_payload.get("data")
    matching = [
        row
        for row in models if isinstance(row, dict) and row.get("id") == route["model"]
    ] if isinstance(models, list) else []
    if len(matching) != 1:
        raise ProviderPreflightError("provider_model_unavailable")
    checks["model_visible"] = True
    return matching[0]


def _admitted_context_window(model_row: dict[str, Any], route: dict[str, Any]) -> int:
    """The catalog window, refused unless it can seat the output reservation
    the run will ask for on every turn."""
    candidate_window = model_row.get("context_length")
    top_provider = model_row.get("top_provider")
    top_provider = top_provider if isinstance(top_provider, dict) else {}
    max_completion = top_provider.get("max_completion_tokens")
    requested_output = int(route["requested_output_tokens"])
    if (
        isinstance(candidate_window, bool)
        or not isinstance(candidate_window, int)
        or candidate_window <= requested_output
    ):
        raise ProviderPreflightError("provider_context_window_unavailable")
    if max_completion is not None and (
        isinstance(max_completion, bool)
        or not isinstance(max_completion, int)
        or max_completion < requested_output
    ):
        raise ProviderPreflightError("provider_output_reservation_unsupported")
    return candidate_window


def _refuse_quantization_drift(
    route: dict[str, Any], served: dict[str, Any] | None
) -> None:
    """Same model name, different numeric format: the fp4 endpoint scored 0/20
    where the fp8 baseline scored 17/20."""
    expected_quantization = route.get("expected_quantization")
    if (
        expected_quantization is not None
        and served is not None
        and served["quantization"] != "unknown"
        and served["quantization"] != expected_quantization
    ):
        raise ProviderPreflightError("provider_quantization_mismatch")


def _probe_canary(
    base: str, availability: dict[str, Any], api_key: str, route: dict[str, Any]
) -> dict[str, Any]:
    """The one paid request of the preflight: prove the pinned route serves."""
    canary = _post_json(
        base + availability["inference_path"],
        api_key,
        {
            "model": route["model"],
            "messages": [{"role": "user", "content": "Reply OK."}],
            # OpenRouter's Relace endpoint advertises the OpenAI-compatible
            # request parameter ``max_tokens``. Using the catalog metadata
            # field name (``max_completion_tokens``) here makes
            # require_parameters=true reject the otherwise valid endpoint.
            "max_tokens": 16,
            "temperature": 0,
            "provider": route["provider_routing"],
        },
    )
    if not isinstance(canary.get("choices"), list) or not canary["choices"]:
        raise ProviderPreflightError("provider_canary_response_invalid")
    return canary


def probe(
    route: dict[str, Any], api_key: str, budget: FundsBudget | None = None
) -> dict[str, Any]:
    budget = budget or FundsBudget.resolve()
    observation = _empty_observation(budget)
    checks: dict[str, bool] = observation["checks"]
    if not api_key:
        raise ProviderPreflightError("provider_credential_missing")
    base = str(route["base_url"]).rstrip("/")
    availability = route["availability"]
    try:
        key_data = _probe_key(base, availability, api_key, checks)
        model_row = _probe_model_row(base, availability, api_key, route, checks)
        observation["context_window_tokens"] = _admitted_context_window(
            model_row, route
        )
        observation["context_window_source"] = "openrouter:/models"
        funds = _assess_funds(route, key_data, model_row, budget)
        observation["funds"] = funds
        if funds["sufficient"] is False:
            raise ProviderPreflightError("provider_funds_insufficient")
        observation["served_endpoint"] = _served_endpoint(base, api_key, route)
        _refuse_quantization_drift(route, observation["served_endpoint"])
        observation["provider_inference_attempts"] = 1
        canary = _probe_canary(base, availability, api_key, route)
        checks["model_canary_served"] = True
        # OpenRouter answers with system_fingerprint: null, which is why the
        # fp8/fp4 swap was invisible to a name-only identity check. Recorded so
        # the receipt says whether the stronger signal existed at all.
        observation["fingerprint_available"] = bool(canary.get("system_fingerprint"))
    except ProviderPreflightError as exc:
        exc.observation = dict(observation, checks=dict(checks))
        raise
    return observation


def _funds_fields(funds: dict[str, Any]) -> dict[str, Any]:
    """The pre-spend funds verdict, as receipt fields.

    Kept out of `checks` on purpose: scripts/attest_deepswe.py pins that dict
    to exactly the four gate keys, and `funds_sufficient` is tri-state - null
    means the key declares no limit, which is not a failure.
    """
    return {
        "funds_sufficient": funds.get("sufficient"),
        # sufficient | insufficient | unbounded_key | pricing_unavailable, so a
        # gate that could not run is distinguishable from one that cleared.
        "funds_verdict": funds.get("verdict"),
        "funds_reason": funds.get("reason"),
        "estimate_usd": funds.get("estimate_usd"),
        # A coarse class, not the credit and not a ratio: see _headroom_bucket.
        "funds_headroom_bucket": funds.get("headroom_bucket"),
        "expected_tasks": funds.get("expected_tasks"),
        "pricing_source": funds.get("pricing_source"),
    }


def _build_receipt(
    *,
    route: dict[str, Any],
    digest: str,
    source_sha: str,
    live: bool,
    error_code: str | None,
    observation: dict[str, Any],
    budget: FundsBudget,
) -> dict[str, Any]:
    """The whole gate verdict, in the exact field set scripts/attest_deepswe.py
    admits. A failed probe hands back whatever it had observed, so read the
    funds block defensively rather than assuming the full shape."""
    funds = observation.get("funds") or _empty_funds(budget)
    return {
        "schema": "gt.provider_preflight.v1",
        "status": "FAIL" if error_code else "PASS",
        "error_code": error_code,
        "mode": "live" if live else "provider_free",
        "source_sha": source_sha,
        "route_id": route["route_id"],
        "provider": route["provider"],
        "base_url": route["base_url"],
        "model": route["model"],
        "provider_routing": route["provider_routing"],
        "route_sha256": digest,
        "checks": observation["checks"],
        "provider_ready": live and error_code is None,
        "paid_run_approved": live,
        # Truthful: the receipt carries a price estimate and a coarse headroom
        # class, and no figure the account holds.
        "account_amounts_recorded": False,
        "provider_inference_attempts": observation["provider_inference_attempts"],
        "provider_inference_calls": int(live and error_code is None),
        "context_window_tokens": observation["context_window_tokens"],
        "reserved_output_tokens": int(route["requested_output_tokens"]),
        "context_window_source": observation["context_window_source"],
        **_funds_fields(funds),
        # Served-model identity beyond the name (fp8 baseline vs fp4 GT-on run).
        "served_endpoint": observation["served_endpoint"],
        "fingerprint_available": observation["fingerprint_available"],
    }


def _write_receipt(output: Path, receipt: dict[str, Any]) -> None:
    """Replace atomically: a half-written gate must never be read as a verdict."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, output)


def run(
    *,
    manifest: Path,
    output: Path,
    source_sha: str,
    live: bool,
    expected_tasks: int | None = None,
    tokens_in_per_task: int | None = None,
    tokens_out_per_task: int | None = None,
    safety_factor: float | None = None,
) -> dict[str, Any]:
    if not _SHA40.fullmatch(source_sha):
        raise ValueError("provider_preflight_source_sha_invalid")
    route, digest = load_route(manifest)
    budget = FundsBudget.resolve(
        expected_tasks=expected_tasks,
        tokens_in_per_task=tokens_in_per_task,
        tokens_out_per_task=tokens_out_per_task,
        safety_factor=safety_factor,
    )
    error_code = None
    observation = _empty_observation(budget)
    if live:
        try:
            observation = probe(
                route, os.environ.get(str(route["credential_env"]), ""), budget
            )
        except ProviderPreflightError as exc:
            error_code = str(exc)
            observation = exc.observation or observation
    receipt = _build_receipt(
        route=route,
        digest=digest,
        source_sha=source_sha,
        live=live,
        error_code=error_code,
        observation=observation,
        budget=budget,
    )
    _write_receipt(output, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--live", action="store_true")
    # Funds-estimate inputs. Each falls back to GT_PREFLIGHT_<NAME> and then to
    # the documented default above; pass --expected-tasks with the real cohort
    # size, since the preflight cannot see the matrix.
    parser.add_argument("--expected-tasks", type=int, default=None)
    parser.add_argument("--tokens-in-per-task", type=int, default=None)
    parser.add_argument("--tokens-out-per-task", type=int, default=None)
    parser.add_argument("--safety-factor", type=float, default=None)
    args = parser.parse_args()
    receipt = run(
        manifest=args.manifest,
        output=args.output,
        source_sha=args.source_sha,
        live=args.live,
        expected_tasks=args.expected_tasks,
        tokens_in_per_task=args.tokens_in_per_task,
        tokens_out_per_task=args.tokens_out_per_task,
        safety_factor=args.safety_factor,
    )
    print(json.dumps(receipt, sort_keys=True))
    if receipt["mode"] == "live" and receipt["funds_verdict"] != "sufficient":
        # An unbounded key or an unpriced model skips the funds gate while the
        # status stays PASS. Annotate the run so the skip is visible in the job
        # log instead of reading as a cleared gate.
        # REVIEW-13 MEDIUM-2. The two interpolated fields are a closed
        # vocabulary this module computes, so this was not exploitable - but
        # it was an unescaped ``::`` line built by hand, which is the shape
        # the repository-wide guard exists to refuse. One builder, one place
        # that knows the command syntax; the fields are bounded and escaped
        # so a future funds_reason read off a provider response cannot end
        # the line and start a second command.
        print(
            gh_command(
                "warning",
                "Provider funds",
                "provider funds gate not cleared: "
                f"verdict={receipt['funds_verdict'] or 'unassessed'} "
                f"reason={receipt['funds_reason'] or 'none'}",
            )
        )
    return int(receipt["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
