"""Build a source-owned runtime observation for a benchmark receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gt_engine.benchmark_parity import (
    RUNTIME_SOURCE_FIELDS,
    build_runtime_observation_from_sources,
)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"runtime source must be a JSON object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for source_name in RUNTIME_SOURCE_FIELDS:
        parser.add_argument(
            f"--{source_name.replace('_', '-')}",
            type=Path,
            required=True,
        )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_paths = {
        source_name: getattr(args, source_name)
        for source_name in RUNTIME_SOURCE_FIELDS
    }
    output = args.output.resolve()
    resolved_inputs = {path.resolve() for path in source_paths.values()}
    if output in resolved_inputs:
        raise ValueError("output must not overwrite a runtime source document")
    observation = build_runtime_observation_from_sources(
        {
            source_name: _load_object(path.resolve(strict=True))
            for source_name, path in source_paths.items()
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(observation, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(json.dumps(observation, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
