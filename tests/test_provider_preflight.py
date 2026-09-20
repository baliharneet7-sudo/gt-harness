from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import provider_preflight

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "provider_route.v1.json"


# The paid route since 2026-09-19: StreamLake, chosen on the live identity
# probe (receipts D:/gt_runs/identity_probe_20260919/identity_streamlake.json).
# fp8 is enforced on every request, not just recorded after the fact: a
# relace/fp4 endpoint under the identical model name scored 0/20 vs 17/20.
STREAMLAKE_FP8_ROUTING = {
    "only": ["streamlake"],
    "quantizations": ["fp8"],
    "allow_fallbacks": False,
    "require_parameters": True,
}
PAID_ROUTE_MANIFESTS = (
    "provider_route.v1.json",
    "provider_route_deepseek_v4_flash_0731_fp8.v1.json",
)


def test_paid_route_is_deepseek_streamlake_fp8_only() -> None:
    """The active route: the HAR-83 benchmark model, one provider, fp8 only."""
    for name in PAID_ROUTE_MANIFESTS:
        route, _ = provider_preflight.load_route(ROOT / "config" / name)
        assert route["model"] == "deepseek/deepseek-v4-flash-0731", name
        assert route["provider_routing"] == STREAMLAKE_FP8_ROUTING, name
    assert (
        provider_preflight._AUTHORIZED_ROUTES["deepseek/deepseek-v4-flash-0731"]
        == STREAMLAKE_FP8_ROUTING
    )
    fp8, _ = provider_preflight.load_route(ROOT / "config" / PAID_ROUTE_MANIFESTS[1])
    assert fp8["route_id"] == "openrouter-deepseek-v4-flash-0731-streamlake-fp8-only"


def test_each_authorized_route_identity_loads(tmp_path: Path) -> None:
    """The allowlist is a closed set: deepseek stays authorized for the
    benchmark route; union-alpha is the functional-verification route."""
    base = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for model, routing in provider_preflight._AUTHORIZED_ROUTES.items():
        doc = dict(base, model=model, provider_routing=routing)
        manifest = tmp_path / f"route-{model.split('/')[-1]}.json"
        manifest.write_text(json.dumps(doc), encoding="utf-8")
        route, _ = provider_preflight.load_route(manifest)
        assert route["model"] == model


def test_load_route_refuses_an_unauthorized_model(tmp_path: Path) -> None:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    doc["model"] = "openai/gpt-5"
    manifest = tmp_path / "route.json"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="provider_model_not_allowed"):
        provider_preflight.load_route(manifest)


def test_load_route_refuses_routing_drift(tmp_path: Path) -> None:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    doc["provider_routing"] = {
        "only": ["stealth"],
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    manifest = tmp_path / "route.json"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="provider_routing_not_allowed"):
        provider_preflight.load_route(manifest)


def test_provider_route_is_valid_without_network(tmp_path: Path) -> None:
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="a" * 40,
        live=False,
    )
    assert receipt["status"] == "PASS"
    assert receipt["model"] == "deepseek/deepseek-v4-flash-0731"
    assert receipt["provider_inference_calls"] == 0
    assert receipt["provider_inference_attempts"] == 0
    assert receipt["provider_ready"] is False
    assert receipt["account_amounts_recorded"] is False
    assert receipt["context_window_tokens"] is None
    assert receipt["reserved_output_tokens"] == 16_384


def test_live_preflight_checks_key_limit_and_exact_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")

    def fake_get(url: str, api_key: str) -> dict[str, object]:
        assert api_key == "canary-not-a-real-key"
        if url.endswith("/key"):
            return {"data": {"limit_remaining": 10_000}}
        return {
            "data": [
                {
                    "id": "deepseek/deepseek-v4-flash-0731",
                    "context_length": 1_048_576,
                    "top_provider": {"max_completion_tokens": 32_768},
                }
            ]
        }

    monkeypatch.setattr(provider_preflight, "_get_json", fake_get)
    monkeypatch.setattr(
        provider_preflight,
        "_post_json",
        lambda url, key, body: (
            {"choices": [{"message": {"content": "OK"}}]}
            if url.endswith("/chat/completions")
            and key == "canary-not-a-real-key"
            and body["model"] == "deepseek/deepseek-v4-flash-0731"
            and body["max_tokens"] == 16
            and body["provider"] == STREAMLAKE_FP8_ROUTING
            and "max_completion_tokens" not in body
            else {}
        ),
    )
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="b" * 40,
        live=True,
    )
    assert all(receipt["checks"].values())
    assert receipt["provider_inference_calls"] == 1
    assert receipt["provider_inference_attempts"] == 1
    assert receipt["provider_ready"] is True
    assert receipt["context_window_tokens"] == 1_048_576
    assert receipt["reserved_output_tokens"] == 16_384
    assert receipt["context_window_source"] == "openrouter:/models"
    assert "canary-not-a-real-key" not in json.dumps(receipt)


def test_live_preflight_fails_before_matrix_when_key_cannot_fund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        lambda _url, _key: {"data": {"limit_remaining": 0}},
    )
    route, _ = provider_preflight.load_route(MANIFEST)
    with pytest.raises(RuntimeError, match="provider_key_cannot_fund_run"):
        provider_preflight.probe(route, "canary-not-a-real-key")


def test_live_failure_is_written_as_redacted_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        lambda _url, _key: {"data": {"limit_remaining": 0}},
    )
    output = tmp_path / "receipt.json"
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=output,
        source_sha="c" * 40,
        live=True,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "provider_key_cannot_fund_run"
    assert receipt["provider_inference_calls"] == 0
    assert receipt["provider_inference_attempts"] == 0
    assert "canary-not-a-real-key" not in output.read_text(encoding="utf-8")


def test_canary_http_failure_preserves_completed_checks_and_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")

    def fake_get(url: str, _api_key: str) -> dict[str, object]:
        if url.endswith("/key"):
            return {"data": {"limit_remaining": 10_000}}
        return {
            "data": [
                {
                    "id": "deepseek/deepseek-v4-flash-0731",
                    "context_length": 1_048_576,
                    "top_provider": {"max_completion_tokens": 32_768},
                }
            ]
        }

    monkeypatch.setattr(provider_preflight, "_get_json", fake_get)
    monkeypatch.setattr(
        provider_preflight,
        "_post_json",
        lambda _url, _key, _body: (_ for _ in ()).throw(
            provider_preflight.ProviderPreflightError("provider_canary_http_400")
        ),
    )
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="d" * 40,
        live=True,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "provider_canary_http_400"
    assert receipt["checks"] == {
        "credential_valid": True,
        "key_limit_available": True,
        "model_visible": True,
        "model_canary_served": False,
    }
    assert receipt["provider_inference_attempts"] == 1
    assert receipt["provider_inference_calls"] == 0


def test_live_preflight_fails_when_model_window_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")

    def fake_get(url: str, _api_key: str) -> dict[str, object]:
        if url.endswith("/key"):
            return {"data": {"limit_remaining": 1}}
        return {"data": [{"id": "deepseek/deepseek-v4-flash-0731"}]}

    monkeypatch.setattr(provider_preflight, "_get_json", fake_get)
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="e" * 40,
        live=True,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "provider_context_window_unavailable"
    assert receipt["provider_inference_attempts"] == 0
    assert receipt["context_window_tokens"] is None


# --- funds sufficiency (GAP 1, run 35383113823) and served-model identity (GAP 2) ---
#
# Run 35383113823 passed `key_limit_available` (the key held SOME credit) and
# then lost three of four tasks mid-run to OpenRouter credit errors
# ("You requested up to 16384 tokens, but can only afford 13421"). The probe
# now prices the whole run before spending anything.

MODEL = "deepseek/deepseek-v4-flash-0731"
# OpenRouter serves catalog prices as USD-per-token strings.
CATALOG_PRICING = {"prompt": "0.0000003", "completion": "0.0000012"}
MODEL_ROW = {
    "id": MODEL,
    "context_length": 1_048_576,
    "top_provider": {"max_completion_tokens": 32_768},
    "pricing": CATALOG_PRICING,
}
# Both paid manifests pin OpenRouter's published StreamLake rate for this model,
# so the route block - not the catalog row above - prices every estimate taken
# against MANIFEST.
ROUTE_PROMPT_PRICE = 4.4e-8
ROUTE_COMPLETION_PRICE = 1.32e-7
# 1 task x (17.5M in x 4.4e-8 + 145k out x 1.32e-7) x 1.25 safety = 0.986425.
DEFAULT_ESTIMATE_USD = (
    1 * (17_500_000 * ROUTE_PROMPT_PRICE + 145_000 * ROUTE_COMPLETION_PRICE) * 1.25
)


def _fake_get(
    *,
    key_data: dict[str, object],
    model_row: dict[str, object] | None = None,
    endpoints: list[dict[str, object]] | None = None,
):
    row = MODEL_ROW if model_row is None else model_row

    def fake_get(url: str, _api_key: str) -> dict[str, object]:
        if url.endswith("/key"):
            return {"data": key_data}
        if url.endswith("/endpoints"):
            return {"data": {"id": MODEL, "endpoints": list(endpoints or [])}}
        return {"data": [row]}

    return fake_get


def _fake_post(fingerprint: object = None):
    def fake_post(_url: str, _key: str, _body: dict[str, object]) -> dict[str, object]:
        return {
            "choices": [{"message": {"content": "OK"}}],
            "system_fingerprint": fingerprint,
        }

    return fake_post


def _never_post(_url: str, _key: str, _body: dict[str, object]) -> dict[str, object]:
    raise AssertionError("the canary must not be paid for after a closed failure")


def _manifest_with(tmp_path: Path, name: str, **overrides: object) -> Path:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key, value in overrides.items():
        if value is None:
            doc.pop(key, None)
        else:
            doc[key] = value
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_funds_check_fails_closed_when_credit_cannot_cover_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Run 35383113823: a key with positive-but-tiny credit passed the old gate."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"limit_remaining": 0.05})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _never_post)
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="1" * 40,
        live=True,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "provider_funds_insufficient"
    assert receipt["funds_sufficient"] is False
    assert receipt["funds_verdict"] == "insufficient"
    # 0.05 / 0.986425: the key cannot fund one run.
    assert receipt["funds_headroom_bucket"] == "lt_1x"
    assert receipt["estimate_usd"] == pytest.approx(DEFAULT_ESTIMATE_USD)
    assert receipt["expected_tasks"] == 1
    assert receipt["pricing_source"] == "route_manifest:pricing"
    assert receipt["provider_inference_calls"] == 0
    assert receipt["checks"] == {
        "credential_valid": True,
        "key_limit_available": True,
        "model_visible": True,
        "model_canary_served": False,
    }


def test_funds_check_derives_remaining_credit_from_limit_minus_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(key_data={"limit": 500.0, "usage": 100.25}),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="2" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["funds_sufficient"] is True
    assert receipt["funds_verdict"] == "sufficient"
    assert receipt["funds_reason"] is None
    # 399.75 / 0.986425 is ~405x. The receipt says only "ten runs or more":
    # a number, however rounded, times the published estimate reconstructs the
    # balance, and a bucket boundary is all the gate ever needed.
    assert receipt["funds_headroom_bucket"] == "ge_10x"
    assert receipt["estimate_usd"] == pytest.approx(DEFAULT_ESTIMATE_USD)


def test_funds_check_is_null_for_a_key_with_no_limit_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unlimited key reports no limit: record the gap, do not fail closed."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"usage": 12.5})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="3" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["funds_sufficient"] is None
    # The gate was skipped, not cleared: the verdict says so out loud (H2).
    assert receipt["funds_verdict"] == "unbounded_key"
    assert receipt["funds_reason"] == "provider_key_limit_unbounded"
    assert receipt["funds_headroom_bucket"] is None
    assert receipt["estimate_usd"] == pytest.approx(DEFAULT_ESTIMATE_USD)


def test_funds_check_is_null_when_no_price_is_published(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Neither the route nor the catalog prices this model: nothing to compare."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    manifest = _manifest_with(tmp_path, "route-unpriced.json", pricing=None)
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(
            key_data={"limit_remaining": 0.01},
            model_row={
                "id": MODEL,
                "context_length": 1_048_576,
                "top_provider": {"max_completion_tokens": 32_768},
            },
        ),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    receipt = provider_preflight.run(
        manifest=manifest,
        output=tmp_path / "receipt.json",
        source_sha="4" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["funds_sufficient"] is None
    assert receipt["funds_verdict"] == "pricing_unavailable"
    assert receipt["funds_reason"] == "provider_pricing_unavailable"
    assert receipt["estimate_usd"] is None
    assert receipt["funds_headroom_bucket"] is None
    assert receipt["pricing_source"] is None


def test_funds_inputs_are_overridable_by_flag_and_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setenv("GT_PREFLIGHT_TOKENS_IN_PER_TASK", "4400000")
    monkeypatch.setenv("GT_PREFLIGHT_TOKENS_OUT_PER_TASK", "80000")
    monkeypatch.setenv("GT_PREFLIGHT_SAFETY_FACTOR", "1.0")
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"limit_remaining": 10_000})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="5" * 40,
        live=True,
        expected_tasks=89,
    )
    assert receipt["expected_tasks"] == 89
    assert receipt["estimate_usd"] == pytest.approx(
        89 * (4_400_000 * ROUTE_PROMPT_PRICE + 80_000 * ROUTE_COMPLETION_PRICE)
    )


def test_route_pricing_block_overrides_the_catalog_price(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    manifest = _manifest_with(
        tmp_path,
        "route-priced.json",
        pricing={
            "prompt_usd_per_token": 1e-6,
            "completion_usd_per_token": 2e-6,
        },
    )
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"limit_remaining": 10_000})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    receipt = provider_preflight.run(
        manifest=manifest,
        output=tmp_path / "receipt.json",
        source_sha="6" * 40,
        live=True,
    )
    assert receipt["pricing_source"] == "route_manifest:pricing"
    assert receipt["estimate_usd"] == pytest.approx(
        (17_500_000 * 1e-6 + 145_000 * 2e-6) * 1.25
    )


def test_load_route_refuses_a_malformed_pricing_block(tmp_path: Path) -> None:
    manifest = _manifest_with(
        tmp_path, "route-badprice.json", pricing={"prompt_usd_per_token": 1e-6}
    )
    with pytest.raises(ValueError, match="provider_pricing_block_invalid"):
        provider_preflight.load_route(manifest)


def test_load_route_refuses_an_unknown_expected_quantization(tmp_path: Path) -> None:
    manifest = _manifest_with(
        tmp_path, "route-badquant.json", expected_quantization="fp6"
    )
    with pytest.raises(ValueError, match="provider_expected_quantization_invalid"):
        provider_preflight.load_route(manifest)


def test_both_paid_route_manifests_pin_fp8() -> None:
    """The frozen baseline ran fp8; the GT-on run reached an fp4 endpoint under
    the same model name and scored 0/20 against 17/20."""
    for name in (
        "provider_route.v1.json",
        "provider_route_deepseek_v4_flash_0731_fp8.v1.json",
    ):
        route, _ = provider_preflight.load_route(ROOT / "config" / name)
        assert route["expected_quantization"] == "fp8"


def test_served_endpoint_identity_is_recorded_from_the_endpoints_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(
            key_data={"limit_remaining": 10_000},
            endpoints=[
                {
                    "tag": "relace/fp4",
                    "provider_name": "Relace",
                    "context_length": 262_144,
                    "pricing": {"prompt": "0.0000009", "completion": "0.0000019"},
                },
                {
                    "tag": "streamlake/fp8",
                    "provider_name": "StreamLake",
                    "context_length": 1_024_000,
                    "pricing": CATALOG_PRICING,
                },
            ],
        ),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_a18b46594c"))
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="7" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["served_endpoint"] == {
        "provider": "streamlake",
        "tag": "streamlake/fp8",
        "quantization": "fp8",
        "context_length": 1_024_000,
        "prompt_price": pytest.approx(3e-7),
        "completion_price": pytest.approx(1.2e-6),
    }
    assert receipt["fingerprint_available"] is True


def test_quantization_drift_on_the_pinned_provider_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(
            key_data={"limit_remaining": 10_000},
            endpoints=[{"tag": "streamlake/fp4", "context_length": 1_024_000}],
        ),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _never_post)
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="8" * 40,
        live=True,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "provider_quantization_mismatch"
    assert receipt["served_endpoint"]["quantization"] == "fp4"
    assert receipt["provider_inference_calls"] == 0


def test_unknown_served_quantization_is_recorded_without_failing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bare provider tag carries no quantization: record "unknown", do not
    invent a mismatch."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(
            key_data={"limit_remaining": 10_000},
            endpoints=[{"provider_name": "StreamLake", "context_length": 1_024_000}],
        ),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post(None))
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="9" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["served_endpoint"]["quantization"] == "unknown"
    assert receipt["served_endpoint"]["tag"] is None
    # OpenRouter returns system_fingerprint: null, which is why name-only
    # identity could not tell fp8 from fp4.
    assert receipt["fingerprint_available"] is False


def test_endpoints_listing_that_omits_the_pinned_provider_records_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(
            key_data={"limit_remaining": 10_000},
            endpoints=[{"tag": "relace/fp4"}],
        ),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post(None))
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="0" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["served_endpoint"] is None


def test_receipt_keeps_the_four_gate_checks_and_adds_the_new_fields(
    tmp_path: Path,
) -> None:
    """scripts/attest_deepswe.py pins `checks` to exactly four keys, so the
    funds verdict is a receipt field, not a fifth check."""
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="a" * 40,
        live=False,
    )
    assert set(receipt["checks"]) == {
        "credential_valid",
        "key_limit_available",
        "model_visible",
        "model_canary_served",
    }
    assert {
        "funds_sufficient",
        "funds_verdict",
        "funds_reason",
        "estimate_usd",
        "funds_headroom_bucket",
        "expected_tasks",
        "pricing_source",
        "served_endpoint",
        "fingerprint_available",
    } <= set(receipt)
    assert receipt["funds_sufficient"] is None
    assert receipt["served_endpoint"] is None
    assert receipt["fingerprint_available"] is False


# --- round 2/3: the balance stays on the runner, and a skipped gate says so ---
#
# `available_usd` was an account balance written into an uploaded artifact
# while the same receipt pinned `account_amounts_recorded: False`. Round 2
# replaced it with a two-decimal ratio, which round 3 removed: `estimate_usd`
# is published at full precision in the same receipt and is deterministic, so
# `available = ratio x estimate` inverted the balance to well under a cent for
# any key under the 10x cap - precisely the thin-key case the field described.
# A bucket is what survives: it answers "can this key fund this run, and by
# roughly how much" while many balances share one receipt.


def _bucket_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, available: float, usage: float
) -> tuple[dict[str, object], str]:
    """One live receipt for one balance, plus the bytes that reach the artifact."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight,
        "_get_json",
        _fake_get(key_data={"limit_remaining": available, "usage": usage}),
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    output = tmp_path / f"receipt-{available}.json"
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=output,
        source_sha="a" * 40,
        live=True,
    )
    return receipt, output.read_text(encoding="utf-8")


# estimate_usd is 0.986425 for the default one-task budget on this route, so
# each row below is (bucket, balances that must be indistinguishable in it).
# Boundaries: 1x = 0.986425, 3x = 2.959275, 10x = 9.86425.
_HEADROOM_GRID = (
    ("lt_1x", (0.11, 0.53, 0.97)),
    ("1x_to_3x", (1.01, 1.87, 2.93)),
    ("3x_to_10x", (3.01, 6.66, 9.81)),
    ("ge_10x", (9.91, 99.99, 4242.42)),
)


@pytest.mark.parametrize(("bucket", "balances"), _HEADROOM_GRID)
def test_the_receipt_is_not_injective_in_the_account_balance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bucket: str,
    balances: tuple[float, ...],
) -> None:
    """The privacy property, stated behaviourally rather than as a naming rule.

    A key-name check ("no field called balance") cannot see an invertible
    field. This one can: within a bucket, every balance must produce the same
    receipt, byte for byte, so no reader can recover which balance produced it.
    """
    usage = 67.89
    receipts = [
        _bucket_receipt(monkeypatch, tmp_path, balance, usage)
        for balance in balances
    ]
    rendered = {json.dumps(receipt, sort_keys=True) for receipt, _ in receipts}

    assert len(rendered) == 1, "the receipt distinguishes balances within a bucket"
    for receipt, _ in receipts:
        assert receipt["funds_headroom_bucket"] == bucket
        assert receipt["account_amounts_recorded"] is False
        assert "available_usd" not in receipt
    for balance, (_, written) in zip(balances, receipts, strict=True):
        # Neither the balance nor the usage figure may survive into the artifact.
        assert str(balance) not in written
        assert str(usage) not in written


def test_no_bucket_boundary_leaks_a_balance_across_the_whole_grid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every balance in the grid lands in its declared bucket, and the four
    buckets are the only thing that separates their receipts."""
    seen: dict[str, set[str]] = {}
    for bucket, balances in _HEADROOM_GRID:
        for balance in balances:
            receipt, written = _bucket_receipt(monkeypatch, tmp_path, balance, 67.89)
            assert receipt["funds_headroom_bucket"] == bucket
            assert str(balance) not in written
            seen.setdefault(bucket, set()).add(json.dumps(receipt, sort_keys=True))

    assert set(seen) == {"lt_1x", "1x_to_3x", "3x_to_10x", "ge_10x"}
    # 12 balances, 4 distinguishable receipts: the map is 3-to-1 by construction
    # and coarser than that for any real account.
    assert all(len(rendered) == 1 for rendered in seen.values())


def test_headroom_is_null_when_the_route_is_priced_at_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A $0 preview route (union-alpha/stealth) estimates at zero: the run is
    funded, and the ratio has no denominator to report."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    manifest = _manifest_with(
        tmp_path,
        "route-free.json",
        pricing={"prompt_usd_per_token": 0.0, "completion_usd_per_token": 0.0},
    )
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"limit_remaining": 5.0})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    receipt = provider_preflight.run(
        manifest=manifest,
        output=tmp_path / "receipt.json",
        source_sha="b" * 40,
        live=True,
    )
    assert receipt["status"] == "PASS"
    assert receipt["funds_verdict"] == "sufficient"
    assert receipt["estimate_usd"] == pytest.approx(0.0)
    assert receipt["funds_headroom_bucket"] is None


def test_provider_free_receipt_reports_no_funds_verdict(tmp_path: Path) -> None:
    """Nothing was assessed without a live probe, so the verdict is absent
    rather than a cleared-looking "sufficient"."""
    receipt = provider_preflight.run(
        manifest=MANIFEST,
        output=tmp_path / "receipt.json",
        source_sha="c" * 40,
        live=False,
    )
    assert receipt["funds_verdict"] is None
    assert receipt["funds_headroom_bucket"] is None
    assert "available_usd" not in receipt


def _cli_argv(manifest: Path, output: Path) -> list[str]:
    return [
        "provider_preflight",
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--source-sha",
        "d" * 40,
        "--live",
    ]


def test_cli_warns_when_an_unbounded_key_skips_the_funds_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An account-level key reports `limit: null`, so the funds gate cannot
    run. It stays a PASS - the key is not broken - but the run log has to say
    the gate was skipped instead of letting silence read as cleared."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"usage": 12.5})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    monkeypatch.setattr(
        sys, "argv", _cli_argv(MANIFEST, tmp_path / "receipt.json")
    )
    assert provider_preflight.main() == 0
    printed = capsys.readouterr().out
    # REVIEW-13 MEDIUM-2: the annotation is built by scripts.gh_annotations
    # now, so it carries a title and - the point of the change - every
    # interpolated field is escaped and bounded. It is still ONE line: a
    # planted verdict or reason cannot open a second workflow command.
    commands = [line for line in printed.split("\n") if line.startswith("::")]
    assert len(commands) == 1, printed
    assert commands[0].startswith("::warning title=Provider funds::")
    assert "unbounded_key" in commands[0]
    assert "provider_key_limit_unbounded" in commands[0]


def test_cli_does_not_warn_when_the_funds_gate_clears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "canary-not-a-real-key")
    monkeypatch.setattr(
        provider_preflight, "_get_json", _fake_get(key_data={"limit_remaining": 10_000})
    )
    monkeypatch.setattr(provider_preflight, "_post_json", _fake_post("fp_deepinfra"))
    monkeypatch.setattr(
        sys, "argv", _cli_argv(MANIFEST, tmp_path / "receipt.json")
    )
    assert provider_preflight.main() == 0
    printed = capsys.readouterr().out
    assert [line for line in printed.split("\n") if line.startswith("::")] == []


def test_endpoints_url_follows_the_manifest_path_and_quotes_the_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing hangs off the manifest's own models path, like every other
    probe request, and the model id - which contains "/" - is percent-encoded
    so a vendor slug cannot inject anything into the URL."""
    route, _ = provider_preflight.load_route(MANIFEST)
    route = dict(
        route,
        model="vendor/model name+v1",
        availability=dict(route["availability"], models_path="/catalogue"),
    )
    seen: list[str] = []

    def fake_get(url: str, _api_key: str) -> dict[str, object]:
        seen.append(url)
        return {"data": {"endpoints": []}}

    monkeypatch.setattr(provider_preflight, "_get_json", fake_get)
    assert (
        provider_preflight._served_endpoint(
            "https://openrouter.ai/api/v1", "canary-not-a-real-key", route
        )
        is None
    )
    assert seen == [
        "https://openrouter.ai/api/v1/catalogue/vendor/model%20name%2Bv1/endpoints"
    ]


def test_both_paid_route_manifests_pin_the_published_streamlake_price() -> None:
    """scripts/tb2_report.py prices a run from this block, and the preflight
    estimates from it, so a catalog price change cannot silently move either.

    OpenRouter also publishes a StreamLake cache-read rate (1.4e-9/token), but
    the pricing block admits exactly the two keys below (load_route refuses
    any other), and tb2_report bills cached input at the prompt rate - so the
    estimate stays an upper bound rather than gaining an unvalidated field."""
    for name in PAID_ROUTE_MANIFESTS:
        route, _ = provider_preflight.load_route(ROOT / "config" / name)
        assert route["pricing"] == {
            "prompt_usd_per_token": 0.000000044,
            "completion_usd_per_token": 0.000000132,
        }, name


# --- round 3: the consumer side of the gate ---
#
# The preflight is told the cohort size with --expected-tasks and prices it.
# Nothing downstream checked that the number it was told is the number the
# planner actually dispatches, so a stale or empty expression would have
# priced one task for a 20-task run and still reported "sufficient".

PAID_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "swelive_gt_harness_paid.yaml",
    ROOT / ".github" / "workflows" / "deepswe_gt_harness_product_p0731.yaml",
)


@pytest.mark.parametrize("workflow", PAID_WORKFLOWS, ids=lambda path: path.stem)
def test_paid_workflow_binds_the_priced_cohort_to_the_planned_one(
    workflow: Path,
) -> None:
    text = workflow.read_text(encoding="utf-8")

    # The planner's count reaches the check as data, not as source code
    # interpolated into the heredoc.
    assert "PLANNED_TASK_COUNT: ${{ needs.plan.outputs.task_count }}" in text
    assert 'planned = int(os.environ["PLANNED_TASK_COUNT"])' in text
    assert 'if receipt.get("expected_tasks") != planned:' in text
    assert "::error title=Provider funds::the funds gate priced" in text
    assert "raise SystemExit(1)" in text


@pytest.mark.parametrize("workflow", PAID_WORKFLOWS, ids=lambda path: path.stem)
def test_paid_workflow_logs_a_bucket_and_never_a_headroom_ratio(
    workflow: Path,
) -> None:
    text = workflow.read_text(encoding="utf-8")

    assert "funds_headroom_ratio" not in text
    assert "headroom_ratio" not in text
    assert "funds_headroom_bucket" in text
    for field in ("funds_verdict=", "reason=", "headroom=", "task(s)"):
        assert field in text


@pytest.mark.parametrize("workflow", PAID_WORKFLOWS, ids=lambda path: path.stem)
def test_paid_workflow_line_endings_are_committed_and_it_parses_as_yaml(
    workflow: Path,
) -> None:
    """Pin the bytes CI reads, which are the committed ones.

    This asserted CRLF over the worktree. That is a property of the checkout,
    not of the repository: git writes CRLF here under autocrlf and LF on the
    runner, so the check passed on Windows and failed on Linux over content
    that was identical in git. These blobs are stored LF, so LF is what the
    run actually consumes and what a future normalization must not silently
    flip.
    """
    committed = subprocess.run(
        ["git", "show", f"HEAD:{workflow.relative_to(ROOT).as_posix()}"],
        capture_output=True, check=True, cwd=ROOT,
    ).stdout

    assert committed.count(b"\r\n") == 0, "committed workflow bytes are LF"
    assert committed.count(b"\n") > 0
    text = workflow.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["jobs"]["provider_gate"]["steps"]
