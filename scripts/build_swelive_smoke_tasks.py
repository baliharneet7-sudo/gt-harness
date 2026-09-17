"""Build the frozen five-task SWE-bench-Live Lite smoke package."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks/data/swebench_live_lite.jsonl"
TEMPLATE = ROOT / "swelive-bench/tasks/aiogram__aiogram-1594/tests"
DIGESTS = {
    "aiogram__aiogram-1594": "sha256:4461f94ae2293dcbabcd71b2425a9d00f9d88dba0e0203fecba6aee311199c2d",
    "amoffat__sh-744": "sha256:0ab5f01f2c45fe84813deec1dd1478917ba63b9a2a7443dc43a065bd186e14c3",
    "arviz-devs__arviz-2413": "sha256:ba0f72743455df00addcdfdfe326e3645761a019b166652318a5c828f1231a80",
    "aws-cloudformation__cfn-lint-3749": "sha256:f66404b8fee73c41820929afe4778e2c0dbba735a950ad9a042ae9e2ea649d29",
    "aws-cloudformation__cfn-lint-3764": "sha256:3a1787a94d8589771a6306984fb0826498eb1a63e14ca87c4826e6382f092cc4",
}


def image_name(instance: str) -> str:
    owner, rest = instance.split("__", 1)
    repo, pr = rest.rsplit("-", 1)
    return f"starryzhang/sweb.eval.x86_64.{owner}_1776_{repo}-{pr}"


def q(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def build(output: Path) -> dict:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()[:5]]
    if [row["instance_id"] for row in rows] != list(DIGESTS):
        raise RuntimeError("frozen smoke cohort drifted")
    template_files = {name: (TEMPLATE / name).read_bytes() for name in ("test.sh", "grade.py")}
    tasks_dir = output / "tasks"
    if tasks_dir.exists():
        shutil.rmtree(tasks_dir)
    tasks_dir.mkdir(parents=True)
    manifest_rows = []
    for ordinal, row in enumerate(rows, 1):
        task_id = row["instance_id"]
        digest = DIGESTS[task_id]
        image = image_name(task_id)
        task = tasks_dir / task_id
        (task / "environment").mkdir(parents=True)
        (task / "tests").mkdir()
        repo = row["repo"]
        base = row["base_commit"]
        pull = int(row["pull_number"])
        statement = row["problem_statement"].strip()
        task_toml = f'''schema_version = "1.3"
artifacts = ["/logs/artifacts/model.patch"]
[task]
name = "swelive/{task_id}"
description = {q(f"SWE-bench-Live Lite task {task_id} ({repo} PR {pull})")}
authors = []
keywords = ["swe-bench-live", "lite", "python"]
[metadata]
task_id = {q(task_id)}
language = "python"
repository_url = {q("https://github.com/" + repo)}
base_commit_hash = {q(base)}
pull_number = {pull}
dataset = "SWE-bench-Live/SWE-bench-Live"
dataset_split = "lite"
log_parser = {q(row.get("log_parser", "pytest"))}
[verifier]
network_mode = "public"
environment_mode = "separate"
timeout_sec = 900.0
[verifier.env]
[verifier.environment]
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 8192
storage_mb = 20480
workdir = "/testbed"
[[verifier.collect]]
command = {q(f"cd /testbed && mkdir -p /logs/artifacts && git config --global --add safe.directory '*' && {{ [ -d .git ] || {{ g=$(find . -maxdepth 2 -mindepth 2 -type d -name .git -print -quit); [ -n \"$g\" ] && cd \"${{g%/.git}}\"; }}; }} && {{ git add -N -A 2>/dev/null || true; git diff --binary {base} > /logs/artifacts/model.patch; }}")}
timeout_sec = 300.0
[agent]
network_mode = "no-network"
timeout_sec = 1800.0
[environment]
build_timeout_sec = 1800.0
docker_image = {q(image + "@" + digest)}
os = "linux"
cpus = 2
memory_mb = 8192
storage_mb = 20480
gpus = 0
mcp_servers = []
workdir = "/testbed"
[environment.env]
[solution.env]
'''
        (task / "task.toml").write_text(task_toml, encoding="utf-8", newline="\n")
        (task / "instruction.md").write_text(statement + "\n", encoding="utf-8", newline="\n")
        docker = f"FROM {image}@{digest}\nWORKDIR /testbed\n"
        (task / "environment/Dockerfile").write_text(docker, encoding="utf-8", newline="\n")
        (task / "tests/Dockerfile").write_text(
            docker + "COPY test.sh run_tests.sh grade.py spec.json test_patch.diff /tests/\nRUN chmod +x /tests/test.sh /tests/run_tests.sh\n",
            encoding="utf-8", newline="\n",
        )
        for name in ("test.sh", "grade.py"):
            (task / "tests" / name).write_bytes(template_files[name])
        commands = row.get("test_cmds") or ["pytest -rA"]
        (task / "tests/run_tests.sh").write_text("#!/bin/bash\n" + "\n".join(commands) + "\n", encoding="utf-8", newline="\n")
        (task / "tests/test_patch.diff").write_text(row["test_patch"], encoding="utf-8", newline="\n")
        spec = {
            "instance_id": task_id, "repo": repo, "pull_number": str(pull),
            "base_commit": base, "test_cmds": commands,
            "log_parser": row.get("log_parser", "pytest"),
            "fail_to_pass": row.get("FAIL_TO_PASS", []),
            "pass_to_pass": row.get("PASS_TO_PASS", []),
            "container_image": image, "container_digest": digest,
        }
        (task / "tests/spec.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
        (task / "image.lock.json").write_text(json.dumps({"schema":"swelive-bench.image-lock/v1","instance_id":task_id,"container_image":image,"container_digest":digest,"docker_image_ref_used_in_task_toml":image+"@"+digest}, indent=2)+"\n", encoding="utf-8", newline="\n")
        config_hash = hashlib.sha256((task / "task.toml").read_bytes()).hexdigest()
        manifest_rows.append({"ordinal":ordinal,"task_id":task_id,"language":"python","base_commit":base,"task_config_sha256":config_hash,"container_image":image,"container_digest":digest})
    manifest = {"schema":"swelive-bench.manifest/v1","adapter":"swe-bench-live-lite","pier_version_target":"0.3.1","task_toml_schema_version":"1.3","task_config_identity":"sha256_canonical_lf_v1","dataset":{"name":"SWE-bench-Live/SWE-bench-Live","split":"lite","source_snapshot":"benchmarks/data/swebench_live_lite.jsonl first five rows","image_name_rule":"starryzhang/sweb.eval.x86_64.<owner>_1776_<repo-pr>"},"tasks":manifest_rows}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8", newline="\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "swelive-bench")
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
