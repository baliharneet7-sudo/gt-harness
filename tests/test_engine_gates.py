"""ENGINE gates — provider-free checks that prevent the class of bug that broke
the witness run: journal-schema corruption, external-looking GT labels in model
bytes, and empty postflight payloads."""
from __future__ import annotations

import subprocess

import pytest

from gt_engine.engine.contracts import (
    ActionKind,
    ActionRequest,
    Decision,
    EvidenceArtifact,
    Fidelity,
    InterceptionDecision,
)
from gt_engine.engine.observe import compile_observation
from gt_engine.engine.runner import (
    _covering_red_artifact,
    _git_changed_py,
    _syntax_artifact,
)
from gt_engine.event_journal import verify_event_journal


def _request():
    return ActionRequest(
        action_id="call_1", kind=ActionKind.SHELL, arguments={},
        literal_shell_form="pytest tests", snapshot_token="tok-1",
        configuration_digest="cfg-1", requested_fidelity=Fidelity.RAW,
    )


def _fact(owner="syntax_result", model_visible=True, content=None):
    return EvidenceArtifact(
        artifact_id="ev-1", owner=owner, semantics="syntax",
        content=content or {"file": "src/x.py", "ok": True},
        anchors=("src/x.py:1",), producer="py_ast", producer_version="1",
        freshness_revision="rev-9", coverage="complete",
        model_visible=model_visible,
    )


# --- Gate 1: engine_delivery events must keep the journal valid ------------


def test_engine_delivery_journal_schema_valid(tmp_path):
    """The runner's engine_delivery append must not break the tamper chain.

    Regression: passing schema='gt.engine.delivery_receipt.v1' OVERRIDES
    ExternalStateStore's forced gt.event.v1 and made verify_event_journal
    report 'unsupported or missing schema' (research_valid=false in the
    witness run)."""
    from gt_engine.miniswe_integration import ExternalStateStore

    store = ExternalStateStore(tmp_path, "task-x")
    store.append(
        "engine_delivery",
        delivery_id="d-0001",
        action_id="call_1",
        decision="pass_through",
        final_observation_sha256="a" * 64,
    )
    receipt = store.receipt()
    verification = verify_event_journal(
        store.path,
        event_count=receipt["event_count"],
        event_head=receipt["event_head"],
    )
    assert verification.valid, verification.issues


def test_schema_override_breaks_journal_documented(tmp_path):
    """The trap is real: a payload schema kwarg corrupts the chain."""
    from gt_engine.miniswe_integration import ExternalStateStore

    store = ExternalStateStore(tmp_path, "task-x")
    store.append(
        "engine_delivery",
        schema="gt.engine.delivery_receipt.v1",  # the bug that shipped
        delivery_id="d-0001",
    )
    verification = verify_event_journal(store.path)
    assert not verification.valid
    assert any("unsupported or missing schema" in i for i in verification.issues)


# --- Gate 2: model-visible bytes carry no external 'GT' framing -------------


def test_observation_render_has_no_gt_sentinels():
    """The engine's model bytes must never say 'gt-engine'/'gt-fact'/'GT_'.
    External labeling makes the model treat the bytes as out-of-band info."""
    observation = compile_observation(
        _request(),
        InterceptionDecision(decision=Decision.AUGMENT, reason="postflight"),
        raw_result="tests passed",
        evidence=(_fact(),),
        receipt_id="rcpt-1",
    )
    rendered = observation.render()
    lowered = rendered.lower()
    assert "gt-engine" not in lowered
    assert "gt-fact" not in lowered
    assert "gt_" not in lowered
    assert "gt_" not in rendered
    # raw preserved exactly, facts present in a neutral block
    assert "tests passed" in rendered
    assert "<result" in rendered and "</result>" in rendered
    assert "src/x.py" in rendered
    assert 'decision="augment"' in rendered


# --- Gate 3: postflight producers emit real facts ----------------------------


def test_syntax_artifact_positive(tmp_path):
    path = tmp_path / "good.py"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")
    artifact = _syntax_artifact(str(path), str(tmp_path))
    assert artifact is not None
    assert artifact.owner == "syntax_result"
    assert artifact.content["ok"] is True
    assert artifact.model_visible
    assert artifact.coverage == "complete"


def test_syntax_artifact_reports_error(tmp_path):
    path = tmp_path / "bad.py"
    path.write_text("def f(:\n", encoding="utf-8")
    artifact = _syntax_artifact(str(path), str(tmp_path))
    assert artifact is not None
    assert artifact.content["ok"] is False
    assert "line" in artifact.content["detail"].lower()


def test_syntax_artifact_omits_non_python(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("anything", encoding="utf-8")
    assert _syntax_artifact(str(path), str(tmp_path)) is None


def test_covering_red_for_test_command():
    artifact = _covering_red_artifact("pytest tests/", "1 passed", 0)
    assert artifact is not None
    assert artifact.owner == "covering_red"
    assert artifact.content["outcome"] == "passed"
    failed = _covering_red_artifact("pytest tests/", "1 failed", 1)
    assert failed.content["outcome"] == "failed"


def test_covering_red_absent_for_plain_read():
    assert _covering_red_artifact("cat src/x.py", "content", 0) is None


def test_git_changed_py_detects_edits(tmp_path):
    git = subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True)
    if git.returncode != 0:
        pytest.skip("git unavailable")
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                   capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"],
                   capture_output=True)
    (src / "x.py").write_text("x = 2\n", encoding="utf-8")
    changed = _git_changed_py(str(tmp_path))
    assert any("x.py" in p for p in changed)


def test_git_changed_py_omits_non_repo(tmp_path):
    assert _git_changed_py(str(tmp_path)) == ()


# --- Gate 4: all 17 DIRECT features are wired --------------------------------


def test_all_seventeen_direct_features_wired():
    """Every DIRECT feature has a registered owner and a producer path.

    The ENGINE is the action-to-observation interface; all 17 DIRECT features
    must be able to fire on their triggers (per-task firing is then gated by
    the actual actions a task produces). caller_contract is REMOVE by design.
    """
    from scripts.engine_feature_census import census

    result = census()
    assert result["all_17_wired"], result
    assert result["facts_ok"] == 9
    assert result["caps_ok"] == 7


def test_all_registered_fact_owners_are_in_inventory():
    from gt_engine.engine.runner import ENGINE_FACT_OWNERS
    from scripts.engine_129_audit import build_transition_rows

    rows, _ = build_transition_rows()
    inventory = {row["identity"] for row in rows}
    for owner in ENGINE_FACT_OWNERS:
        assert owner in inventory, f"{owner} not in the 129-row inventory"
        row = next(r for r in rows if r["identity"] == owner)
        assert row["category"] == "FACT", f"{owner} is not a FACT identity"
