from __future__ import annotations

import json
from pathlib import Path

from scripts.inventory_historical_replay import build_inventory


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_inventory_ignores_verifier_and_artifact_directories(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.json"
    root = tmp_path / "tasks"
    _write(predictions, {"predictions": [{"task": "one", "class": "gain"}]})
    (root / "one" / "verifier" / "workspace").mkdir(parents=True)
    (root / "one" / "artifacts" / "repository").mkdir(parents=True)

    result = build_inventory(
        predictions_path=predictions,
        artifact_root=root,
        workspace_names=("workspace", "repository"),
    )

    assert result["available_count"] == 0
    assert result["entries"][0]["status"] == "unavailable"
    assert result["entries"][0]["reason"] == "no_legal_workspace_found"
    assert result["replay_executed"] is False


def test_inventory_reports_only_explicit_legal_workspace(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.json"
    root = tmp_path / "tasks"
    _write(predictions, {"predictions": [{"task": "one"}]})
    workspace = root / "one" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "src.py").write_text("print('ok')\n", encoding="utf-8")

    result = build_inventory(
        predictions_path=predictions,
        artifact_root=root,
        workspace_names=("workspace",),
    )

    assert result["available_count"] == 1
    assert result["entries"][0]["workspace_candidates"] == ["one/workspace"]
