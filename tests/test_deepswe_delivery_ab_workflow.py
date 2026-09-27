"""Structure of the DeepSWE push-vs-attached workflow and its route renderer."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from scripts import provider_preflight
from scripts.render_provider_route import render_route
from scripts.resolve_harbor_budget import canonical_task_config_bytes

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deepswe_gt_delivery_ab.yml"
TEMPLATE = json.loads((ROOT / "config" / "provider_route.v1.json").read_text(encoding="utf-8"))


def _workflow() -> tuple[str, dict]:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def _declared_cli_kwargs() -> set[str]:
    tree = ast.parse((ROOT / "eval" / "miniswe_agent.py").read_text(encoding="utf-8"))
    kwargs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "CliFlag":
            for keyword in node.keywords:
                if keyword.arg == "kwarg" and isinstance(keyword.value, ast.Constant):
                    kwargs.add(keyword.value.value)
    return kwargs


# --- route renderer ------------------------------------------------------------

def _load(tmp_path: Path, route: dict) -> dict:
    path = tmp_path / "route.json"
    path.write_text(json.dumps(route), encoding="utf-8")
    loaded, _ = provider_preflight.load_route(path)
    return loaded


def test_render_without_inputs_keeps_the_template_route(tmp_path):
    route = _load(tmp_path, render_route(TEMPLATE))
    assert route["model"] == TEMPLATE["model"]
    assert route["provider_routing"] == TEMPLATE["provider_routing"]
    assert route["pricing"] == TEMPLATE["pricing"]
    assert route["expected_quantization"] == "fp8"
    assert "reasoning_effort" not in route


def test_render_model_override_drops_template_pricing_and_lock(tmp_path):
    route = _load(tmp_path, render_route(TEMPLATE, model="openai/gpt-5.6-terra",
                                         reasoning_effort="medium"))
    assert route["model"] == "openai/gpt-5.6-terra"
    assert route["provider_routing"] == {}
    assert "pricing" not in route and "expected_quantization" not in route
    assert route["reasoning_effort"] == "medium"
    assert route["route_id"].startswith("openrouter-openai-gpt-5-6-terra-")


def test_render_provider_inputs_build_the_routing(tmp_path):
    route = _load(tmp_path, render_route(TEMPLATE, model="stealth/space-bunny-alpha",
                                         provider_only="stealth", quantization="fp16"))
    assert route["provider_routing"] == {"only": ["stealth"], "allow_fallbacks": False,
                                         "require_parameters": True, "quantizations": ["fp16"]}
    assert "expected_quantization" not in route


def test_render_route_id_is_deterministic():
    assert render_route(TEMPLATE, model="x/y")["route_id"] == render_route(TEMPLATE, model="x/y")["route_id"]
    assert render_route(TEMPLATE, model="x/y")["route_id"] != render_route(
        TEMPLATE, model="x/y", reasoning_effort="max")["route_id"]


# --- workflow structure ----------------------------------------------------------

def test_workflow_parses_with_expected_jobs():
    _, doc = _workflow()
    assert list(doc["jobs"]) == ["plan", "readiness", "readiness_binding", "mirror_plan", "mirror",
                                 "image_digest_gate", "provider_gate", "task", "aggregate"]


def test_task_images_are_mirrored_before_the_digest_gate():
    # Public ECR throttles anonymous reads per runner IP; the full cohort
    # (run 36346438031) could not read its manifests from one runner.
    _, doc = _workflow()
    mirror = doc["jobs"]["mirror"]
    assert mirror["permissions"]["packages"] == "write"
    assert "crane" in str(mirror["steps"]) and "@${DIGEST}" in str(mirror["steps"])
    assert "mirror" in doc["jobs"]["image_digest_gate"]["needs"]


def test_no_gt_off_arm_anywhere():
    text, _ = _workflow()
    assert "--gt-off" not in text
    assert "integration_mode=off" not in text
    assert "gt_off\"" not in text and "gt_off:" not in text


def test_paid_jobs_are_gated_on_explicit_approval():
    _, doc = _workflow()
    for job in ("provider_gate", "task", "aggregate"):
        assert "inputs.approve_paid_run == true" in doc["jobs"][job]["if"]
    dispatch = doc[True]["workflow_dispatch"]["inputs"]
    assert dispatch["approve_paid_run"]["default"] is False


def test_every_ak_knob_is_declared_on_the_agent():
    text, _ = _workflow()
    used = set(re.findall(r"--ak ([a-z_]+)=", text))
    assert {"gt_delivery_mode", "step_limit", "max_iterations", "temperature"} <= used
    assert used <= _declared_cli_kwargs()


def test_task_artifacts_and_job_names_carry_the_leg_id():
    text, doc = _workflow()
    upload = [step for step in doc["jobs"]["task"]["steps"]
              if "upload-artifact" in str(step.get("uses", ""))]
    assert upload and all("matrix.leg_id" in step["with"]["name"] for step in upload)
    assert '--job-name "deepswe-gt-ab-${GITHUB_RUN_ID}-${LEG_ID}"' in text
    assert "deepswe20-task-" not in text
    assert "GT_REASONING_EFFORT: ${{ needs.plan.outputs.reasoning_effort }}" in text


# --- the embedded plan script, run hermetically --------------------------------

TASK_TOML = b'[metadata]\nlanguage = "python"\n[agent]\ntimeout_sec = 5400.0\n'


def _fake_checkout(tmp_path: Path, tasks: list[str]) -> Path:
    work = tmp_path / "work"
    bench = work / "deepswe-bench"
    for task in tasks:
        (bench / "tasks" / task).mkdir(parents=True)
        (bench / "tasks" / task / "task.toml").write_bytes(TASK_TOML)
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(bench)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True,
                         text=True).stdout.strip()
    digest = hashlib.sha256(canonical_task_config_bytes(TASK_TOML)).hexdigest()
    catalog = {
        "schema": "gt.deepswe_task_catalog.v1", "benchmark_sha": sha,
        "task_config_identity": "sha256_canonical_lf_v1", "task_order_sha256": "0" * 64,
        "tasks": [{"task_id": task, "language": "python", "container_image": "img",
                   "container_digest": "sha256:" + "1" * 64, "task_config_sha256": digest}
                  for task in tasks],
    }
    (work / "config").mkdir()
    (work / "config" / "deepswe_task_catalog_v1.json").write_text(json.dumps(catalog), encoding="utf-8")
    (work / "plan").mkdir()
    (work / "plan" / "provider-route.json").write_text(json.dumps(render_route(TEMPLATE)),
                                                      encoding="utf-8")
    return work


def _run_plan(work: Path, **overrides: str) -> subprocess.CompletedProcess:
    _, doc = _workflow()
    run = next(step for step in doc["jobs"]["plan"]["steps"] if step.get("id") == "cohort")["run"]
    script = textwrap.dedent(run.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0])
    env = dict(os.environ, SOURCE_SHA="a" * 40, APPROVE_PAID_RUN="false", TASKS_INPUT="t-one,t-two",
               ARMS_INPUT="both", N_RUNS="2", MAX_PARALLEL="3", TEMPERATURE="1.0",
               STEP_LIMIT="300", PROVIDER_FAILURE_THRESHOLD="10",
               GITHUB_OUTPUT=str(work / "out.txt"), PYTHONPATH=str(ROOT))
    env.update(overrides)
    return subprocess.run([sys.executable, "-c", script], cwd=work, env=env,
                          capture_output=True, text=True, timeout=120)


def test_plan_interleaves_arms_task_major_with_unique_leg_ids(tmp_path):
    work = _fake_checkout(tmp_path, ["t-one", "t-two"])
    done = _run_plan(work)
    assert done.returncode == 0, done.stderr
    plan = json.loads((work / "plan" / "delivery-ab-plan.json").read_text(encoding="utf-8"))
    assert [leg["leg_id"] for leg in plan["legs"]] == [
        "t-one__push__r1", "t-one__attached__r1", "t-one__attached__r2", "t-one__push__r2",
        "t-two__push__r1", "t-two__attached__r1", "t-two__attached__r2", "t-two__push__r2",
    ]
    assert [leg["stagger_slot"] for leg in plan["legs"]] == [0, 1, 2, 0, 1, 2, 0, 1]
    assert all(leg["step_limit"] == 300 for leg in plan["legs"])
    assert plan["gt_off_arm"] is False
    outputs = (work / "out.txt").read_text(encoding="utf-8")
    assert "leg_count=8\n" in outputs and "step_limit=300\n" in outputs


def test_plan_refuses_unknown_tasks_and_oversized_matrices(tmp_path):
    work = _fake_checkout(tmp_path, ["t-one", "t-two"])
    assert _run_plan(work, TASKS_INPUT="t-one,zz").returncode != 0
    done = _run_plan(work, N_RUNS="200")
    assert done.returncode != 0 and "256-job matrix limit" in done.stderr


def test_control10_matches_the_frozen_control_and_the_catalog():
    _, doc = _workflow()
    run = next(step for step in doc["jobs"]["plan"]["steps"] if step.get("id") == "cohort")["run"]
    control = re.findall(r'^\s+"([a-z0-9-]+)",$', run.split("CONTROL10 = [", 1)[1].split("]", 1)[0],
                         re.MULTILINE)
    catalog = json.loads((ROOT / "config" / "deepswe_task_catalog_v1.json").read_text(encoding="utf-8"))
    assert len(control) == 10 and set(control) <= {row["task_id"] for row in catalog["tasks"]}


@pytest.mark.parametrize("name", ["plan", "task", "aggregate"])
def test_jobs_keep_the_certified_action_pins(name):
    _, doc = _workflow()
    for step in doc["jobs"][name]["steps"]:
        uses = step.get("uses", "")
        if uses:
            assert re.search(r"@[0-9a-f]{40}$", uses), uses
