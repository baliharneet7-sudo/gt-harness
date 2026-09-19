"""The no-op LSP row must say WHICH kind of nothing it promoted.

``lsp_promotion DEGRADED terminal_no_op:nothing_promotable`` is printed
identically for a task with no LSP-serviceable language (extract-elf is a
C/ELF task; run 35293191813 reported exactly this and was correct) and for a
task whose serviceable language was never promoted, which is a real fault.
The promotion receipts separate the two, so the reader is not left guessing.

These tests pin the annotation only. The capability state, the "did this
work" column, the did-not-work call-out and the exit code are gt_session's
and run_diagnostics' to decide, and stay byte-identical either way.
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.diagnose_benchmark_run as diagnose

_NO_OP_EVIDENCE = "terminal_no_op:nothing_promotable"


def _capability_row(task_id: str, **overrides: object) -> dict:
    row = {
        "task_id": task_id,
        "capability": "lsp_promotion",
        "state": "DEGRADED",
        "required": True,
        "declared": True,
        "initialized": True,
        "triggered": True,
        "delivered": False,
        "refused": False,
        "degraded": True,
        "verified": False,
        "evidence": _NO_OP_EVIDENCE,
    }
    row.update(overrides)
    return row


def _working_row(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "capability": "dense_retrieval",
        "state": "WORKING",
        "required": True,
        "declared": True,
        "initialized": True,
        "triggered": True,
        "delivered": True,
        "refused": False,
        "degraded": False,
        "verified": True,
        "evidence": "dense_index_ready_query_ready",
    }


def _plant_task(root: Path, task_id: str, receipts: list[dict] | None) -> Path:
    """One task directory shaped like a Harbor artifact tree.

    diagnose_artifact_root hands back rows keyed by task id and drops the path
    it read them from, so the diagnostics document is what re-anchors the task
    directory that holds the receipts.
    """
    agent = root / task_id / "agent"
    (agent).mkdir(parents=True, exist_ok=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": task_id}),
        encoding="utf-8",
    )
    for index, receipt in enumerate(receipts or []):
        receipt_dir = agent / "gt-state" / task_id / "lsp_receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        (receipt_dir / f"promotion-{index}.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
    return root / task_id


def _run(tmp_path: Path, monkeypatch, capsys, rows: list[dict]) -> tuple[str, str]:
    """Render one report; return (stderr, step summary markdown)."""
    payload = {
        "tasks": [
            {"task_id": row["task_id"], "primary_diagnostic": "none",
             "fingerprint": "a" * 40}
            for row in rows
        ],
        "capabilities": rows,
    }

    class _Report:
        diagnostics: list = []
        exit_code = 0

        def to_mapping(self):
            return payload

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(diagnose, "diagnose_artifact_root", lambda *a, **k: _Report())
    exit_code = diagnose.main(["--root", str(tmp_path)])
    assert exit_code == 0, "annotation must not move the exit code"
    captured = capsys.readouterr()
    # The JSON document is the sealed report. Annotation is a rendering
    # concern and must not leak into it.
    document = json.loads(captured.out)
    assert all("lsp_no_op_verdict" not in row for row in document["capabilities"])
    return captured.err, summary.read_text(encoding="utf-8")


def test_no_serviceable_language_is_annotated_expected(tmp_path, monkeypatch, capsys):
    """extract-elf promoted nothing because there was nothing to promote."""
    _plant_task(tmp_path, "extract-elf", [{
        "schema": "gt.lsp_promotion_task.v1",
        "status": "no_op",
        "languages_promotable": [],
        "languages_attempted": [],
        "languages_completed": [],
        "languages_unavailable": [],
    }])

    stderr, rendered = _run(
        tmp_path, monkeypatch, capsys, [_capability_row("extract-elf")]
    )

    assert "[GT][CAPABILITY][DEGRADED] lsp_promotion" in stderr
    assert f"evidence={_NO_OP_EVIDENCE} [EXPECTED:" in stderr
    assert "no LSP-serviceable language" in stderr
    assert f"| {_NO_OP_EVIDENCE} [EXPECTED:" in rendered
    # State and column are untouched: the row is still DEGRADED and still
    # reads as not-worked.
    assert "| lsp_promotion | DEGRADED | yes | **NO** |" in rendered
    assert "**These did not work: lsp_promotion**" in rendered


def test_serviceable_language_never_promoted_is_unexpected_and_named(
    tmp_path, monkeypatch, capsys
):
    """A promotable language that never completed is a fault, and is named."""
    _plant_task(tmp_path, "rust-task", [{
        "schema": "gt.lsp_promotion_task.v1",
        "status": "no_op",
        "languages_promotable": ["rust"],
        "languages_attempted": ["rust"],
        "languages_completed": [],
        "languages_unavailable": [],
    }])

    stderr, rendered = _run(
        tmp_path, monkeypatch, capsys, [_capability_row("rust-task")]
    )

    assert f"evidence={_NO_OP_EVIDENCE} [UNEXPECTED:" in stderr
    assert "rust" in stderr
    assert f"| {_NO_OP_EVIDENCE} [UNEXPECTED:" in rendered
    assert "rust" in rendered
    assert "EXPECTED:" in stderr  # substring of UNEXPECTED; verdict is not EXPECTED
    assert " [EXPECTED:" not in stderr


def test_worst_receipt_wins_over_a_clean_neighbour(tmp_path, monkeypatch, capsys):
    """One faulted receipt is never laundered by a clean one beside it."""
    _plant_task(tmp_path, "mixed-task", [
        {
            "schema": "gt.lsp_promotion_task.v1", "status": "no_op",
            "languages_promotable": [], "languages_attempted": [],
            "languages_completed": [], "languages_unavailable": [],
        },
        {
            "schema": "gt.lsp_promotion_task.v1", "status": "no_op",
            "languages_promotable": [], "languages_attempted": [],
            "languages_completed": [], "languages_unavailable": ["go"],
        },
    ])

    stderr, _ = _run(tmp_path, monkeypatch, capsys, [_capability_row("mixed-task")])

    assert f"evidence={_NO_OP_EVIDENCE} [UNEXPECTED:" in stderr
    assert "go" in stderr


def test_missing_receipt_is_unknown_never_expected(tmp_path, monkeypatch, capsys):
    """Absence of evidence is not evidence of correctness."""
    _plant_task(tmp_path, "silent-task", [])

    stderr, rendered = _run(
        tmp_path, monkeypatch, capsys, [_capability_row("silent-task")]
    )

    assert f"evidence={_NO_OP_EVIDENCE} [UNKNOWN:" in stderr
    assert f"| {_NO_OP_EVIDENCE} [UNKNOWN:" in rendered
    assert " [EXPECTED:" not in stderr
    assert " [EXPECTED:" not in rendered


def test_working_rows_are_never_annotated(tmp_path, monkeypatch, capsys):
    """Only the no-op promotion row carries a verdict."""
    _plant_task(tmp_path, "healthy-task", [{
        "schema": "gt.lsp_promotion_task.v1",
        "status": "no_op",
        "languages_promotable": [],
        "languages_attempted": [],
        "languages_completed": [],
        "languages_unavailable": [],
    }])

    stderr, rendered = _run(
        tmp_path, monkeypatch, capsys, [_working_row("healthy-task")]
    )

    assert "dense_retrieval" not in stderr
    assert "| dense_retrieval | WORKING | yes | yes | dense_index_ready_query_ready |" \
        in rendered
    assert "EXPECTED" not in rendered
    assert "UNKNOWN" not in rendered


def test_a_promotion_row_that_did_not_no_op_is_left_alone(
    tmp_path, monkeypatch, capsys
):
    """A DEGRADED promotion row with other evidence is not a no-op question."""
    _plant_task(tmp_path, "server-down", [])

    stderr, rendered = _run(
        tmp_path, monkeypatch, capsys,
        [_capability_row("server-down", state="FAILED", refused=True,
                         degraded=False, evidence="promotion_no_servers:servers=0")],
    )

    assert "promotion_no_servers:servers=0" in stderr
    assert "UNKNOWN" not in stderr
    assert "UNKNOWN" not in rendered
# --- the anchor search is bounded to the harness's own subtrees --------------
# A task directory holds the task's whole repository checkout. An unbounded
# rglob for diagnostics.json walks that checkout once per task and, worse, a
# vendored look-alike inside it wins the first-document-wins race: the task
# then gets anchored to a directory inside the checkout and that directory's
# promotion receipts decide this task's verdict.


def _decoy_checkout(task_dir: Path, task_id: str) -> Path:
    """A look-alike task tree inside a checkout under ``task_dir``.

    ``.venv`` sorts ahead of ``agent``, so a whole-tree walk visits the decoy
    first and the harness's own document loses the race. The decoy's receipt
    says the opposite of the real one, so reading it is visible in the verdict
    rather than merely suspected.
    """
    decoy = task_dir / ".venv" / "lib" / "site-packages" / "harness"
    agent = decoy / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": task_id}),
        encoding="utf-8",
    )
    receipts = agent / "gt-state" / task_id / "lsp_receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "promotion-0.json").write_text(
        json.dumps(
            {
                "schema": "gt.lsp_promotion_task.v1",
                "status": "no_op",
                "languages_promotable": [],
                "languages_attempted": [],
                "languages_completed": [],
                "languages_unavailable": [],
            }
        ),
        encoding="utf-8",
    )
    return decoy


def test_a_look_alike_inside_a_checkout_never_anchors_the_task(
    tmp_path, monkeypatch, capsys
):
    """The real fault must not be laundered by a vendored clean receipt."""
    task_dir = _plant_task(tmp_path, "rust-task", [{
        "schema": "gt.lsp_promotion_task.v1",
        "status": "no_op",
        "languages_promotable": ["rust"],
        "languages_attempted": ["rust"],
        "languages_completed": [],
        "languages_unavailable": [],
    }])
    _decoy_checkout(task_dir, "rust-task")

    assert diagnose._task_dirs_by_id(tmp_path) == {"rust-task": task_dir}

    stderr, rendered = _run(
        tmp_path, monkeypatch, capsys, [_capability_row("rust-task")]
    )

    assert f"evidence={_NO_OP_EVIDENCE} [UNEXPECTED:" in stderr
    assert " [EXPECTED:" not in stderr
    assert " [EXPECTED:" not in rendered


def test_the_checkout_is_not_walked_at_all(tmp_path):
    """Bounded globs, not a filtered walk: the checkout is never opened."""
    task_dir = _plant_task(tmp_path, "rust-task", [])
    decoy = _decoy_checkout(task_dir, "rust-task")

    read = [path for path in diagnose._diagnostics_documents(tmp_path)]

    assert read == [task_dir / "agent" / "diagnostics.json"]
    assert not [path for path in read if decoy in path.parents]


def test_the_pier_trial_layout_two_levels_down_is_still_anchored(tmp_path):
    """Pier writes <job-name>/<task>__<hash>/agent/, one level deeper."""
    trial = tmp_path / "tb2-gt-job-1" / "rust-task__9f3c1a2b"
    agent = trial / "agent"
    agent.mkdir(parents=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "rust-task"}),
        encoding="utf-8",
    )

    assert diagnose._task_dirs_by_id(tmp_path) == {"rust-task": trial}


def test_the_gt_state_copy_of_the_document_is_still_read(tmp_path):
    """The only other place a collector writes it."""
    task_dir = tmp_path / "rust-task"
    state = task_dir / "agent" / "gt-state" / "rust-task"
    state.mkdir(parents=True)
    (state / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "rust-task"}),
        encoding="utf-8",
    )

    assert diagnose._task_dirs_by_id(tmp_path) == {"rust-task": task_dir}


# --- the trial depths are guarded, exactly as the sibling walkers are -------
# L-1 (round 5): `_TRIAL_PREFIXES` searched three depths at once with no test
# of what a trial is, unlike verify_run_receipts.find_trials and
# tb2_report._find_trials. The deepest prefix reaches one level INSIDE a
# resolved trial, so a checkout directory that owns an `agent/` had its
# diagnostics document read as a task's own - and that document anchors the
# task directory whose promotion receipts decide the verdict.


def _decoy_inside_the_trial(task_dir: Path, task_id: str) -> Path:
    """`<trial>/sub__x/agent/diagnostics.json` - a fixture tree in a checkout."""
    agent = task_dir / "sub__x" / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    document = agent / "diagnostics.json"
    document.write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": task_id}),
        encoding="utf-8",
    )
    return document


def test_a_directory_inside_a_trial_is_never_a_second_trial(tmp_path):
    task_dir = _plant_task(tmp_path, "rust-task", [])
    decoy = _decoy_inside_the_trial(task_dir, "vendored-look-alike")

    documents = diagnose._diagnostics_documents(tmp_path)

    assert documents == [task_dir / "agent" / "diagnostics.json"]
    assert decoy not in documents
    # A document that is never read cannot anchor a task that does not exist.
    assert diagnose._task_dirs_by_id(tmp_path) == {"rust-task": task_dir}


def test_a_root_that_is_itself_a_trial_does_not_search_its_checkout(tmp_path):
    """The per-task step points this at one trial directory."""
    agent = tmp_path / "agent"
    agent.mkdir(parents=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "rust-task"}),
        encoding="utf-8",
    )
    checkout = tmp_path / "checkout" / "agent"
    checkout.mkdir(parents=True)
    decoy = checkout / "diagnostics.json"
    decoy.write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "vendored-look-alike"}),
        encoding="utf-8",
    )

    documents = diagnose._diagnostics_documents(tmp_path)

    assert documents == [agent / "diagnostics.json"]
    assert decoy not in documents
    assert diagnose._task_dirs_by_id(tmp_path) == {"rust-task": tmp_path}


def test_the_deepest_supported_trial_depth_is_still_anchored(tmp_path):
    """`<job>/<artifact>/agent/` - two levels down, the deepest prefix's reason.

    The guard must narrow nothing: it only refuses a candidate that sits below
    a directory that already owns an ``agent/``.
    """
    trial = tmp_path / "tb2-gt-job-1" / "tb2-gt-harness-1-rust-task__9f3c1a2b"
    agent = trial / "agent"
    agent.mkdir(parents=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "rust-task"}),
        encoding="utf-8",
    )

    assert diagnose._task_dirs_by_id(tmp_path) == {"rust-task": trial}


# --- M-1 (round 6): the ancestor walk never ran for a relative root ---------
# `Path(".").parent` IS `Path(".")`, so `while parent != parent.parent` could
# not take its first step and every candidate under a relative root answered
# "not inside a trial". Pointed at `.` from inside a trial - the shape of every
# per-task step that has already `cd`-ed into the task - the checkout was
# searched again and a vendored document anchored the task.


def test_a_relative_root_that_is_itself_a_trial_does_not_search_its_checkout(
    tmp_path, monkeypatch
):
    agent = tmp_path / "agent"
    agent.mkdir(parents=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "rust-task"}),
        encoding="utf-8",
    )
    checkout = tmp_path / "checkout" / "agent"
    checkout.mkdir(parents=True)
    decoy = checkout / "diagnostics.json"
    decoy.write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "vendored-look-alike"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    documents = diagnose._diagnostics_documents(Path("."))

    assert documents == [Path("agent") / "diagnostics.json"]
    assert Path("checkout") / "agent" / "diagnostics.json" not in documents
    assert diagnose._task_dirs_by_id(Path(".")) == {"rust-task": Path(".")}


def test_a_relative_root_still_anchors_the_trials_below_it(tmp_path, monkeypatch):
    """The guard must narrow nothing when the root is not itself a trial."""
    trial = tmp_path / "tb2-gt-job-1" / "rust-task__9f3c1a2b"
    agent = trial / "agent"
    agent.mkdir(parents=True)
    (agent / "diagnostics.json").write_text(
        json.dumps({"schema": "gt.diagnostics.v1", "task_id": "rust-task"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert diagnose._task_dirs_by_id(Path(".")) == {
        "rust-task": Path("tb2-gt-job-1") / "rust-task__9f3c1a2b"
    }
