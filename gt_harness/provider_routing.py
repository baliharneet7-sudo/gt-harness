"""Launch-time provider routing: any model, structurally validated.

The model and its OpenRouter routing are chosen when a run is launched, never
from a table of permitted models in code. What stays closed is the SHAPE: an
unknown routing key, a malformed provider list or an unknown quantization is
refused by name, so a typo cannot silently widen a route. The exact routing
object used rides in every receipt, which is what makes runs comparable.
"""
from __future__ import annotations

from typing import Any

ROUTING_LIST_KEYS = frozenset({"only", "order", "ignore", "quantizations"})
ROUTING_BOOL_KEYS = frozenset({"allow_fallbacks", "require_parameters"})
ROUTING_STRING_KEYS = frozenset({"sort", "data_collection"})
ROUTING_KEYS = ROUTING_LIST_KEYS | ROUTING_BOOL_KEYS | ROUTING_STRING_KEYS

KNOWN_QUANTIZATIONS = frozenset({
    "int4", "int8", "fp4", "fp6", "fp8", "fp16", "bf16", "fp32", "unknown",
})
REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})
_SORTS = frozenset({"price", "throughput", "latency"})
_DATA_COLLECTION = frozenset({"allow", "deny"})


class ProviderRoutingError(ValueError):
    """A routing object that cannot be sent as-is."""


def validate_provider_routing(routing: Any) -> dict[str, Any]:
    """Return a normalized copy of ``routing`` or raise by name."""
    if routing is None:
        return {}
    if not isinstance(routing, dict):
        raise ProviderRoutingError("provider_routing_shape_invalid")
    unknown = set(routing) - ROUTING_KEYS
    if unknown:
        raise ProviderRoutingError(f"provider_routing_key_unknown:{sorted(unknown)[0]}")
    normalized: dict[str, Any] = {}
    for key, value in routing.items():
        if key in ROUTING_LIST_KEYS:
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                raise ProviderRoutingError(f"provider_routing_list_invalid:{key}")
            if key == "quantizations" and not set(value) <= KNOWN_QUANTIZATIONS:
                raise ProviderRoutingError("provider_routing_quantization_unknown")
            normalized[key] = [item.strip() for item in value]
        elif key in ROUTING_BOOL_KEYS:
            if not isinstance(value, bool):
                raise ProviderRoutingError(f"provider_routing_bool_invalid:{key}")
            normalized[key] = value
        else:
            allowed = _SORTS if key == "sort" else _DATA_COLLECTION
            if value not in allowed:
                raise ProviderRoutingError(f"provider_routing_value_invalid:{key}")
            normalized[key] = value
    return normalized


def routing_from_inputs(
    *,
    provider_only: str = "",
    quantization: str = "",
    allow_fallbacks: bool = False,
) -> dict[str, Any]:
    """Build the routing object from workflow inputs.

    ``provider_only`` is a comma list of OpenRouter provider tags; empty or
    ``none`` means "let OpenRouter choose" (then fallbacks are allowed, since
    pinning nothing and forbidding fallback would be contradictory).
    """
    providers = [
        item.strip() for item in (provider_only or "").split(",")
        if item.strip() and item.strip().lower() != "none"
    ]
    quantizations = [
        item.strip() for item in (quantization or "").split(",")
        if item.strip() and item.strip().lower() != "none"
    ]
    routing: dict[str, Any] = {}
    if providers:
        routing["only"] = providers
        routing["allow_fallbacks"] = bool(allow_fallbacks)
        routing["require_parameters"] = True
    if quantizations:
        routing["quantizations"] = quantizations
    return validate_provider_routing(routing)


def validate_reasoning_effort(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("", "none"):
        return ""
    if text not in REASONING_EFFORTS:
        raise ProviderRoutingError(f"reasoning_effort_invalid:{text}")
    return text


__all__ = [
    "KNOWN_QUANTIZATIONS",
    "ProviderRoutingError",
    "REASONING_EFFORTS",
    "ROUTING_KEYS",
    "routing_from_inputs",
    "validate_provider_routing",
    "validate_reasoning_effort",
]
