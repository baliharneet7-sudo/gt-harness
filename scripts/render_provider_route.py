"""Render a provider route file from launch inputs.

The template (config/provider_route.v1.json) supplies everything that is not a
launch choice: base URL, credential env, availability contract, retry pacing,
output reservation. The model, routing and reasoning effort come from the
launch. The rendered file is what the preflight certifies and the plan
attests by sha256, so a run's route is exactly reproducible from its plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from gt_harness.provider_routing import (
    routing_from_inputs,
    validate_provider_routing,
    validate_reasoning_effort,
)

DEFAULT_TEMPLATE = Path("config/provider_route.v1.json")
_SLUG = re.compile(r"[^a-z0-9]+")
# The quantizations the preflight can read off an endpoint tag; any other
# value stays a routing constraint only, with no post-hoc mismatch gate.
_PREFLIGHT_QUANTIZATIONS = frozenset({"fp4", "fp8", "int8", "bf16"})


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")


def render_route(
    template: dict[str, Any],
    *,
    model: str = "",
    provider_only: str = "",
    quantization: str = "",
    allow_fallbacks: bool = False,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    route = dict(template)
    chosen_model = model.strip() or str(template["model"])
    model_changed = chosen_model != template["model"]
    if provider_only.strip() or quantization.strip():
        routing = routing_from_inputs(
            provider_only=provider_only,
            quantization=quantization,
            allow_fallbacks=allow_fallbacks,
        )
    elif model_changed:
        # The template's endpoint lock names a provider that may not serve the
        # new model; an unstated route for a new model is "OpenRouter chooses".
        routing = {}
    else:
        routing = validate_provider_routing(template["provider_routing"])
    route["model"] = chosen_model
    route["provider_routing"] = routing
    if model_changed:
        # Prices and the expected quantization belong to the template model.
        route.pop("pricing", None)
        route.pop("expected_quantization", None)
    quantizations = routing.get("quantizations") or []
    if len(quantizations) == 1 and quantizations[0] in _PREFLIGHT_QUANTIZATIONS:
        route["expected_quantization"] = quantizations[0]
    elif model_changed or quantization.strip():
        route.pop("expected_quantization", None)
    effort = validate_reasoning_effort(reasoning_effort)
    if effort:
        route["reasoning_effort"] = effort
    else:
        route.pop("reasoning_effort", None)
    identity = json.dumps(
        {"model": chosen_model, "routing": routing, "effort": effort},
        sort_keys=True, separators=(",", ":"),
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    route["route_id"] = f"openrouter-{_slug(chosen_model)}-{suffix}"
    return route


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--model", default="")
    parser.add_argument("--provider-only", default="")
    parser.add_argument("--quantization", default="")
    parser.add_argument("--allow-fallbacks", default="false")
    parser.add_argument("--reasoning-effort", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    template = json.loads(args.template.read_text(encoding="utf-8"))
    route = render_route(
        template,
        model=args.model,
        provider_only=args.provider_only,
        quantization=args.quantization,
        allow_fallbacks=str(args.allow_fallbacks).strip().lower() == "true",
        reasoning_effort=args.reasoning_effort,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(route, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"route_id": route["route_id"], "model": route["model"],
                      "provider_routing": route["provider_routing"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
