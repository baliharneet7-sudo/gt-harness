"""Render one caller-owned GT treatment descriptor into Harbor agent arguments."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# This module has a machine-readable stdout contract when emitting Harbor
# arguments.  mini-swe-agent 2.2.x otherwise prints a startup banner at import
# time, which would become invalid command-line arguments in a shell mapfile.
os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")

from eval.gt_central_agent import MiniSweCentralAgent
from gt_engine.treatment_adapter import (
    BenchmarkManifest,
    GroundTruthTreatmentAdapter,
    treatment_from_descriptor,
)
from scripts.release_manifest import load_release_manifest

_IDENTITY_KEYS = frozenset(
    {
        "integration_mode",
        "treatment_profile",
        "enable_persistent_execution_state",
        "enable_preemptive_retrieval",
        "enable_relational_context",
        "enable_semantic_evidence",
        "dense_fallback_only",
        "relational_context_max_depth",
        "relational_context_max_branching",
        "relational_context_max_processes",
        "relational_context_max_tokens",
        "step_limit",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", "surrogatepass")


def _benchmark_runtime_identity(
    manifest: Mapping[str, Any],
    *,
    treatment: GroundTruthTreatmentAdapter,
    max_steps: int,
) -> dict[str, Any]:
    """Validate a built manifest and select this treatment's runtime identity."""

    verified = BenchmarkManifest.from_dict(manifest)
    if verified.max_steps != int(max_steps):
        raise ValueError("benchmark manifest step limit mismatch")
    identity = verified.runtime_identity(treatment.treatment_id)
    if _canonical(identity["treatment"]) != _canonical(treatment.receipt_identity()):
        raise ValueError("benchmark manifest treatment identity mismatch")
    return identity


def build_runtime_arguments(
    descriptor: Mapping[str, Any],
    *,
    source_sha: str,
    max_steps: int,
    benchmark_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = dict(descriptor)
    runtime_kwargs = row.pop("runtime_agent_kwargs", {})
    if not isinstance(runtime_kwargs, dict):
        raise ValueError("runtime_agent_kwargs must be an object")
    forbidden = sorted(_IDENTITY_KEYS.intersection(runtime_kwargs))
    if forbidden:
        raise ValueError(
            "runtime_agent_kwargs must not override treatment identity: "
            + ", ".join(forbidden)
        )
    row["source_sha"] = str(source_sha or "").strip().lower()
    treatment = treatment_from_descriptor(row)
    if not isinstance(treatment, GroundTruthTreatmentAdapter):
        raise ValueError("runtime argument rendering requires a GroundTruth treatment")
    if isinstance(max_steps, bool) or int(max_steps) < 1:
        raise ValueError("max_steps must be a positive integer")

    accepted = set(inspect.signature(MiniSweCentralAgent.__init__).parameters)
    unknown = sorted(set(runtime_kwargs) - accepted)
    if unknown:
        raise ValueError("unknown MiniSweCentralAgent arguments: " + ", ".join(unknown))

    agent_kwargs = treatment.agent_kwargs()
    agent_kwargs.update(runtime_kwargs)
    agent_kwargs["step_limit"] = int(max_steps)
    if benchmark_manifest is not None:
        agent_kwargs["benchmark_identity"] = _benchmark_runtime_identity(
            benchmark_manifest,
            treatment=treatment,
            max_steps=int(max_steps),
        )
    payload: dict[str, Any] = {
        "schema": "gt.treatment_runtime_arguments.v1",
        "treatment_id": treatment.treatment_id,
        "source_sha": treatment.source_sha,
        "profile_id": treatment.profile_id,
        "agent_kwargs": agent_kwargs,
    }
    payload["contract_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def harbor_argument_lines(payload: Mapping[str, Any]) -> tuple[str, ...]:
    if payload.get("schema") != "gt.treatment_runtime_arguments.v1":
        raise ValueError("unsupported treatment runtime argument schema")
    kwargs = payload.get("agent_kwargs")
    if not isinstance(kwargs, dict):
        raise ValueError("treatment runtime arguments are missing agent_kwargs")
    lines: list[str] = []
    for key in sorted(kwargs):
        value = kwargs[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = "null"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            rendered = str(value)
        elif isinstance(value, str) and "\n" not in value and "\r" not in value:
            rendered = value
        else:
            rendered = _canonical(value).decode("utf-8")
        lines.extend(("--ak", f"{key}={rendered}"))
    return tuple(lines)


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--benchmark-manifest", type=Path)
    parser.add_argument("--emit-harbor-args", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.emit_harbor_args is not None:
        if any(
            value is not None
            for value in (
                args.descriptor,
                args.release_manifest,
                args.source_sha,
                args.max_steps,
                args.output,
                args.benchmark_manifest,
            )
        ):
            raise ValueError("--emit-harbor-args cannot be combined with build arguments")
        payload = json.loads(args.emit_harbor_args.resolve(strict=True).read_text(encoding="utf-8"))
        print("\n".join(harbor_argument_lines(payload)))
        return 0
    if None in (args.source_sha, args.max_steps, args.output):
        raise ValueError("build mode requires source SHA, max steps, and output")
    if (args.descriptor is None) == (args.release_manifest is None):
        raise ValueError("build mode requires exactly one descriptor source")
    descriptor_path = (
        args.descriptor.resolve(strict=True)
        if args.descriptor is not None
        else load_release_manifest(args.release_manifest).treatment_path
    )
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if not isinstance(descriptor, dict):
        raise ValueError("treatment descriptor must be an object")
    benchmark_manifest = (
        json.loads(args.benchmark_manifest.resolve(strict=True).read_text(encoding="utf-8"))
        if args.benchmark_manifest is not None
        else None
    )
    if benchmark_manifest is not None and not isinstance(benchmark_manifest, dict):
        raise ValueError("benchmark manifest must be an object")
    payload = build_runtime_arguments(
        descriptor,
        source_sha=args.source_sha,
        max_steps=args.max_steps,
        benchmark_manifest=benchmark_manifest,
    )
    _atomic_write(args.output.resolve(), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
