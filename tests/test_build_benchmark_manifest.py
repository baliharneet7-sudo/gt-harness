from __future__ import annotations

import hashlib
import json

import pytest

from scripts.build_benchmark_manifest import build_parser, main


def _sha1(label: str) -> str:
    return hashlib.sha1(label.encode(), usedforsecurity=False).hexdigest()


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _execution_contract() -> dict[str, object]:
    return {
        "task_count": 1,
        "task_order_sha256": _sha256("fixture-task-order"),
        "provider_identity": "fixture-provider",
        "temperature": 0.0,
        "sampling_parameters": {},
        "tool_envelope_sha256": _sha256("fixture-tools"),
        "hook_envelope_sha256": _sha256("fixture-hooks"),
        "embedding_configuration_sha256": _sha256("fixture-embedding"),
        "hardware_assumptions_sha256": _sha256("fixture-hardware"),
        "retry_policy_sha256": _sha256("fixture-retries"),
        "timeout_policy_sha256": _sha256("fixture-timeouts"),
        "token_accounting_sha256": _sha256("fixture-token-accounting"),
    }


def _write_treatments(path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "adapter_kind": "bare",
                    "treatment_id": "control",
                    "source_sha": _sha1("fixture-harness"),
                },
                {
                    "adapter_kind": "groundtruth",
                    "treatment_id": "groundtruth",
                    "source_sha": _sha1("fixture-harness"),
                    "profile_id": "central_relational_v2",
                    "preemptive_retrieval": True,
                    "relational_context": True,
                    "dense_fallback_only": True,
                    "semantic_evidence": True,
                },
            ]
        ),
        encoding="utf-8",
    )


def test_manifest_cli_requires_every_benchmark_identity_and_budget() -> None:
    parser = build_parser()
    required = {
        action.dest
        for action in parser._actions
        if getattr(action, "required", False)
    }

    assert required >= {
        "benchmark_id",
        "task_manifest",
        "model_id",
        "scaffold_sha",
        "treatments",
        "execution_contract",
        "max_steps",
        "trials_per_task",
        "output",
    }
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_manifest_cli_hashes_caller_supplied_task_manifest_and_preserves_budget(
    tmp_path,
) -> None:
    task_manifest = tmp_path / "tasks.jsonl"
    task_manifest.write_text('{"instance_id":"fixture-1"}\n', encoding="utf-8")
    execution_contract = tmp_path / "execution-contract.json"
    execution_contract.write_text(
        json.dumps(_execution_contract()), encoding="utf-8"
    )
    treatments = tmp_path / "treatments.json"
    _write_treatments(treatments)
    output = tmp_path / "benchmark-manifest.json"

    exit_code = main(
        [
            "--benchmark-id",
            "fixture-suite",
            "--task-manifest",
            str(task_manifest),
            "--model-id",
            "fixture-provider/model",
            "--scaffold-sha",
            _sha1("fixture-scaffold"),
            "--treatments",
            str(treatments),
            "--execution-contract",
            str(execution_contract),
            "--max-steps",
            "23",
            "--trials-per-task",
            "2",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["benchmark_id"] == "fixture-suite"
    assert payload["task_manifest_sha256"] == hashlib.sha256(
        task_manifest.read_bytes()
    ).hexdigest()
    assert payload["max_steps"] == 23
    assert payload["trials_per_task"] == 2
    assert payload["execution_contract"] == _execution_contract()
    assert payload["parity_treatment_ids"] == ["control", "groundtruth"]


def test_manifest_cli_refuses_to_overwrite_its_task_manifest(tmp_path) -> None:
    task_manifest = tmp_path / "tasks.jsonl"
    original = '{"instance_id":"fixture-1"}\n'
    task_manifest.write_text(original, encoding="utf-8")
    execution_contract = tmp_path / "execution-contract.json"
    execution_contract.write_text(json.dumps(_execution_contract()), encoding="utf-8")
    treatments = tmp_path / "treatments.json"
    _write_treatments(treatments)

    with pytest.raises(ValueError, match="output must not overwrite the task manifest"):
        main(
            [
                "--benchmark-id",
                "fixture-suite",
                "--task-manifest",
                str(task_manifest),
                "--model-id",
                "fixture-provider/model",
                "--scaffold-sha",
                _sha1("fixture-scaffold"),
                "--treatments",
                str(treatments),
                "--execution-contract",
                str(execution_contract),
                "--max-steps",
                "9",
                "--trials-per-task",
                "2",
                "--output",
                str(task_manifest),
            ]
        )

    assert task_manifest.read_text(encoding="utf-8") == original


def test_manifest_cli_refuses_to_overwrite_its_execution_contract(tmp_path) -> None:
    task_manifest = tmp_path / "tasks.jsonl"
    task_manifest.write_text('{"instance_id":"fixture-1"}\n', encoding="utf-8")
    execution_contract = tmp_path / "execution-contract.json"
    original = json.dumps(_execution_contract())
    execution_contract.write_text(original, encoding="utf-8")
    treatments = tmp_path / "treatments.json"
    _write_treatments(treatments)

    with pytest.raises(ValueError, match="output must not overwrite an input"):
        main(
            [
                "--benchmark-id",
                "fixture-suite",
                "--task-manifest",
                str(task_manifest),
                "--model-id",
                "fixture-provider/model",
                "--scaffold-sha",
                _sha1("fixture-scaffold"),
                "--treatments",
                str(treatments),
                "--execution-contract",
                str(execution_contract),
                "--max-steps",
                "9",
                "--trials-per-task",
                "2",
                "--output",
                str(execution_contract),
            ]
        )

    assert execution_contract.read_text(encoding="utf-8") == original
