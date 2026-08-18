from __future__ import annotations

import json

import pytest

from scripts.build_runtime_observation import main


def _sources() -> dict[str, dict[str, object]]:
    return {
        "dispatch_manifest": {
            "task_count": 2,
            "task_order_sha256": "a" * 64,
        },
        "provider_request": {
            "provider_identity": "fixture/provider",
            "temperature": 0.0,
            "sampling_parameters": {"top_p": 1.0},
        },
        "serialized_runtime_envelope": {
            "tool_envelope_sha256": "b" * 64,
            "hook_envelope_sha256": "c" * 64,
        },
        "loaded_asset_receipt": {
            "embedding_configuration_sha256": "d" * 64,
        },
        "runner_environment": {
            "hardware_assumptions_sha256": "e" * 64,
        },
        "runtime_policy": {
            "retry_policy_sha256": "f" * 64,
            "timeout_policy_sha256": "0" * 64,
        },
        "metering_adapter": {
            "token_accounting_sha256": "1" * 64,
        },
    }


def test_runtime_observation_cli_builds_from_separate_sources(tmp_path, capsys):
    paths = {}
    for source_name, value in _sources().items():
        path = tmp_path / f"{source_name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[source_name] = path
    output = tmp_path / "runtime-observation.json"
    args = []
    for source_name, path in paths.items():
        args.extend([f"--{source_name.replace('_', '-')}", str(path)])
    args.extend(["--output", str(output)])

    assert main(args) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "gt.benchmark_runtime_execution_observation.v1"
    assert payload["execution_contract"]["task_count"] == 2
    assert payload["field_sources"]["provider_identity"]["origin"] == (
        "provider_request"
    )
    assert capsys.readouterr().out


def test_runtime_observation_cli_does_not_overwrite_source(tmp_path):
    paths = {}
    for source_name, value in _sources().items():
        path = tmp_path / f"{source_name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[source_name] = path
    args = []
    for source_name, path in paths.items():
        args.extend([f"--{source_name.replace('_', '-')}", str(path)])
    args.extend(["--output", str(paths["provider_request"])])

    with pytest.raises(ValueError, match="must not overwrite"):
        main(args)
