"""The three GT-on mini workflows: 20 fixed tasks, first5 gate, 5 parallel."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
MINIS = {
    "gt_mini_tb2.yml": "./.github/workflows/tb2_miniswe_central.yml",
    "gt_mini_deepswe.yml": "./.github/workflows/deepswe_gt_delivery_ab.yml",
    "gt_mini_swelive.yml": "./.github/workflows/swelive_gt_harness_paid.yaml",
}


def _load(name: str) -> tuple[str, dict]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def _sets(text: str) -> tuple[list[str], list[str]]:
    first5 = re.search(r'FIRST5="([^"]+)"', text).group(1).split(",")
    rest15 = re.search(r'REST15="([^"]+)"', text).group(1).split(",")
    return first5, rest15


@pytest.mark.parametrize("name", sorted(MINIS))
def test_twenty_disjoint_tasks_split_five_then_fifteen(name: str) -> None:
    first5, rest15 = _sets(_load(name)[0])
    assert len(first5) == 5 and len(rest15) == 15
    assert len(set(first5 + rest15)) == 20


@pytest.mark.parametrize("name", sorted(MINIS))
def test_runs_gt_on_five_at_a_time_through_the_certified_pipeline(name: str) -> None:
    text, workflow = _load(name)
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert inputs["stage"]["options"] == ["first5", "rest15"]
    assert inputs["gt_delivery_mode"]["options"] == ["attached", "push"]
    assert inputs["model"]["required"] is True and "default" not in inputs["model"]
    job = workflow["jobs"]["gt_on"]
    assert job["uses"] == MINIS[name]
    assert job["secrets"] == "inherit"
    assert job["needs"] == "gate"
    assert job["with"]["max_parallel"] == "5"
    assert "gt_off" not in text


@pytest.mark.parametrize("name", sorted(MINIS))
def test_rest15_is_gated_on_a_successful_first5_of_the_same_workflow(name: str) -> None:
    text, _ = _load(name)
    gate = _load(name)[1]["jobs"]["gate"]["steps"][0]["run"]
    assert f"WORKFLOW_PATH: .github/workflows/{name}" in text
    assert 'if [ "$conclusion" != success ]' in gate
    assert '*"| first5 |"*' in gate
    assert "rest15 needs first5_run_id" in gate


def test_task_sets_resolve_against_the_pinned_catalogs() -> None:
    deepswe = {row["task_id"] for row in json.loads(
        (ROOT / "config" / "deepswe_task_catalog_v1.json").read_text(encoding="utf-8"))["tasks"]}
    swelive = {row.get("instance_id") or row.get("task_id") for row in json.loads(
        (ROOT / "config" / "swelive_lite_catalog_v1.json").read_text(encoding="utf-8"))["tasks"]}
    tb2_text = (WORKFLOWS / "tb2_miniswe_central.yml").read_text(encoding="utf-8")
    repair20 = set(re.findall(r'"([a-z0-9-]+)"', tb2_text[tb2_text.index("tasks = ["):
                                                         tb2_text.index("expected_hash")]))
    for name, universe in (("gt_mini_deepswe.yml", deepswe), ("gt_mini_swelive.yml", swelive),
                           ("gt_mini_tb2.yml", repair20)):
        first5, rest15 = _sets(_load(name)[0])
        assert set(first5 + rest15) <= universe, name
    # TB2's subset stage draws only from repair20, and the mini set IS repair20.
    assert set(sum(_sets(_load("gt_mini_tb2.yml")[0]), [])) == repair20
