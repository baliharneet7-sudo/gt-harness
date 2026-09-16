from pathlib import Path

from scripts.swebench.patch_transport import normalize_patch_transport


def test_missing_terminal_newline_is_restored_without_other_changes() -> None:
    patch = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new"
    assert normalize_patch_transport(patch) == patch + "\n"


def test_existing_terminal_newline_is_preserved() -> None:
    patch = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert normalize_patch_transport(patch) == patch


def test_live_workflow_uses_lossless_patch_transport() -> None:
    workflow = Path(".github/workflows/live_lite_inference.yml").read_text(
        encoding="utf-8"
    )
    assert "patch = normalize_patch_transport(raw_patch)" in workflow
    assert '"model_patch": patch.strip()' not in workflow


def test_eval_workflow_reuses_exact_source_run_and_requires_all_grades() -> None:
    workflow = Path(".github/workflows/live_lite_eval.yml").read_text(encoding="utf-8")
    assert "source_workflow_run_id:" in workflow
    assert "run-id: ${{ inputs.source_workflow_run_id }}" in workflow
    assert "normalize_patch_transport" in workflow
    assert "Require an official grade for every prediction" in workflow
