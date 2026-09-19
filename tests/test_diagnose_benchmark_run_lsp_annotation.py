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

import io
import json
import sys
from pathlib import Path

import scripts.diagnose_benchmark_run as diagnose
from scripts.gh_annotations import ANNOTATION_FIELD_LIMIT, ANNOTATION_TRUNCATION

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


def _run(
    tmp_path: Path,
    monkeypatch,
    capsys,
    rows: list[dict],
    diagnostics: list | None = None,
    *,
    github_actions: bool = False,
    tasks: list[dict] | None = None,
) -> tuple[str, str]:
    """Render one report; return (stderr, step summary markdown).

    ``GITHUB_ACTIONS`` is always set, never merely left alone: whether this
    widget emits workflow-command lines is the thing under test in the
    injection cases below, and inheriting the runner's own value would make
    every other case here mean something different on CI than on a laptop.

    ``tasks`` overrides the task table, which is derived from ``rows``
    otherwise. The task table carries its own artifact-derived fields
    (``task_id``, ``primary_diagnostic``) and they need to be plantable
    independently of a capability row.
    """
    payload = {
        "tasks": tasks if tasks is not None else [
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

    # Assigned after the class body: a class body is not a closure over the
    # enclosing function's locals.
    _Report.diagnostics = list(diagnostics or [])

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_ACTIONS", "true" if github_actions else "false")
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


# --- nothing this widget prints may be a workflow command -------------------
# REVIEW-12 MEDIUM. GitHub reads a line that BEGINS with ``::`` off a step's
# stdio as a workflow command. Every field below is read out of an artifact
# the model wrote inside its own container: a capability row's ``evidence``
# and ``capability`` come straight off ``agent/diagnostics.json``, and a
# diagnostics event's ``task_id`` and ``phase`` are ``str(row.get(...))`` in
# gt_engine.run_diagnostics._load_events with no character class imposed.
#
# ``normalized_cause`` is the field REVIEW-12 named and the one that was
# already safe - ``DiagnosticEvent.normalized_cause`` is ``_normalize(cause)``,
# i.e. ``[a-z0-9_]`` and nothing else. It carries the payload here anyway,
# because what this pins is the RENDERER: the day the renderer prints a raw
# ``cause``, or ``_normalize`` is relaxed, the hole is back and nothing else
# in the suite would notice.
#
# The payload is REVIEW-11 H-1's, reproduced end to end on a real trial copy:
# three lines of which the runner reads two. ``::stop-commands`` silences
# every later annotation in the job - including this step's own ``::error``
# on a failing run - and the forged ``::error title=Grader::`` states a
# verdict nothing produced.
_INJECTION = "x\n::stop-commands::hunter2\n::error title=Grader::TASK PASSED"


class _Code:
    """``event.code`` is a closed StrEnum; the stub carries only ``.value``."""

    def __init__(self, value: str) -> None:
        self.value = value


class _Event:
    """One diagnostics event as ``diagnose.main`` consumes it.

    A real ``DiagnosticEvent`` cannot be built with this text in
    ``normalized_cause``, which is exactly why the renderer is pinned against
    a stub: this must fail when the renderer stops escaping, not only when
    the producer stops normalizing.
    """

    def __init__(
        self, severity: str, code: str, task_id: str, phase: str, cause: str
    ) -> None:
        self.severity = severity
        self.code = _Code(code)
        self.task_id = task_id
        self.phase = phase
        self.normalized_cause = cause


def _commands(stderr: str) -> list[str]:
    """Every line of ``stderr`` the Actions runner would obey as a command."""
    return [line for line in stderr.split("\n") if line.startswith("::")]


def test_a_planted_diagnostic_cannot_open_a_second_workflow_command(
    tmp_path, monkeypatch, capsys
):
    """One event, one annotation - whatever the event's text contains."""
    event = _Event("ERROR", "GT_PROVIDER_FAILED", _INJECTION, _INJECTION, _INJECTION)

    stderr, _ = _run(tmp_path, monkeypatch, capsys, [], [event], github_actions=True)

    commands = _commands(stderr)
    assert len(commands) == 1, stderr
    assert commands[0].startswith("::error title=GT_PROVIDER_FAILED::")
    assert not any(line.startswith("::stop-commands") for line in stderr.split("\n"))
    assert not any(
        line.startswith("::error title=Grader") for line in stderr.split("\n")
    )
    # Inert, not dropped: the payload is still readable inside the one line.
    assert "%0A" in commands[0]
    assert "hunter2" in commands[0]


def test_a_planted_capability_row_cannot_forge_an_annotation(
    tmp_path, monkeypatch, capsys
):
    """The capability line interpolates ``evidence``, which is model-written."""
    stderr, _ = _run(
        tmp_path,
        monkeypatch,
        capsys,
        [_capability_row("t", evidence=_INJECTION)],
        github_actions=True,
    )

    commands = _commands(stderr)
    assert len(commands) == 1, stderr
    assert commands[0].startswith("::error title=capability_not_working::")
    assert not any(line.startswith("::stop-commands") for line in stderr.split("\n"))
    assert "%0A" in commands[0]


def test_the_human_stderr_line_is_never_a_workflow_command_either(
    tmp_path, monkeypatch, capsys
):
    """The plain ``[GT]`` line is printed to the same stream the runner parses.

    Escaping only the ``::`` line would leave the hole wide open: the runner
    does not care which print statement a line came from, and this one is
    printed whether or not ``GITHUB_ACTIONS`` is set.
    """
    event = _Event("WARNING", "GT_SETUP_ERROR", "t", _INJECTION, "ok")

    stderr, _ = _run(
        tmp_path,
        monkeypatch,
        capsys,
        [_capability_row("t", evidence=_INJECTION)],
        [event],
        github_actions=False,
    )

    assert _commands(stderr) == [], stderr
    # The lines are still there, and still say what happened.
    assert "[GT][WARNING][GT_SETUP_ERROR]" in stderr
    assert "[GT][CAPABILITY][DEGRADED] lsp_promotion" in stderr


def test_a_severity_chooses_the_annotation_kind(tmp_path, monkeypatch, capsys):
    """WARNING is a ``::warning``; the routing survives the escaping change."""
    event = _Event("WARNING", "GT_SETUP_ERROR", "t", "setup", "boom")

    stderr, _ = _run(tmp_path, monkeypatch, capsys, [], [event], github_actions=True)

    assert _commands(stderr) == [
        "::warning title=GT_SETUP_ERROR::[GT][WARNING][GT_SETUP_ERROR] task=t "
        "phase=setup cause=boom"
    ]


# --- REVIEW-13 MEDIUM-1: the verdict is the part that must not be cut -------
# The capability line reads ``... evidence=<model> [VERDICT: <host>]``. The
# model's field comes first and the harness's verdict last, so a bound applied
# to the COMPOSED line spends the whole budget on the container's bytes and
# truncates away the one part of the line the container cannot forge - the
# answer to "was promoting nothing right here?". Every field is bounded on its
# own instead; the composed line is verified, never re-cut.


def test_a_long_evidence_field_cannot_truncate_the_host_verdict(
    tmp_path, monkeypatch, capsys
):
    """2,000 characters of evidence, and the verdict still arrives."""
    _plant_task(tmp_path, "rust-task", [{
        "schema": "gt.lsp_promotion_task.v1",
        "status": "no_op",
        "languages_promotable": ["rust"],
        "languages_attempted": ["rust"],
        "languages_completed": [],
        "languages_unavailable": [],
    }])
    flood = _NO_OP_EVIDENCE + "x" * 2_000

    stderr, rendered = _run(
        tmp_path,
        monkeypatch,
        capsys,
        [_capability_row("rust-task", evidence=flood)],
        github_actions=True,
    )

    human = [line for line in stderr.split("\n") if line.startswith("[GT][CAPABILITY]")]
    commands = _commands(stderr)
    assert len(human) == 1, stderr
    assert len(commands) == 1, stderr
    # The flood is bounded ...
    assert "x" * 600 not in human[0]
    assert "x" * 600 not in commands[0]
    assert "...(truncated)" in human[0]
    # ... and the verdict, which follows it, is still on both lines.
    assert "[UNEXPECTED:" in human[0], human[0]
    assert "[UNEXPECTED:" in commands[0], commands[0]
    assert "rust" in commands[0]
    # The step summary is a markdown file, not a log line, and keeps the row
    # the sealed report carries.
    assert "UNEXPECTED" in rendered


def test_a_long_phase_cannot_truncate_the_cause_off_an_event_line(
    tmp_path, monkeypatch, capsys
):
    """Same rule on the event line: ``phase`` is model-written and comes
    before ``cause``, so a composed-line bound would eat the cause."""
    event = _Event("ERROR", "GT_PROVIDER_FAILED", "t", "p" * 2_000, "the_real_cause")

    stderr, _ = _run(tmp_path, monkeypatch, capsys, [], [event], github_actions=True)

    commands = _commands(stderr)
    assert len(commands) == 1, stderr
    assert "cause=the_real_cause" in commands[0], commands[0]
    assert "cause=the_real_cause" in stderr
    assert "p" * 600 not in commands[0]


def test_a_planted_field_is_bounded_and_escaped_on_both_lines(
    tmp_path, monkeypatch, capsys
):
    """Per-field bounding must not have cost the escaping."""
    event = _Event("ERROR", "GT_PROVIDER_FAILED", _INJECTION, _INJECTION, _INJECTION)

    stderr, _ = _run(tmp_path, monkeypatch, capsys, [], [event], github_actions=True)

    assert len(_commands(stderr)) == 1, stderr
    assert not any(line.startswith("::stop-commands") for line in stderr.split("\n"))
    # Escaped once, not twice: the human line and the annotation carry the
    # same bytes for the same field.
    assert "%250A" not in stderr
    # Escaped ONCE: the annotation carries the human line byte for byte, so a
    # reader is not shown two different renderings of the same field.
    human = [line for line in stderr.split("\n") if line.startswith("[GT][ERROR]")]
    assert len(human) == 1, stderr
    assert _commands(stderr)[0].endswith(human[0])
    assert human[0].count("%0A") == 6, human[0]


# --- REVIEW-14 HIGH-1: the renderer must not die on the data it renders -----
# gh_verbatim REFUSES a composed message longer than the line limit, which is
# right - past the allowance it is a caller defect, not a data condition. But
# the first limit (8 * 512) was arithmetically unreachable: gh_escape bounds
# the RAW field and escapes AFTER, and escaping expands by up to 3x, so three
# container-written fields already compose ~4,690 characters. The ValueError
# was therefore raised on ordinary adversarial data, uncaught, inside the
# render loop of a job that has already finished paying for its run: the first
# oversized row killed every later annotation AND the whole
# GITHUB_STEP_SUMMARY, and both paid attestation callers went red with no
# diagnostics at all.
#
# Two things had to be true, and both are pinned here: the limit admits every
# line a bounded-field caller can compose, and the renderer contains a render
# failure to the row it happened on.

_RENDER_FLOOD = "%" * 3_000
_RENDER_NEWLINES = "\n" * 3_000


def test_adversarial_fields_do_not_end_the_render(tmp_path, monkeypatch, capsys):
    """Three flooded fields on the event line, and the run still reports."""
    adversarial = _Event(
        "ERROR", "GT_PROVIDER_FAILED", _RENDER_FLOOD, _RENDER_NEWLINES, _RENDER_FLOOD
    )
    normal = _Event("WARNING", "GT_SETUP_ERROR", "later-task", "setup", "boom")
    _plant_task(tmp_path, "flooded", [])

    stderr, rendered = _run(
        tmp_path,
        monkeypatch,
        capsys,
        [_capability_row("flooded", evidence=_NO_OP_EVIDENCE + _RENDER_FLOOD)],
        [adversarial, normal],
        github_actions=True,
    )

    commands = _commands(stderr)
    # One per event, one for the degraded capability. Nothing was lost, and
    # nothing raised.
    assert len(commands) == 3, commands
    assert commands[0].startswith("::error title=GT_PROVIDER_FAILED::")
    # The row AFTER the adversarial one is the whole point: it used to never
    # be reached.
    assert commands[1] == (
        "::warning title=GT_SETUP_ERROR::[GT][WARNING][GT_SETUP_ERROR] "
        "task=later-task phase=setup cause=boom"
    )
    assert commands[2].startswith("::error title=capability_not_working::")
    assert "line could not be rendered" not in stderr
    # And the step summary - written after the loop - still exists.
    assert "## GroundTruth diagnostic summary" in rendered
    assert "### Capabilities" in rendered


def test_a_render_failure_is_contained_to_its_own_row(
    tmp_path, monkeypatch, capsys
):
    """A renderer that crashes on adversarial input is worse than one that
    says so. The trap in gh_verbatim stays loud, but it is caught per row."""

    def _boom(kind, title, message):
        raise ValueError("planted caller defect")

    monkeypatch.setattr(diagnose, "gh_command_escaped", _boom)
    events = [
        _Event("ERROR", "GT_PROVIDER_FAILED", "t", "p", "c"),
        _Event("WARNING", "GT_SETUP_ERROR", "t2", "p2", "c2"),
    ]

    stderr, rendered = _run(
        tmp_path,
        monkeypatch,
        capsys,
        [_capability_row("t")],
        events,
        github_actions=True,
    )

    commands = _commands(stderr)
    assert len(commands) == 3, commands
    assert all(
        line.startswith("::error title=Diagnostics renderer::") for line in commands
    ), commands
    assert "GT_PROVIDER_FAILED: line could not be rendered (" in commands[0]
    assert "GT_SETUP_ERROR: line could not be rendered (" in commands[1]
    assert "capability_not_working: line could not be rendered (" in commands[2]
    assert " chars)" in commands[0]
    # The human lines are unaffected: only the annotation could not be built.
    assert "[GT][ERROR][GT_PROVIDER_FAILED] task=t phase=p cause=c" in stderr
    # And the summary is still written.
    assert "## GroundTruth diagnostic summary" in rendered


def test_the_fallback_annotation_is_fixed_text_and_one_line(
    tmp_path, monkeypatch, capsys
):
    """Nothing model-written reaches the fallback but the closed enum code."""

    def _boom(kind, title, message):
        raise ValueError("planted caller defect")

    monkeypatch.setattr(diagnose, "gh_command_escaped", _boom)
    event = _Event("ERROR", "GT_PROVIDER_FAILED", _INJECTION, _INJECTION, _INJECTION)

    stderr, _ = _run(tmp_path, monkeypatch, capsys, [], [event], github_actions=True)

    commands = _commands(stderr)
    assert len(commands) == 1, commands
    assert "hunter2" not in commands[0]
    assert "stop-commands" not in commands[0]
    assert not any(line.startswith("::stop-commands") for line in stderr.split("\n"))


# --- REVIEW-15 MEDIUM: the step summary is a TABLE, and a cell can forge a row
#
# ``GITHUB_STEP_SUMMARY`` is markdown, and a markdown table row ends at a
# newline and splits on ``|``. Both of those characters are legal inside a
# capability row's ``evidence`` - written inside the container the model
# controls - and the renderer interpolated the field straight into the row. So
# a planted ``broken |<LF>| dense_retrieval | WORKING | yes | yes | all good |``
# closed the real cell, ended the real row and wrote a SECOND row claiming a
# capability worked, in a widget whose whole job is to say which capabilities
# did not. The escaping the stderr lines got (REVIEW-11/12) does not apply
# here: ``%0A`` is the RUNNER's syntax, not markdown's.
_MD_INJECTION = "broken |\n| dense_retrieval | WORKING | yes | yes | all good |"

# A cell boundary is an UNESCAPED pipe. Splitting on every ``|`` would count
# the escaped ones as boundaries and report the forged row as a wide row
# instead of as a contained cell - which is the difference under test.
def _split_row(line: str) -> list[str]:
    """Split a table row on pipes that are NOT escaped, counting backslashes.

    Review 18: a lookbehind for one backslash scores ``\\|`` (an escaped
    backslash followed by a live pipe) as escaped, which is exactly the
    breakout a permissive renderer performs. Count the run of backslashes
    before each pipe: an even run leaves the pipe live.
    """
    cells: list[str] = []
    current: list[str] = []
    run = 0
    for ch in line:
        if ch == "\\":
            run += 1
            current.append(ch)
            continue
        if ch == "|" and run % 2 == 0:
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        run = 0
    cells.append("".join(current))
    return cells

_CAPABILITY_HEADER = "| Capability | State | Required | Worked | Evidence |"
_TASK_HEADER = "| Task | Primary | Fingerprint |"


def _table(summary: str, header: str) -> list[list[str]]:
    """The data rows under ``header``, each split into its cells."""
    lines = summary.split("\n")
    start = lines.index(header)
    rows: list[list[str]] = []
    for line in lines[start + 2:]:  # +1 is the |---|---| separator
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in _split_row(line)[1:-1]])
    return rows


def _unescaped(cell: str) -> str:
    """The cell's text as a reader sees it rendered."""
    return cell.replace("\\|", "|").replace("\\\\", "\\")


def test_a_planted_evidence_cell_cannot_forge_a_capability_row(
    tmp_path, monkeypatch, capsys
):
    """The forged row must land INSIDE one cell, as text, and nowhere else."""
    rows = [_capability_row("t", evidence=_MD_INJECTION), _working_row("t")]

    _, summary = _run(tmp_path, monkeypatch, capsys, rows)

    table = _table(summary, _CAPABILITY_HEADER)
    assert len(table) == 2, table
    assert all(len(row) == 5 for row in table), table
    planted, honest = table
    # The honest DEGRADED row is intact - state, columns and all.
    assert planted[:4] == ["lsp_promotion", "DEGRADED", "yes", "**NO**"]
    assert _unescaped(planted[4]).startswith("broken |")
    assert "dense_retrieval | WORKING | yes | yes | all good" in _unescaped(planted[4])
    # And the dense_retrieval row is the one the producer sealed, not the one
    # the payload tried to write.
    assert honest == [
        "dense_retrieval", "WORKING", "yes", "yes", "dense_index_ready_query_ready",
    ]


def test_a_planted_capability_name_or_state_cannot_forge_a_row(
    tmp_path, monkeypatch, capsys
):
    """``capability`` and ``state`` come off the same container-written row."""
    rows = [_capability_row("t", capability=_MD_INJECTION, state=_MD_INJECTION)]

    _, summary = _run(tmp_path, monkeypatch, capsys, rows)

    table = _table(summary, _CAPABILITY_HEADER)
    assert len(table) == 1, table
    assert len(table[0]) == 5, table[0]


def test_a_planted_task_id_or_diagnostic_cannot_forge_a_task_row(
    tmp_path, monkeypatch, capsys
):
    """The task table interpolates two artifact-derived fields of its own."""
    tasks = [
        {"task_id": _MD_INJECTION, "primary_diagnostic": _MD_INJECTION,
         "fingerprint": "a" * 40},
    ]

    _, summary = _run(tmp_path, monkeypatch, capsys, [], tasks=tasks)

    table = _table(summary, _TASK_HEADER)
    assert len(table) == 1, table
    assert len(table[0]) == 3, table[0]
    assert "dense_retrieval | WORKING" in _unescaped(table[0][0])


def test_the_did_not_work_callout_cannot_forge_a_row(tmp_path, monkeypatch, capsys):
    """The bold call-out names capabilities, and the name is model-written."""
    rows = [_capability_row("t", capability=_MD_INJECTION)]

    _, summary = _run(tmp_path, monkeypatch, capsys, rows)

    callout = next(line for line in summary.split("\n")
                   if line.startswith("**These did not work:"))
    assert callout.endswith("**")
    assert "dense_retrieval" in callout


def test_a_five_thousand_character_evidence_cell_is_bounded(
    tmp_path, monkeypatch, capsys
):
    """An unbounded cell buries the whole widget; the JSON keeps it whole."""
    rows = [_capability_row("t", evidence="A" * 5000)]

    _, summary = _run(tmp_path, monkeypatch, capsys, rows)

    cell = _table(summary, _CAPABILITY_HEADER)[0][4]
    assert ANNOTATION_TRUNCATION in cell
    assert len(cell) < ANNOTATION_FIELD_LIMIT + 100


def test_the_host_verdict_survives_a_maximal_evidence_cell(
    tmp_path, monkeypatch, capsys
):
    """REVIEW-13's rule again, in markdown: bound each field, never the cell.

    ``evidence`` is model-written and the ``[VERDICT: ...]`` that follows it is
    the harness's answer to "was promoting nothing right here?". A single bound
    over the composed cell spends the budget on the container's bytes and cuts
    the verdict off - the one part of the cell the container cannot forge.
    """
    _plant_task(tmp_path, "t", [{
        "schema": "gt.lsp_promotion_task.v1",
        "status": "no_op",
        "languages_promotable": ["rust"],
        "languages_attempted": ["rust"],
        "languages_completed": [],
        "languages_unavailable": [],
    }])
    rows = [_capability_row("t", evidence=_NO_OP_EVIDENCE + "x" * 5000)]

    _, summary = _run(tmp_path, monkeypatch, capsys, rows)

    cell = _table(summary, _CAPABILITY_HEADER)[0][4]
    assert "[UNEXPECTED:" in cell
    assert "rust" in cell


# --- REVIEW-15 LOW: a console that cannot spell the evidence ----------------
#
# The human ``[GT]`` lines go to stderr BEFORE the annotations and before the
# summary is written. On a cp1252 console - which is what a local run against
# a downloaded artifact gets on Windows - a `` ``, an emoji or a CJK
# character in ``evidence`` raises UnicodeEncodeError out of ``print``, and the
# traceback takes every later row, every annotation and the whole summary with
# it. The bytes come from the container, so the console's codepage is not
# something this tool gets to assume.
_HOSTILE = "boundary  emoji \U0001f600 cjk 中文 accented na\xefve"


def _run_on_a_cp1252_console(tmp_path, monkeypatch, rows) -> tuple[str, str]:
    """``main`` with stderr wrapped in a console that cannot hold the text."""
    payload = {
        "tasks": [{"task_id": row["task_id"], "primary_diagnostic": "none",
                   "fingerprint": "a" * 40} for row in rows],
        "capabilities": rows,
    }

    class _Report:
        diagnostics: list = []
        exit_code = 0

        def to_mapping(self):
            return payload

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(diagnose, "diagnose_artifact_root", lambda *a, **k: _Report())
    buffer = io.BytesIO()
    console = io.TextIOWrapper(buffer, encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stderr", console)
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    assert diagnose.main(["--root", str(tmp_path)]) == 0

    console.flush()
    return (buffer.getvalue().decode("cp1252", "replace"),
            summary.read_text(encoding="utf-8"))


def test_a_cp1252_console_loses_no_row_and_no_summary(tmp_path, monkeypatch):
    rows = [
        _capability_row("t", capability=f"cap{index}", evidence=_HOSTILE)
        for index in range(4)
    ]

    stderr, summary = _run_on_a_cp1252_console(tmp_path, monkeypatch, rows)

    # Four human lines, four annotations, and the summary that follows them.
    # Counted by LINE START: the annotation carries the human line as its
    # message, so a substring count sees every row twice.
    human = [line for line in stderr.split("\n")
             if line.startswith("[GT][CAPABILITY][DEGRADED]")]
    assert len(human) == 4, stderr
    assert len(_commands(stderr)) == 4, stderr
    assert "## GroundTruth diagnostic summary" in summary
    assert len(_table(summary, _CAPABILITY_HEADER)) == 4
    # The downgrade is lossy only where the console genuinely cannot spell
    # the character: cp1252 HAS an i-diaeresis, so it survives, and the ones
    # it lacks come out as readable escapes rather than as a dead process.
    assert "na\xefve" in human[0]
    assert "\\u4e2d" in human[0] and "\\U0001f600" in human[0]


def test_a_cp1252_console_still_refuses_the_workflow_command_payload(
    tmp_path, monkeypatch
):
    """The downgrade must not re-open REVIEW-11: still one line per row."""
    rows = [_capability_row("t", evidence=_HOSTILE + _INJECTION)]

    stderr, _ = _run_on_a_cp1252_console(tmp_path, monkeypatch, rows)

    assert len(_commands(stderr)) == 1, stderr
    assert not any(line.startswith("::stop-commands") for line in stderr.split("\n"))


def test_an_escaped_pipe_in_a_cell_cannot_free_the_next_pipe(tmp_path, monkeypatch, capsys):
    """Review 18: a written backslash-pipe must not become an escaped backslash
    followed by a LIVE pipe. The backslash is escaped first, so the Worked
    column keeps the host verdict whichever GFM implementation renders it."""
    payload = "dense_retrieval" + "\\|WORKING\\|yes\\|yes"
    rows = [_capability_row("t", evidence=payload), _working_row("t")]

    _, summary = _run(tmp_path, monkeypatch, capsys, rows)

    table = _table(summary, _CAPABILITY_HEADER)
    assert len(table) == 2, table
    planted, honest = table
    assert planted[:4] == ["lsp_promotion", "DEGRADED", "yes", "**NO**"], planted
    assert _unescaped(planted[4]).startswith(payload), planted[4]
    assert honest[0] == "dense_retrieval"


def test_a_backtick_cannot_close_the_fingerprint_code_span():
    """Backslash escapes are inert inside a code span, so a backtick is
    replaced, not escaped (review 18)."""
    cell = diagnose._md_cell("`aaaaaaaa`[x](ht")
    assert "`" not in cell
    assert cell.startswith("'aaaaaaaa'")
