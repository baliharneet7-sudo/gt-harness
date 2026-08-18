"""Inventory legal inputs for historical GroundTruth replay.

This command is deliberately an availability audit, not a replay engine.  It
reads the frozen prediction rows, looks for explicitly named repository
workspace directories under each row's artifact directory, and records which
rows can be replayed without touching verifier-only material.  It never reads
grader outputs and never turns a prediction into an observed outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

FORBIDDEN_PARTS = frozenset({"verifier", "artifacts"})
DEFAULT_WORKSPACE_NAMES = ("workspace", "repository", "repo", "source_workspace")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: Path, root: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if any(part in FORBIDDEN_PARTS for part in relative.parts):
        return None
    return relative.as_posix()


def _workspace_candidates(task_root: Path, names: tuple[str, ...]) -> list[Path]:
    if not task_root.is_dir():
        return []
    candidates: list[Path] = []
    for name in names:
        for candidate in task_root.glob(f"**/{name}"):
            if not candidate.is_dir():
                continue
            if _safe_relative(candidate, task_root) is None:
                continue
            try:
                next(candidate.iterdir())
            except (OSError, StopIteration):
                continue
            candidates.append(candidate)
    return sorted(set(candidates), key=lambda path: path.as_posix())


def build_inventory(
    *,
    predictions_path: Path,
    artifact_root: Path,
    workspace_names: tuple[str, ...],
) -> dict[str, Any]:
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    rows = predictions.get("predictions")
    if not isinstance(rows, list):
        raise ValueError("prediction artifact must contain a predictions list")

    artifact_root = artifact_root.resolve()
    entries: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"prediction row {index} is not an object")
        task = str(row.get("task") or "").strip()
        if not task or Path(task).name != task or task in {".", ".."}:
            raise ValueError(f"prediction row {index} has an invalid task")
        task_root = artifact_root / task
        candidates = _workspace_candidates(task_root, workspace_names)
        legal_candidates = []
        for candidate in candidates:
            relative = _safe_relative(candidate, artifact_root)
            if relative is not None:
                legal_candidates.append(relative)
        entries.append(
            {
                "task": task,
                "class": row.get("class"),
                "status": "available" if legal_candidates else "unavailable",
                "reason": None
                if legal_candidates
                else "no_legal_workspace_found",
                "workspace_candidates": legal_candidates,
                "prediction_sha256": _sha256(predictions_path),
            }
        )

    return {
        "schema": "gt.historical_replay_inventory.v1",
        "prediction_artifact": predictions_path.resolve().as_posix(),
        "prediction_artifact_sha256": _sha256(predictions_path),
        "artifact_root": artifact_root.as_posix(),
        "workspace_names": list(workspace_names),
        "forbidden_path_parts": sorted(FORBIDDEN_PARTS),
        "entries": entries,
        "available_count": sum(entry["status"] == "available" for entry in entries),
        "unavailable_count": sum(entry["status"] == "unavailable" for entry in entries),
        "replay_executed": False,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workspace-name",
        action="append",
        dest="workspace_names",
        help="Allowed workspace directory name; may be repeated.",
    )
    args = parser.parse_args()
    workspace_names = tuple(args.workspace_names or DEFAULT_WORKSPACE_NAMES)
    if args.output.resolve() in {args.predictions.resolve(), args.artifact_root.resolve()}:
        raise SystemExit("output must not overwrite an input path")
    result = build_inventory(
        predictions_path=args.predictions,
        artifact_root=args.artifact_root,
        workspace_names=workspace_names,
    )
    _write_atomic(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
