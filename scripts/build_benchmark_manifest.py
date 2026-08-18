"""Build a pinned comparison manifest from caller-supplied benchmark inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from gt_engine.treatment_adapter import (
    BenchmarkManifest,
    treatment_from_descriptor,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--scaffold-sha", required=True)
    parser.add_argument("--treatments", type=Path, required=True)
    parser.add_argument("--execution-contract", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--trials-per-task", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    task_manifest = args.task_manifest.resolve(strict=True)
    execution_contract_path = args.execution_contract.resolve(strict=True)
    treatments_path = args.treatments.resolve(strict=True)
    output = args.output.resolve()
    if output == task_manifest:
        raise ValueError("output must not overwrite the task manifest")
    if output in {execution_contract_path, treatments_path}:
        raise ValueError("output must not overwrite an input file")
    execution_contract = json.loads(execution_contract_path.read_text(encoding="utf-8"))
    if not isinstance(execution_contract, dict):
        raise ValueError("execution contract must be a JSON object")
    treatment_rows = json.loads(treatments_path.read_text(encoding="utf-8"))
    if not isinstance(treatment_rows, list) or not treatment_rows:
        raise ValueError("treatments must be a non-empty JSON array")
    if not all(isinstance(row, dict) for row in treatment_rows):
        raise ValueError("every treatment descriptor must be a JSON object")
    treatments = tuple(treatment_from_descriptor(row) for row in treatment_rows)
    task_manifest_sha256 = hashlib.sha256(task_manifest.read_bytes()).hexdigest()
    manifest = BenchmarkManifest.create(
        benchmark_id=args.benchmark_id,
        task_manifest_sha256=task_manifest_sha256,
        model_id=args.model_id,
        scaffold_sha=args.scaffold_sha,
        max_steps=args.max_steps,
        trials_per_task=args.trials_per_task,
        execution_contract=execution_contract,
        treatments=treatments,
    )
    _atomic_write_json(output, manifest.as_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
