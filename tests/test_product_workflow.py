from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from scripts.validate_product_workflow import validate_workflow

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deepswe_gt_harness_product.yml"
PAID_WORKFLOW = (
    ROOT / ".github" / "workflows" / "deepswe_gt_harness_product_p0731.yaml"
)


def test_product_workflow_is_reachable_pinned_and_provider_free() -> None:
    assert validate_workflow(WORKFLOW, root=ROOT) == []


def test_full_suite_receives_the_verified_producer_path() -> None:
    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["provider-free-product"]["steps"]
    suite = next(step for step in steps if step.get("name") == "Run the full Python suite serially")
    assert suite.get("env", {}).get("GT_INDEX_BINARY") == "/opt/groundtruth/gt-index/gt-index"


def test_product_workflow_rejects_bypassing_manifest_pin_resolution(
    tmp_path: Path,
) -> None:
    altered = tmp_path / "workflow.yml"
    altered.write_text(
        WORKFLOW.read_text(encoding="utf-8").replace(
            "${{ steps.product-pins.outputs.review_inbox_commit }}",
            "ac45a546cb3c39d5b8ce0f630b5c8ce2ef572685",
        )
        + "\n# steps.product-pins.outputs.review_inbox_commit\n",
        encoding="utf-8",
    )
    assert "product_manifest_pins_unreachable" in validate_workflow(altered, root=ROOT)


def test_only_closed_supported_workflow_set_is_active() -> None:
    # git ls-files, not glob. GitHub runs workflows from the COMMITTED ref, so
    # the working tree is a proxy for the property and not the property: an
    # untracked .yml never reaches Actions, and globbing calls it a
    # supply-chain event anyway. That false red is not the safe direction - it
    # is the condition that trains a hurried operator to wave the gate through,
    # and this is the gate that must not be waved through. The staging area is
    # included on purpose: something staged is one command from being the ref.
    listed = subprocess.run(
        ["git", "ls-files", "--", ".github/workflows/*.yml", ".github/workflows/*.yaml"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    active = sorted(PurePosixPath(line).name for line in listed.splitlines() if line.strip())
    # The set stays closed on purpose: an unreviewed workflow appearing here
    # is a supply-chain event, not a detail. Everything retired lives in
    # `.github/workflows-archive/`, which Actions does not register, so an
    # archived lane cannot be dispatched, triggered, called or spent -- see
    # that directory's README. Each name below is admitted individually,
    # never by loosening the rule:
    #
    # `deepswe_cache_images.yml` / `tb2_cache_images.yml` -- the two image
    # mirrors. workflow_dispatch-only, touch no paid path, and exist to cut
    # task-image pull latency.
    #
    # `deepswe_gt_harness_product.yml` -- the provider-free acceptance gate
    # itself. workflow_call/workflow_dispatch only, holds no secret, and
    # `scripts/validate_product_workflow.py` fails it closed if a manifest pin
    # or the zero-spend assertion ever becomes unreachable from it.
    #
    # `deepswe_gt_harness_product_p0731.yaml` -- the paid DeepSWE lane. It is
    # approval-gated by its own `approve_paid_run` input, runs the readiness
    # gate above before any provider call, and is the caller the product
    # workflow's own reachability step re-validates.
    #
    # `swelive_gt_harness_paid.yaml` -- the reviewed paid SWE-bench-Live smoke
    # path: workflow_dispatch-only, approval-gated by its own input, and bound
    # to the manifest pins.
    #
    # `swebench_live_lite_full.yml` -- the SWE-bench-Live dispatcher, and the
    # only caller of `swelive_gt_harness_paid.yaml`. Retiring it would strand
    # the paid lane behind a manual dispatch with hand-typed inputs, which is
    # the shape that produced the wrong-arm runs this gate exists to prevent.
    #
    # `tb2_miniswe_central.yml` -- the TB2 central lane, and a caller of the
    # product workflow. It carries the hardened secret sanitation (the U+FEFF
    # regression in `tests/test_env_hardening.py`) and is the only supported
    # way to run TB2 with GT on.
    #
    # `task_progress.yml` -- the progress monitor. workflow_call-only, takes no
    # secret, spends nothing of its own, and is a declared dependency of the
    # two central lanes and the engine; `tests/test_benchmark_progress.py` and
    # `tests/test_benchmark_workflow_dependencies.py` both bind to it.
    #
    # `central_provider_free.yml` -- the provider-free half of the DeepSWE
    # central lane, called by `deepswe_miniswe_central.yml`. No secret, no
    # provider call.
    #
    # `deepswe_miniswe_central.yml` and `tb2_miniswe_engine.yml` -- admitted
    # because campaign 1 hardened them (adapter import guard, monitor timeout
    # ownership, ruff target guard) and the dependency tests in
    # `tests/test_benchmark_workflow_dependencies.py` assert on their text.
    # Archiving them would delete the subject of a passing regression test
    # rather than the risk the test describes.
    assert active == [
        "central_provider_free.yml",
        "deepswe_cache_images.yml",
        "deepswe_gt_harness_product.yml",
        "deepswe_gt_harness_product_p0731.yaml",
        "deepswe_miniswe_central.yml",
        "swebench_live_lite_full.yml",
        "swelive_gt_harness_paid.yaml",
        "task_progress.yml",
        "tb2_cache_images.yml",
        "tb2_miniswe_central.yml",
        "tb2_miniswe_engine.yml",
    ]


def test_paid_product_workflow_is_reachable_pinned_and_approval_gated() -> None:
    assert validate_workflow(PAID_WORKFLOW, root=ROOT) == []


def test_readiness_workflows_enforce_full_suite_pinned_sources_and_dark_gate() -> None:
    provider_free = WORKFLOW.read_text(encoding="utf-8")
    paid = PAID_WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest -q -ra tests" in provider_free
    assert "repository: abhigyanpatwari/GitNexus" in provider_free
    assert "ref: 7e993ab8972386294fb96bf14a8665d0b5325397" in provider_free
    assert "fetch-depth: 0" in provider_free
    assert "e56c7ef17eaffee36c80ff4dde4f0cd3991c4dcd" in provider_free
    assert "7bbbc9d0b7f02f8cdaab79ad82ee86884b738eb5" in provider_free
    assert "+refs/heads/*:refs/remotes/origin/*" in provider_free
    assert "PRODUCER_PATH=\"/opt/groundtruth/gt-index/gt-index\"" in provider_free
    assert "sha256sum --check --strict" in provider_free
    assert 're.fullmatch(r"[0-9a-f]{64}", pins["producer_sha"])' in provider_free
    assert 'Path("artifacts/product-closeout").mkdir(parents=True, exist_ok=True)' in provider_free
    assert "git config --global user.email \"gt-harness-ci@example.invalid\"" in provider_free
    assert "git config core.hooksPath \"${GITHUB_WORKSPACE}/.githooks\"" in provider_free
    assert "python scripts/verify_feature_matrix.py" in provider_free
    assert "python scripts/gt_audit.py" in paid
    assert "python scripts/gt_live_gate.py" in paid
    assert "--require-complete-census" in paid
    assert "python -m scripts.attest_deepswe" in paid
    assert "--output attestation/feature-matrix.json" in paid
    assert "cp gt_finalstand/feature_matrix.json" not in paid
    assert "AUDIT_EXIT=0" in paid
    assert '--workflow-run-id "$GITHUB_RUN_ID"' in paid
    assert "attestation/gt-audit.json" in paid
    assert "attestation/gt-live-gate.json" in paid
    assert "attestation/feature-matrix.json" in paid
    assert "cohort_stage" in paid
    assert "remaining-19" in paid
    assert "validate_prior_gate" in paid
    assert "diagnose_benchmark_run" in paid
    assert "task_selection" not in paid
    assert "if: always()" in paid.split(
        "- name: Verify all DeepSWE outcomes and product receipts", 1
    )[1].split("- name: Upload final DeepSWE GT Harness attestation", 1)[0]
    assert "from gt_harness.runtime_receipts import" not in paid
    assert '"onnxruntime==1.20.1" "tokenizers==0.23.1"' in paid
    assert "Install pinned attestation test dependencies" in paid
    assert "--require-hashes -r config/product-requirements.lock" in paid.split(
        "Install pinned attestation test dependencies", 1
    )[1]
    assert "str(MiniSweAgent._gt_wheel())" in paid
    assert 'python -c "import groundtruth.runtime.gateway"' in paid
    assert "max_timeout_sec=stage_timeout_cap_seconds(stage)" in paid
    assert '"agent_timeout_multiplier": budget["timeout_multiplier"]' in paid
    assert '--agent-timeout-multiplier "${{ matrix.agent_timeout_multiplier }}"' in paid
    assert "--agent-timeout-multiplier 1.0" not in paid


def test_paid_smoke_requires_all_exact_task_image_digests_before_provider_gate() -> None:
    paid = PAID_WORKFLOW.read_text(encoding="utf-8")
    assert '"container_image": bundle_task["container_image"]' in paid
    assert '"container_digest": bundle_task["container_digest"]' in paid
    assert "image_digest_gate:" in paid
    assert "needs: [plan, readiness, image_digest_gate]" in paid
    assert "needs: [plan, readiness, image_digest_gate, provider_gate]" in paid
    assert "Verify all exact task-image manifests without provider access" in paid
    assert 'docker buildx imagetools inspect --raw "$IMAGE_REF"' in paid
    assert 'test "sha256:${OBSERVED}" = "${DIGEST}"' in paid
    assert "Pull and verify the exact task image" in paid
    assert 'docker pull "${SOURCE_IMAGE}@${SOURCE_DIGEST}"' in paid
    assert "image_cache:" not in paid
    assert "ghcr.io/" not in paid
    assert "secrets.OPENROUTER_API_KEY" not in paid.split(
        "  image_digest_gate:", 1
    )[1].split(
        "  provider_gate:", 1
    )[0]
