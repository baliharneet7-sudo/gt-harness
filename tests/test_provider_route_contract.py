from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.provider_route_contract import (
    bind_provider_credential,
    resolve_release_provider_route,
)


def test_frozen_release_route_is_derived_from_baseline_identity() -> None:
    root = Path(__file__).resolve().parents[1]

    route = resolve_release_provider_route(
        root / "eval/release/active_release.json", root=root
    )

    assert route["request_model"] == "deepseek-v4-flash"
    assert route["litellm_model"] == "openai/deepseek-v4-flash"
    assert route["api_base"] == "https://api.deepseek.com"
    assert route["expected_response_model"] == "deepseek-v4-flash"
    assert route["expected_adapter_provider"] == "openai"
    assert route["credential_secret_name"] == "DEEPSEEK_API_KEY"
    assert "credential_value" not in route
    assert "sk-" not in json.dumps(route).lower()


def test_release_route_rejects_ambiguous_or_non_native_identity(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    treatment = tmp_path / "treatment.json"
    prediction = tmp_path / "prediction.json"
    baseline.write_text(
        json.dumps(
            {
                "manifest": {
                    "model": "model",
                    "model_identity": {
                        "catalog_model": "openai/model",
                        "response_model": "model",
                        "route": "gateway:ambiguous",
                        "api_host": "gateway.invalid",
                        "adapter_provider": "openai",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    treatment.write_text("{}", encoding="utf-8")
    prediction.write_text("{}", encoding="utf-8")
    import hashlib

    manifest = tmp_path / "active_release.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "gt.release_manifest.v1",
                "release_id": "test",
                "task_profile": "repair20-v1",
                "runtime_commit": "a" * 40,
                "prediction": {
                    "path": "prediction.json",
                    "sha256": hashlib.sha256(prediction.read_bytes()).hexdigest(),
                },
                "baseline": {
                    "path": "baseline.json",
                    "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                },
                "treatment": {
                    "path": "treatment.json",
                    "sha256": hashlib.sha256(treatment.read_bytes()).hexdigest(),
                },
                "allowed_post_runtime_paths": [
                    "active_release.json",
                    "prediction.json",
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="native provider route"):
        resolve_release_provider_route(manifest, root=tmp_path)


def test_paid_workflow_loads_route_identity_instead_of_dispatching_it() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/tb2_miniswe_central.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts.provider_route_contract" in workflow
    assert "inputs.api_key" not in workflow
    assert "inputs.model" not in workflow
    assert "inputs.api_base" not in workflow
    assert "OPENAI_BASE_URL: https://api.deepseek.com" not in workflow
    assert "GT_LITELLM_MODEL: openai/deepseek-v4-flash" not in workflow
    assert "OPENAI_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}" not in workflow
    assert "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}" not in workflow
    assert "DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}" not in workflow
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" not in workflow
    assert "TOKENROUTER_API_KEY: ${{ secrets.TOKENROUTER_API_KEY }}" not in workflow
    assert (
        "GT_SELECTED_PROVIDER_CREDENTIAL: "
        "${{ secrets[steps.route.outputs.credential_secret_name] }}"
    ) in workflow
    assert "--bind-credential" in workflow


def test_approved_credential_binding_never_enters_route_receipt() -> None:
    route = {
        "credential_secret_name": "DEEPSEEK_API_KEY",
    }
    credential = bind_provider_credential(
        route, environ={"DEEPSEEK_API_KEY": "opaque-test-credential"}
    )

    assert credential == "opaque-test-credential"
    assert "opaque-test-credential" not in json.dumps(route)


def test_provider_neutral_selected_credential_takes_precedence() -> None:
    route = {"credential_secret_name": "DEEPSEEK_API_KEY"}

    credential = bind_provider_credential(
        route,
        environ={
            "GT_SELECTED_PROVIDER_CREDENTIAL": "selected-credential",
            "DEEPSEEK_API_KEY": "provider-named-fallback",
        },
    )

    assert credential == "selected-credential"
