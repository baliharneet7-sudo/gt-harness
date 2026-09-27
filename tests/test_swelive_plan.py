"""Execute the SWE-bench-Live planner heredoc and attest what it produces.

The planner is inline Python in swelive_gt_harness_paid.yaml, so these tests
run THAT source (lifted from the workflow) in a scratch workspace instead of a
restatement of it, then drive scripts/attest_deepswe.py's swelive bindings.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from scripts import attest_deepswe
from scripts.attest_deepswe import attest_deepswe as attest
from scripts.benchmark_suites import load_suite
from scripts.build_swelive_catalog import (
    catalog_sha256,
    load_catalog,
    load_rows,
    materialize,
    shard_tasks,
    smoke5_task_ids,
    template_files,
)
from scripts.provider_preflight import load_route
from scripts.render_provider_route import main as render_route_cli
from tests.test_benchmark_suites import REQUESTED, SWELIVE_TASK, _swelive_fixture, _write

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/swelive_gt_harness_paid.yaml"
MODEL = "stealth/space-bunny-alpha"
# What a task leg reads from `matrix.*` in the workflow; everything else stays
# in the uploaded plan.
LEG_KEYS = ("ordinal", "task", "container_image", "container_digest",
            "agent_timeout_multiplier", "time_budget_seconds")


def _planner_source() -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(step for step in document["jobs"]["plan"]["steps"] if step.get("id") == "cohort")
    match = re.search(r"python - <<'PY'\n(.*?)\nPY(\n|$)", step["run"], re.S)
    assert match
    return match.group(1)


@lru_cache(maxsize=1)
def _rows() -> tuple:
    return tuple(load_rows())


def _workspace(tmp_path: Path, tasks: list[str], *, model: str = MODEL, effort: str = "") -> Path:
    (tmp_path / "config").mkdir()
    for name in ("tb2_gt_import_manifest.json", "provider_route.v1.json"):
        shutil.copyfile(ROOT / "config" / name, tmp_path / "config" / name)
    (tmp_path / "swelive-bench").mkdir()
    shutil.copyfile(ROOT / "swelive-bench/manifest.json", tmp_path / "swelive-bench/manifest.json")
    materialize(load_catalog(), _rows(), tmp_path / "swelive-bench/rendered", tasks,
                templates=template_files())
    args = ["--template", str(ROOT / "config/provider_route.v1.json"), "--model", model,
            "--output", str(tmp_path / "plan/provider-route.json")]
    if effort:
        args += ["--reasoning-effort", effort]
    assert render_route_cli(args) == 0
    return tmp_path


def _plan(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "SOURCE_SHA": "f" * 40,
        "TREATMENT": "groundtruth",
        "APPROVE_PAID_RUN": "true",
        "COHORT_STAGE": "gate-one",
        "SINGLE_TASK_ID": "",
        "PRIOR_GATE_RUN_ID": "",
        "MODEL": MODEL,
        "GT_DELIVERY_MODE": "attached",
        "TEMPERATURE": "1.0",
        "STEP_LIMIT": "0",
        "MAX_PARALLEL": "20",
        "SHARD_INDEX": "1",
        "SHARD_COUNT": "1",
        "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
        "PYTHONPATH": str(ROOT),
    })
    env.update(overrides)
    return subprocess.run([sys.executable, "-c", _planner_source()], cwd=tmp_path,
                          capture_output=True, text=True, env=env)


def _outputs(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / "github-output.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


def _plan_json(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "plan/swelive-plan.json").read_text(encoding="utf-8"))


def test_gate_one_plans_the_launch_model_and_attached_delivery(tmp_path: Path) -> None:
    _workspace(tmp_path, [SWELIVE_TASK], effort="high")
    completed = _plan(tmp_path)
    assert completed.returncode == 0, completed.stderr
    plan = _plan_json(tmp_path)
    route, digest = load_route(tmp_path / "plan/provider-route.json")
    assert plan["task_ids"] == [SWELIVE_TASK]
    assert plan["requested_model"] == MODEL
    assert plan["effective_model"] == "openai/" + MODEL
    assert plan["provider_route"] == route and plan["provider_route_sha256"] == digest
    assert plan["gt_delivery_mode"] == "attached" and plan["gt_off_arm"] is False
    assert plan["reasoning_effort"] == "high"
    assert (plan["step_limit"], plan["temperature"]) == (0, 1.0)
    assert (plan["max_parallel"], plan["max_parallel_requested"]) == (1, 20)
    assert plan["shard"] == {"index": 1, "count": 1, "method": "strided"}
    row = plan["matrix"][0]
    assert row["execution_budget_capped"] is False
    assert row["outer_agent_timeout_seconds"] <= row["hosted_execution_cap_seconds"]
    # 355-minute job minus the 145-minute staging/evaluator reserve.
    assert row["hosted_execution_cap_seconds"] == (355 - 145) * 60
    outputs = _outputs(tmp_path)
    assert outputs["model"] == MODEL
    assert outputs["gt_delivery_mode"] == "attached"
    assert outputs["reasoning_effort"] == "high"
    assert outputs["max_parallel"] == "1"
    assert outputs["step_limit"] == "0"
    assert outputs["task_count"] == "1"
    legs = json.loads(outputs["matrix"])["include"]
    assert legs == [{key: row[key] for key in LEG_KEYS} for row in plan["matrix"]]


def test_smoke5_is_the_catalog_head_as_a_named_subset(tmp_path: Path) -> None:
    head = smoke5_task_ids(load_catalog())
    _workspace(tmp_path, head)
    completed = _plan(tmp_path, COHORT_STAGE="smoke5", GT_DELIVERY_MODE="push", MAX_PARALLEL="3")
    assert completed.returncode == 0, completed.stderr
    plan = _plan_json(tmp_path)
    assert plan["task_ids"] == head
    assert plan["cohort_stage"] == "subset:" + ",".join(head)
    assert plan["gt_delivery_mode"] == "push"
    assert plan["max_parallel"] == 3


def test_the_full_split_refuses_one_matrix_above_256_legs(tmp_path: Path) -> None:
    _workspace(tmp_path, [])
    completed = _plan(tmp_path, COHORT_STAGE="all")
    assert completed.returncode != 0
    assert "300 legs exceed the 256-job matrix limit; dispatch shard_count >= 2" in completed.stderr


def test_the_full_split_runs_as_two_strided_shards(tmp_path: Path) -> None:
    tasks = [row["task_id"] for row in load_catalog()["tasks"]]
    shard = shard_tasks(tasks, 2, 2)
    _workspace(tmp_path, shard)
    completed = _plan(tmp_path, COHORT_STAGE="all", SHARD_INDEX="2", SHARD_COUNT="2")
    assert completed.returncode == 0, completed.stderr
    plan = _plan_json(tmp_path)
    assert plan["task_ids"] == shard and plan["task_count"] == 150
    assert plan["stage_task_count"] == 300 and plan["full_task_count"] == 300
    assert plan["max_parallel"] == 20
    assert len(plan["matrix"]) == 150 <= 256
    # The job matrix travels through expressions and env; one environment
    # string may hold at most 128 KiB (MAX_ARG_STRLEN), and a 256-leg shard
    # must fit with room to spare.
    per_leg = max(len(json.dumps(leg, separators=(",", ":")))
                  for leg in json.loads(_outputs(tmp_path)["matrix"])["include"])
    assert per_leg * 256 < 128 * 1024 * 0.8


@pytest.mark.parametrize("overrides, message", [
    ({"GT_DELIVERY_MODE": "shadow"}, "gt_delivery_mode must be attached or push"),
    ({"GT_DELIVERY_MODE": ""}, "gt_delivery_mode must be attached or push"),
    ({"STEP_LIMIT": "-1"}, "step_limit must be a non-negative integer"),
    ({"MAX_PARALLEL": "0"}, "max_parallel must be a positive integer"),
    ({"MAX_PARALLEL": "257"}, "max_parallel must be <= 256"),
    ({"SHARD_COUNT": "0"}, "shard_count must be a positive integer"),
    ({"MODEL": "stealth/other-model"}, "model must be the bare OpenRouter id"),
    ({"TEMPERATURE": "-0.5"}, "temperature must be >= 0"),
])
def test_invalid_launch_inputs_fail_the_plan(tmp_path: Path, overrides: dict, message: str) -> None:
    _workspace(tmp_path, [SWELIVE_TASK])
    completed = _plan(tmp_path, **overrides)
    assert completed.returncode != 0
    assert message in completed.stderr


def test_an_openai_prefixed_model_is_refused(tmp_path: Path) -> None:
    _workspace(tmp_path, [SWELIVE_TASK], model="openai/" + MODEL)
    completed = _plan(tmp_path, MODEL="openai/" + MODEL)
    assert completed.returncode != 0
    assert "model must be the bare OpenRouter id" in completed.stderr


# --- attestation of the swelive launch contract ------------------------------

def _attest(root: Path) -> dict:
    return attest(root, source_sha="f" * 40, task_job_result="success",
                  workflow_run_id="offline", suite=load_suite("swelive"))


def _mutate_plan(root: Path, **fields) -> None:
    path = root / "swelive-plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan.update(fields)
    _write(path, plan)


def test_attestation_passes_on_the_rendered_launch_route(tmp_path: Path) -> None:
    _swelive_fixture(tmp_path)
    receipt = _attest(tmp_path)
    assert receipt["status"] == "PASS", receipt["errors"]
    assert receipt["requested_model"] == REQUESTED


def test_attestation_refuses_a_missing_or_substituted_route(tmp_path: Path) -> None:
    _swelive_fixture(tmp_path)
    (tmp_path / "provider-route.json").unlink()
    assert "planned_provider_route_missing" in _attest(tmp_path)["errors"]

    other = tmp_path / "other"
    _swelive_fixture(other)
    route = json.loads((other / "provider-route.json").read_text(encoding="utf-8"))
    route["retry_pacing"] = {**route["retry_pacing"], "dispatch_stagger_seconds": 1}
    _write(other / "provider-route.json", route)
    errors = _attest(other)["errors"]
    assert "planned_provider_route_mismatch" in errors


def test_attestation_binds_parallelism_to_the_recorded_launch_request(tmp_path: Path) -> None:
    _swelive_fixture(tmp_path)
    _mutate_plan(tmp_path, max_parallel=20)  # one task cannot run 20-wide
    assert "planned_parallelism_mismatch" in _attest(tmp_path)["errors"]
    _mutate_plan(tmp_path, max_parallel=1, max_parallel_requested=0)
    assert "planned_parallelism_mismatch" in _attest(tmp_path)["errors"]


@pytest.mark.parametrize("fields", [
    {"gt_delivery_mode": "shadow"},
    {"gt_delivery_mode": None},
    {"step_limit": -1},
    {"temperature": "1.0"},
    {"gt_off_arm": True},
])
def test_attestation_refuses_an_invalid_launch_contract(tmp_path: Path, fields: dict) -> None:
    _swelive_fixture(tmp_path)
    _mutate_plan(tmp_path, **fields)
    assert "planned_launch_contract_invalid" in _attest(tmp_path)["errors"]


def test_attestation_binds_the_catalog_and_the_shard(tmp_path: Path) -> None:
    _swelive_fixture(tmp_path)
    _mutate_plan(tmp_path, catalog={"sha256": "0" * 64})
    assert "planned_catalog_identity_mismatch" in _attest(tmp_path)["errors"]
    _mutate_plan(tmp_path, catalog={"sha256": catalog_sha256()},
                 shard={"index": 2, "count": 2, "method": "strided"})
    errors = _attest(tmp_path)["errors"]
    assert "planned_shard_invalid" in errors


def test_shard_rederivation_is_exact() -> None:
    tasks = [f"t{i}" for i in range(10)]
    errors: list[str] = []
    plan = {"shard": {"index": 2, "count": 3, "method": "strided"}, "stage_task_count": 10}
    assert attest_deepswe._swelive_shard(plan, tasks, errors) == ["t1", "t4", "t7"]
    assert errors == []
    plan["stage_task_count"] = 9
    assert attest_deepswe._swelive_shard(plan, tasks, errors) == []
    assert errors == ["planned_shard_invalid"]


def test_task_legs_read_only_the_projected_matrix_keys() -> None:
    used = set(re.findall(r"matrix\.([a-z_]+) \}\}", WORKFLOW.read_text(encoding="utf-8")))
    assert used == set(LEG_KEYS)


def test_deepswe_keeps_its_checked_in_route_and_fixed_parallel_rail() -> None:
    source = Path(attest_deepswe.__file__).read_text(encoding="utf-8")
    assert attest_deepswe.DEEPSWE_ROUTE_PATH == ROOT / "config" / "provider_route.v1.json"
    assert 'plan.get("max_parallel") != min(20, len(expected))' in source
    assert "provider_route_deepseek" not in source
