#!/usr/bin/env python3
"""Stage Harbor artifacts into a readable, completeness-certified upload tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from scripts.harbor_results import collect_harbor_results

_AUDIT_NAMES = frozenset(
    {
        "result.json",
        "miniswe_trajectory.json",
        "central_receipt.json",
        "benchmark-manifest.json",
        "intervention_chain.json",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_harbor_artifacts(
    source: Path, target: Path, *, expected_tasks: tuple[str, ...]
) -> dict[str, Any]:
    source = source.resolve()
    target = target.resolve()
    if not source.is_dir():
        raise ValueError(f"artifact source is not a directory: {source}")
    if target.exists():
        raise ValueError(f"artifact stage target already exists: {target}")
    shutil.copytree(source, target, copy_function=shutil.copy2)
    collection = collect_harbor_results(target, expected_tasks=expected_tasks)
    audited_files = []
    for path in sorted(target.rglob("*")):
        if not path.is_file() or path.name not in _AUDIT_NAMES:
            continue
        audited_files.append(
            {
                "path": path.relative_to(target).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "schema": "gt.harbor_artifact_stage.v1",
        "status": "PASS" if not collection.failures else "BLOCKED",
        "source": str(source),
        "target": str(target),
        "result_collection": collection.as_dict(),
        "audited_files": audited_files,
        "audited_file_count": len(audited_files),
    }
    (target / "artifact-stage-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--expected-csv", default="")
    args = parser.parse_args(argv)
    expected = tuple(
        item.strip() for item in args.expected_csv.split(",") if item.strip()
    )
    manifest = stage_harbor_artifacts(
        args.source, args.target, expected_tasks=expected
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
