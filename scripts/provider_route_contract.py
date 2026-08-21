#!/usr/bin/env python3
"""Resolve an immutable release provider route without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scripts.release_manifest import ACTIVE_RELEASE_PATH, load_release_manifest

_CREDENTIAL_SECRET_NAMES = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "tokenrouter": "TOKENROUTER_API_KEY",
}
_SELECTED_CREDENTIAL_ENV = "GT_SELECTED_PROVIDER_CREDENTIAL"


def resolve_release_provider_route(
    manifest_path: Path = ACTIVE_RELEASE_PATH,
    *,
    root: Path | None = None,
) -> dict[str, str]:
    release_root = (root or Path.cwd()).resolve()
    release = load_release_manifest(manifest_path, root=release_root)
    baseline = json.loads(release.baseline_path.read_text(encoding="utf-8"))
    manifest = baseline.get("manifest") or {}
    identity = manifest.get("model_identity") or {}
    route_id = str(identity.get("route") or "")
    route_parts = route_id.split(":")
    if len(route_parts) != 3 or route_parts[1] != "native":
        raise ValueError("release comparison requires an exact native provider route")
    provider, _, route_host = route_parts
    api_host = str(identity.get("api_host") or "")
    if not api_host or route_host != api_host or any(
        character in api_host for character in "/\\?#@"
    ):
        raise ValueError("release provider route host is missing or inconsistent")
    fields: dict[str, Any] = {
        "request_model": manifest.get("model"),
        "litellm_model": identity.get("catalog_model"),
        "expected_response_model": identity.get("response_model"),
        "expected_adapter_provider": identity.get("adapter_provider"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in fields.values()):
        raise ValueError("release provider/model identity is incomplete")
    credential_secret_name = _CREDENTIAL_SECRET_NAMES.get(provider)
    if credential_secret_name is None:
        raise ValueError("release provider has no approved credential binding")
    return {
        "route_id": route_id,
        "request_model": str(fields["request_model"]),
        "litellm_model": str(fields["litellm_model"]),
        "api_base": f"https://{api_host}",
        "expected_response_model": str(fields["expected_response_model"]),
        "expected_adapter_provider": str(fields["expected_adapter_provider"]),
        "credential_secret_name": credential_secret_name,
    }


def _write_lines(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"provider route value contains a newline: {key}")
            handle.write(f"{key}={value}\n")


def bind_provider_credential(
    route: dict[str, str], *, environ: dict[str, str] | None = None
) -> str:
    """Resolve the approved route credential without serializing its value."""
    environment = os.environ if environ is None else environ
    secret_name = route["credential_secret_name"]
    # CI resolves exactly one approved GitHub secret by name and exposes it to
    # this binding step under a provider-neutral variable.  The named fallback
    # keeps the CLI usable outside GitHub without requiring all provider
    # credentials to coexist in the process environment.
    credential = str(
        environment.get(_SELECTED_CREDENTIAL_ENV)
        or environment.get(secret_name)
        or ""
    )
    if not credential:
        raise ValueError(f"required provider credential is unavailable: {secret_name}")
    if "\n" in credential or "\r" in credential:
        raise ValueError("provider credential contains a newline")
    return credential


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-manifest", type=Path, default=ACTIVE_RELEASE_PATH)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--bind-credential", action="store_true")
    args = parser.parse_args()
    route = resolve_release_provider_route(args.release_manifest)
    if args.github_env is not None:
        github_environment = {
                "OPENAI_BASE_URL": route["api_base"],
                "GT_LITELLM_MODEL": route["litellm_model"],
                "GT_EXPECTED_RESPONSE_MODEL": route["expected_response_model"],
                "GT_EXPECTED_ADAPTER_PROVIDER": route[
                    "expected_adapter_provider"
                ],
                "GT_PROVIDER_ROUTE_ID": route["route_id"],
        }
        if args.bind_credential:
            github_environment["OPENAI_API_KEY"] = bind_provider_credential(route)
        _write_lines(args.github_env, github_environment)
    elif args.bind_credential:
        raise ValueError("--bind-credential requires --github-env")
    if args.github_output is not None:
        _write_lines(args.github_output, route)
    if args.json_output is not None:
        args.json_output.write_text(
            json.dumps(route, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(route, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
