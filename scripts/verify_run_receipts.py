"""Read a task's receipts against each other and report the contradictions.

Every defect found this week was already visible in the artifacts. Each
receipt was internally consistent and nothing read two of them together, so
runs went green with zero graded tasks and nobody was told. The contradictions
this checks for are the ones that actually happened:

  * Run 35280614124: the supervisor recorded ``child_returncode: 0`` while the
    report's own ``terminal`` said ``internal_error``. A clean child exit and
    an internal-error terminal cannot both be true.
  * Run 35256147148, task ``amoffat__sh-744``: 4,660 bytes of committed work
    were observed in the workspace and the submission was still graded as
    empty, with reward 0 and no error code to explain it. The size of what was
    actually submitted is read off the artifact, not taken on a flag: no
    caller passes one, so a flag-only check could never fire in CI.
  * Run 35262214538: a git error was labelled ``provider_failed`` although
    every provider request got a response and no provider failure was
    recorded. The provider was never the thing that failed.
  * Cohort 35298094010: ``write-compressor`` and ``sanitize-git-repo`` were
    killed by the OOM killer during initial indexing. Those are not model
    results and must not be read as any.

Harbor exits 0 on an errored trial, so a green job is not evidence that
anything was graded; that pairing is reported as a WARNING rather than a
failure because a legitimately empty shard exists.

Absence of evidence is never a pass. A receipt that omits a key a check needs
makes that check UNKNOWN. A run receipt that is ON DISK and cannot be parsed
into an object is not a missing one: it is a writer or an upload that broke,
so it refuses the whole task by name (``read_error``) rather than being read
as "this run wrote nothing" - which said "wrote no gt-run.json" in a detail
whose own file list named gt-run.json. A run that left no run receipt at all
was never checked, and saying so is not the same as passing it:
that exits 2 with a ``resolution_error`` naming which way the resolution
failed - ``no_trial_found``, ``no_run_receipt``, ``ambiguous_trial``,
``read_error`` or ``no_decidable_check`` - and a ``resolution_detail`` naming
what WAS found instead. The last one is the run receipt that parses and says
nothing: every check UNKNOWN with none crashed means nothing about the run was
decided, and a receipt of six UNKNOWNs over a real task id exiting 0 is the
same false pass whichever door it came through.
Nothing here reruns, regrades or repairs anything: it reads artifacts and
reports.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SCHEMA = "gt.receipt_consistency.v1"
PROGRESS_SCHEMA = "gt.benchmark_progress.v1"

CONTRADICTION = "CONTRADICTION"
WARNING = "WARNING"
INFO = "INFO"
UNKNOWN = "UNKNOWN"
OK = "OK"

# Terminals that assert the run itself broke. A child that exited 0 did not.
_FAILURE_TERMINALS = frozenset({"internal_error", "provider_failed", "setup_error"})

_GT_RUN_NAME = "gt-run.json"
_REPORT_NAME = "miniswe_report.json"

# Every value main() can write into ``resolution_error``. rc 2 tells a reader
# that nothing was resolved; this says which way. The set is explicit, and
# tests/test_verify_run_receipts.py asserts that the codes handed to
# ``build_unresolved_receipt`` - literals, and the ones main chooses between in
# a variable - are exactly this set, and that each is named in the module
# docstring: an undocumented refusal code reads as a checker bug rather than as
# a verdict about the run.
RESOLUTION_ERRORS = (
    "no_trial_found",  # no Pier trial dir AND neither run receipt anywhere
    "no_run_receipt",  # a trial was found and it wrote neither run receipt
    "ambiguous_trial",  # more than one trial directory under one root
    "read_error",  # a run receipt on disk is unparseable, or a read raised
    "no_decidable_check",  # the run receipts parsed but decided no check at all
)

# How much of a failed read's own text a refusal repeats. The parse error is
# what tells the reader which byte of which file to look at, so it is quoted -
# but a message is not a place to paste a receipt, and this detail is written
# into a CI annotation.
_READ_ERROR_TEXT_LIMIT = 200

# How many file names the refusal detail lists before it says "+N more". The
# list is what makes "no run receipt" falsifiable, and a trial's harness
# subtrees are small; the bound is there so a pathological tree cannot write a
# megabyte of names into a receipt and a CI annotation.
_DETAIL_FILE_LIMIT = 12

# The harness owns exactly these subtrees of a task directory. Everything else
# under a TB2 task dir is the task's own repository checkout: unbounded in size
# and full of JSON that looks like ours (vendored fixtures, site-packages), so
# a whole-tree walk both costs a full traversal per task and can read another
# project's file as this run's receipt. The list is explicit for that reason -
# a new artifact location has to be added here deliberately.
_HARNESS_GLOBS = (
    "*.json",  # the trial dir's own top level
    "agent/*.json",
    # Only the state dir's top level: one level deeper are the per-request
    # provider blobs, thousands of files, and no receipt lives among them.
    "agent/gt-state/*/*.json",
    "artifacts/*.json",
    "official-evaluator/*.json",
    "progress/*.json",
)

_MODEL_PATCH_RELATIVE = ("artifacts", "model.patch")
_PREDICTIONS_RELATIVE = ("official-evaluator", "predictions.jsonl")


# Pier names one directory per trial ``<task>__<hash>`` and writes the
# harness's receipts under its ``agent/``. The step may be pointed at the suite
# root (``results/terminal-bench``, which holds a ``<job-name>/`` level) or at
# the job directory itself, so the trial sits one or two levels down - and
# never deeper: below the trial is the task's own repository checkout.
#
# The two depths are tried in order and the first that yields a trial wins.
# Searching both at once walked one level INSIDE a resolved trial: a checkout
# directory named with a ``__`` and owning an ``agent/`` (a vendored package,
# a fixture tree) counted as a second trial, and the task was refused with
# exit 2 over a directory name.
_TRIAL_GLOBS = ("*__*", "*/*__*")


class AmbiguousTrialError(RuntimeError):
    """More than one Pier trial directory under one artifact root.

    Reading two trials as one task mixes their receipts and reports whichever
    file sorted first as this task's. Refuse, and name what was found.
    """


class ReceiptReadError(RuntimeError):
    """A run receipt exists on disk and cannot be read as a JSON object.

    M-1 (round 8): the reader answered None for an absent file, an
    unparseable one and a valid JSON list alike, so a truncated or
    half-uploaded ``gt-run.json`` reached the resolution gate as "this run
    wrote no run receipt" - a claim its own detail contradicted by listing
    gt-run.json among the files found, and past ``_DETAIL_FILE_LIMIT`` names
    the contradiction truncated away. Present-and-unreadable is a different
    fault from absent and sends the reader somewhere else entirely: to the
    writer or the upload, not to the run.
    """


def _owns_agent_dir(path: Path) -> bool:
    """True when ``path`` is a directory owning an ``agent/``.

    This is what makes a directory a trial - not its name, which is the same
    rule ``_inside_a_trial`` applies to ancestors. Kept as one predicate so
    the trial search and the "was the CLI pointed AT a trial" question cannot
    drift apart.
    """
    return path.is_dir() and path.joinpath("agent").is_dir()


def _is_trial(path: Path) -> bool:
    """A Pier trial directory: ``<task>__<hash>/`` owning an ``agent/``."""
    return "__" in path.name and _owns_agent_dir(path)


def _inside_a_trial(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` sits below a trial, i.e. inside its checkout.

    A trial is a directory that OWNS an ``agent/``, and nothing else is one
    whatever it is called. So the question is about ancestry, not about
    names: ``candidate`` is inside a trial when some ancestor between it and
    the resolved ``root``, ``root`` INCLUDED, owns an ``agent/``. This is the
    SAME rule as in scripts/tb2_report.py and scripts/diagnose_benchmark_run.py
    (each keeps its own copy - two are gates, one is a reporting tool - and
    tests/test_tb2_report.py asserts the three answer one table identically).

    H-1 (round 6): this used to answer ``"__" in parent.name`` for a depth-2
    candidate. Pier names its job directory after the task and every
    SWE-bench instance id carries a ``__`` - job
    ``swelive-...-aiogram__aiogram-1594``, trial
    ``aiogram__aiogram-1594__pteFG6N`` - so every real trial under a swelive
    job directory was rejected, ``find_trials`` returned nothing, and the run
    carried on with trial, gt-run.json and miniswe_report.json all None while
    the workflow's copied progress receipt kept the refusal from firing: a
    planted contradiction exited 0 under a real task id.

    Both sides are resolved before they are compared, so a relative root
    (``.``, the directory the checker is run in) still matches the
    candidate's own ancestors - and a candidate that resolves OUT from
    under the root is excluded rather than reported as searchable (L-3).
    """
    root = root.resolve()
    candidate = candidate.resolve()
    if candidate == root:
        # The root is where the search starts; it is not inside anything.
        return False
    ancestors: list[Path] = []
    for parent in candidate.parents:
        ancestors.append(parent)
        if parent == root:
            break
    else:
        # L-3 (round 7): ``candidate`` is not under ``root`` at all. Both
        # sides are resolved first, so a symlink under a trial pointing
        # outside the root arrives here already resolved out from under it,
        # the walk runs off the top, and answering False said "not inside a
        # trial" - which made the escapee a SEARCH ROOT and another project's
        # receipts this run's. A path that escapes the root is never a trial
        # OF THIS ROOT, so it is excluded exactly as a checkout is.
        return True
    return any(parent.joinpath("agent").is_dir() for parent in ancestors)


def find_trials(root: Path) -> list[Path]:
    """Every Pier trial directory under ``root``, at the shallowest depth found.

    Depth order is the whole point: pointed at the job directory, the trials
    are one level down and everything below them is the task's own repository
    checkout, which may hold any directory name at all. Searching both depths
    at once made a checkout directory named with a ``__`` and owning an
    ``agent/`` (a vendored package, a fixture tree) count as a second trial,
    which refused the whole task with exit 2 over a directory name. So the
    deeper glob is consulted only when the shallower one found nothing, and
    nothing below a trial is ever a trial.
    """
    if not root.is_dir():
        return []
    for pattern in _TRIAL_GLOBS:
        found = [
            path
            for path in sorted(root.glob(pattern))
            if _is_trial(path) and not _inside_a_trial(root, path)
        ]
        if found:
            return found
    return []


def resolve_trial(root: Path) -> Path | None:
    """The one trial directory under ``root``, or None when there is none."""
    trials = find_trials(root)
    if len(trials) > 1:
        raise AmbiguousTrialError(
            f"{len(trials)} trial directories under {root}: "
            + ", ".join(str(trial) for trial in trials)
            + "; point the check at one task's trial directory"
        )
    return trials[0] if trials else None


def _trial_roots(root: Path) -> list[Path]:
    """``root``, the directories directly inside it, and any Pier trial dir.

    The CLI is pointed at one task's artifacts, but the layouts differ per
    workflow: a flat download, ``<download>/<task>/``, and Pier's own
    ``<job-name>/<task>__<hash>/``, which is two levels down. Nothing deeper is
    treated as a trial dir: below that is the checkout.

    The children are filtered through the same ``_inside_a_trial`` guard the
    trial search uses. Pointing the CLI at a trial is a documented mode, and
    there every child except the harness's own ``agent/``, ``artifacts/``,
    ``official-evaluator/`` and ``progress/`` is the task's repository
    checkout: adding them unconditionally made a look-alike at
    ``<trial>/checkout/agent/`` this run's receipts, which reported four OK
    verdicts under another task's id and exited 0. When ``root`` owns an
    ``agent/`` the guard declines every child, so a trial is searched through
    its own harness globs only - which already reach ``agent/*.json``.
    """
    roots = [root]
    try:
        children = sorted(child for child in root.iterdir() if child.is_dir())
    except OSError:
        children = []
    roots.extend(child for child in children if not _inside_a_trial(root, child))
    roots.extend(trial for trial in find_trials(root) if trial not in roots)
    return roots


def harness_receipts(root: Path) -> list[Path]:
    """Every JSON file in the harness-owned subtrees under ``root``.

    Order is stable (trial dir, then the glob list, then name) so two runs over
    the same tree pick the same file.
    """
    if not root.is_dir():
        return [root] if root.is_file() else []
    found: dict[Path, None] = {}
    for trial in _trial_roots(root):
        for pattern in _HARNESS_GLOBS:
            for path in sorted(trial.glob(pattern)):
                if path.is_file():
                    found.setdefault(path, None)
    return list(found)


def find_named(root: Path, name: str) -> Path | None:
    """First match for ``name`` in the harness-owned subtrees, or None.

    Artifact layouts differ per workflow (``<task>/agent/``, ``<task>/``, a
    bare download directory), so the finder is by name, not by path - but only
    within the subtrees the harness itself writes.
    """
    if not root.is_dir():
        return root if root.is_file() and root.name == name else None
    for path in harness_receipts(root):
        if path.name == name:
            return path
    return None


def _predictions_patch_bytes(path: Path, task_id: str | None) -> int | None:
    """Length of this task's ``model_patch`` in a predictions file, or None.

    A predictions file may be merged across tasks, so the row is matched on
    ``instance_id``. A lone row is taken as this task's only when it names no
    instance at all: a single row that names another task is that task's
    evidence, and reading its size as ours is how a neighbour's empty patch
    would be reported as this task's. Anything ambiguous returns None, because
    guessing which row was graded invents the evidence this check looks for.
    """
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        # UnicodeDecodeError IS a ValueError: a model_patch that diffs a
        # latin-1 encoded file is not decodable here, and that took the whole
        # run down with a traceback - exit 1, no receipt - while the workflow
        # reported a contradiction and pointed the reader at a file that was
        # never written. Undecodable is unread, and unread is None.
        return None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("model_patch"), str):
            rows.append(row)
    matched = [row for row in rows if row.get("instance_id") == task_id] if task_id else []
    if not matched and len(rows) == 1 and not rows[0].get("instance_id"):
        matched = rows
    if not matched:
        return None
    return len(str(matched[0]["model_patch"]).encode("utf-8"))


def find_submitted_patch(root: Path, task_id: str | None = None) -> tuple[int | None, str | None]:
    """Bytes of the patch the grader received, and where that was read.

    No caller supplies ``--submitted-patch-bytes``, so a check that only
    trusted the flag could never fire on a shipped run. The size is on disk in
    the artifact: Pier collects the patch to ``artifacts/model.patch``, and the
    official evaluator's ``predictions.jsonl`` carries the same bytes as
    ``model_patch``. The collected file wins - it is the thing that shipped.
    """
    roots = _trial_roots(root) if root.is_dir() else []
    for trial in roots:
        patch = trial.joinpath(*_MODEL_PATCH_RELATIVE)
        if patch.is_file():
            try:
                return patch.stat().st_size, str(patch)
            except OSError:
                continue
    for trial in roots:
        predictions = trial.joinpath(*_PREDICTIONS_RELATIVE)
        if predictions.is_file():
            size = _predictions_patch_bytes(predictions, task_id)
            if size is not None:
                return size, str(predictions)
    return None, None


def _read_json(path: Path | None) -> dict[str, Any] | None:
    """Return a JSON object, or None for anything unreadable or non-object."""
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _bounded(value: object) -> str:
    """One line of at most ``_READ_ERROR_TEXT_LIMIT`` characters."""
    text = " ".join(str(value).split())
    if len(text) <= _READ_ERROR_TEXT_LIMIT:
        return text
    return text[:_READ_ERROR_TEXT_LIMIT] + " (truncated)"


def _read_receipt_json(path: Path | None) -> dict[str, Any] | None:
    """A run receipt as a JSON object, raising when one is there unreadable.

    The two named run receipts are what resolution is decided on, so for them
    alone "not there" and "there and unreadable" must not collapse to the same
    answer (M-1, round 8). Everything else under the harness subtrees - the
    progress receipt's schema hunt reads every JSON file there - keeps going
    through ``_read_json``, because a file this checker knows nothing about
    being unparseable says nothing about the run.
    """
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        # ValueError covers UnicodeDecodeError: a receipt written in another
        # encoding is on disk and unread, which is this refusal, not absence.
        raise ReceiptReadError(f"{path} could not be read: {_bounded(exc)}") from exc
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ReceiptReadError(f"{path} is not valid JSON: {_bounded(exc)}") from exc
    if not isinstance(value, dict):
        # Valid JSON that is not an object carries no key any check reads, and
        # ``.get`` on it would raise inside whichever check touched it first.
        raise ReceiptReadError(
            f"{path} is a JSON {type(value).__name__}, not an object"
        )
    return value


def find_progress(root: Path) -> Path | None:
    """Locate the benchmark progress receipt by schema, not by file name.

    The emitters name it differently per workflow (``benchmark-progress.json``,
    ``progress.json``, ``gt-progress.json``), so the schema string is the only
    stable handle. Only the harness's own subtrees are opened: reading every
    JSON file under a task dir means parsing its entire repository checkout.
    """
    for path in harness_receipts(root):
        body = _read_json(path)
        if body is not None and body.get("schema") == PROGRESS_SCHEMA:
            return path
    return None


@dataclass(frozen=True)
class Inputs:
    """The three receipts, plus where each came from (or None if absent)."""

    root: Path
    trial: Path | None = None
    gt_run: dict[str, Any] | None = None
    gt_run_path: Path | None = None
    report: dict[str, Any] | None = None
    report_path: Path | None = None
    progress: dict[str, Any] | None = None
    progress_path: Path | None = None
    submitted_patch_bytes: int | None = None
    submitted_patch_source: str | None = None

    @property
    def trial_task_id(self) -> str | None:
        """The task named by the trial directory ``<task>__<hash>``, or None.

        The hash is separated at the LAST ``__``, which leaves a SWE-bench
        instance id (``amoffat__sh-744__<hash>`` -> ``amoffat__sh-744``) whole.
        """
        if self.trial is None:
            return None
        task, _, _digest = self.trial.name.rpartition("__")
        return task or self.trial.name

    @property
    def task_id(self) -> str:
        """The task these receipts belong to, taken from the receipts first.

        ``root`` is an artifact root, not a task: pointed at
        ``results/terminal-bench`` its name made every task ``terminal-bench``,
        which is why the trial directory is read before falling back to it.
        """
        for candidate in (
            (self.gt_run or {}).get("task_id"),
            (self.progress_tasks[0].get("task_id") if self.progress_tasks else None),
            self.trial_task_id,
        ):
            if isinstance(candidate, str) and candidate:
                return candidate
        return self.root.name

    @property
    def progress_tasks(self) -> list[dict[str, Any]]:
        tasks = (self.progress or {}).get("tasks")
        return [row for row in tasks if isinstance(row, dict)] if isinstance(tasks, list) else []

    def progress_task(self, task_id: str | None = None) -> dict[str, Any] | None:
        """The progress row for this task, or the only row when unambiguous."""
        rows = self.progress_tasks
        if task_id:
            matched = [row for row in rows if row.get("task_id") == task_id]
            if matched:
                return matched[0]
        return rows[0] if len(rows) == 1 else None

    @property
    def supervisor(self) -> dict[str, Any] | None:
        block = (self.report or {}).get("supervisor")
        return block if isinstance(block, dict) else None

    @property
    def patch_state(self) -> dict[str, Any] | None:
        block = (self.report or {}).get("submission_patch_state")
        return block if isinstance(block, dict) else None


def load_inputs(root: Path | str) -> Inputs:
    """Find and read the three receipts under one task artifact directory.

    Raises ``ReceiptReadError`` when a run receipt is on disk and unreadable,
    and ``AmbiguousTrialError`` when one root holds two trials. Both are
    refusals about the artifacts, and both are decided here so that every
    caller - the CLI and any other reader - gets the same answer.
    """
    root = Path(root)
    trial = resolve_trial(root)
    if trial is None and _owns_agent_dir(root):
        # M-2 (round 8): the CLI documents "the trial dir itself" as a root,
        # and pointed there ``find_trials`` correctly finds nothing BELOW it -
        # everything below a trial is the task's checkout. The refusal then
        # read "no trial found", which sends the reader to check the path,
        # over a directory that IS the trial and died. A directory owning an
        # ``agent/`` is a trial by the same rule ``_inside_a_trial`` uses on
        # ancestors, so root is one, and ``_unresolved_detail`` lists the
        # harness JSON it did write.
        trial = root
    gt_run_path = find_named(root, _GT_RUN_NAME)
    report_path = find_named(root, _REPORT_NAME)
    progress_path = find_progress(root)
    # Read in a fixed order so two runs over one broken tree name the same
    # file first.
    gt_run = _read_receipt_json(gt_run_path)
    report = _read_receipt_json(report_path)
    inputs = Inputs(
        root=root,
        trial=trial,
        gt_run=gt_run,
        gt_run_path=gt_run_path,
        report=report,
        report_path=report_path,
        progress=_read_json(progress_path),
        progress_path=progress_path,
    )
    # The submitted size is derived last because the lookup keys off task_id,
    # which only the receipts above can supply.
    size, source = find_submitted_patch(root, inputs.task_id)
    return replace(inputs, submitted_patch_bytes=size, submitted_patch_source=source)


def _int(value: Any) -> int | None:
    """A finite number as an int; bools and everything else become None.

    H-2 (round 6/7): ``json.dumps`` writes bare ``NaN``, ``Infinity`` and
    ``-Infinity`` - it is Python's own default - and ``json.loads`` reads them
    back as floats. ``int(nan)`` is a ValueError and ``int(inf)`` an
    OverflowError, so a receipt carrying either took the reading check down
    into the per-check handler, where it became that check's UNKNOWN and was
    counted by nothing. A value that is not a finite number cannot be read as
    a count or a return code, and unreadable is None here - which every caller
    already treats as "this field said nothing".

    This is the module's only numeric conversion; nothing else calls ``int``
    or ``float`` on a value that came out of a receipt.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return int(value)


def _result(check_id: str, severity: str, message: str) -> dict[str, str]:
    return {"check_id": check_id, "severity": severity, "message": message}


# --- checks ----------------------------------------------------------------


def check_child_exit_vs_terminal(inputs: Inputs, **_: Any) -> dict[str, str]:
    """Run 35280614124: child exited 0, terminal said internal_error."""
    check_id = "child_exit_vs_terminal"
    supervisor = inputs.supervisor
    terminal = (inputs.report or {}).get("terminal")
    if supervisor is None or "child_returncode" not in supervisor:
        return _result(check_id, UNKNOWN, "no supervisor.child_returncode in miniswe_report.json")
    if not isinstance(terminal, str) or not terminal:
        return _result(check_id, UNKNOWN, "miniswe_report.json has no terminal")
    returncode = _int(supervisor.get("child_returncode"))
    if returncode is None:
        # The key is there and it is not a number this can read - a string, a
        # null, or one of the non-finite floats json.dumps writes (H-2). The
        # comparison below would then quietly answer "not 0" and report OK,
        # which says the child exited as the terminal claims on the one path
        # where the exit code was never read.
        return _result(
            check_id,
            UNKNOWN,
            "supervisor.child_returncode="
            f"{supervisor.get('child_returncode')!r} is not a finite number",
        )
    if returncode == 0 and terminal in _FAILURE_TERMINALS:
        return _result(
            check_id,
            CONTRADICTION,
            f"supervisor child_returncode=0 but terminal={terminal!r}; "
            "a child that exited cleanly did not fail the run",
        )
    return _result(check_id, OK, f"child_returncode={returncode} terminal={terminal!r}")


def check_committed_work_vs_empty_submission(
    inputs: Inputs, *, submitted_patch_bytes: int | None = None, **_: Any
) -> dict[str, str]:
    """Run 35256147148 amoffat__sh-744: 4,660 committed bytes graded as empty."""
    check_id = "committed_work_vs_empty_submission"
    state = inputs.patch_state
    if state is None:
        return _result(check_id, UNKNOWN, "no submission_patch_state in miniswe_report.json")
    committed_bytes = _int(state.get("committed_patch_bytes"))
    committed_empty = state.get("committed_patch_empty")
    if committed_bytes is None and not isinstance(committed_empty, bool):
        return _result(
            check_id,
            UNKNOWN,
            f"submission_patch_state status={state.get('status')!r} recorded neither "
            "committed_patch_bytes nor committed_patch_empty",
        )

    has_work = bool(committed_bytes and committed_bytes > 0) or committed_empty is False
    if not has_work:
        return _result(check_id, OK, "no committed work observed; an empty submission loses nothing")

    reasons: list[str] = []
    if (inputs.report or {}).get("collected_patch_will_be_empty") is True:
        reasons.append("collected_patch_will_be_empty=true")
    # The flag is an override for a caller that knows better; with no flag the
    # size comes off the artifact, because in CI there is no flag.
    submitted = submitted_patch_bytes
    source = "--submitted-patch-bytes"
    if submitted is None:
        submitted, source = inputs.submitted_patch_bytes, inputs.submitted_patch_source
    task = inputs.progress_task(inputs.task_id)
    if submitted == 0:
        # Work was committed in the workspace and nothing was submitted: the
        # two receipts disagree on their own, whether or not a grading row
        # exists to confirm it. The grading side of run 35256147148 - reward
        # 0 with no error_code to explain it - is named when it is there.
        detail = f"a 0-byte submitted patch ({source})"
        if (
            task is not None
            and _int(task.get("reward")) == 0
            and str(task.get("error_code") or "") == ""
        ):
            detail = f"graded reward=0 with no error_code and {detail}"
        reasons.append(detail)
    if reasons:
        observed = f"{committed_bytes:,}" if committed_bytes is not None else "nonempty"
        return _result(
            check_id,
            CONTRADICTION,
            f"{observed} committed_patch_bytes of work in the workspace, but "
            + " and ".join(reasons),
        )
    if submitted is None:
        # M-2 (round 6): work was observed and nothing readable says what
        # shipped - no artifacts/model.patch, and no predictions row that is
        # this task's (a latin-1 predictions.jsonl lands here too). Absence of
        # evidence is UNKNOWN in this module; reporting OK here said the
        # submission was fine on the one path where it was never read.
        return _result(
            check_id,
            UNKNOWN,
            "committed work observed but the submitted patch size is unavailable: "
            "no artifacts/model.patch and no readable predictions row for this task",
        )
    return _result(check_id, OK, "committed work observed and nothing claims the submission was empty")


def check_valid_run_vs_infra_state(inputs: Inputs, **_: Any) -> dict[str, str]:
    """A completed, valid research run cannot also be an infrastructure failure."""
    check_id = "valid_run_vs_infra_state"
    gt_run = inputs.gt_run
    if gt_run is None or "status" not in gt_run or "research_valid" not in gt_run:
        return _result(check_id, UNKNOWN, "no gt-run.json status/research_valid")
    task = inputs.progress_task(inputs.task_id)
    if task is None or not task.get("state"):
        return _result(check_id, UNKNOWN, f"no {PROGRESS_SCHEMA} row for this task")
    status = str(gt_run.get("status") or "")
    valid = gt_run.get("research_valid") is True
    state = str(task.get("state") or "")
    if status == "COMPLETED" and valid and state == "infrastructure_failed":
        return _result(
            check_id,
            CONTRADICTION,
            "gt-run.json says status=COMPLETED research_valid=true while the progress "
            "receipt says state=infrastructure_failed",
        )
    return _result(check_id, OK, f"status={status!r} research_valid={valid} state={state!r}")


def check_provider_failed_without_provider_failures(inputs: Inputs, **_: Any) -> dict[str, str]:
    """Run 35262214538: a git error labelled provider_failed.

    The counters are read under the names ``gt-run.json`` actually carries -
    ``provider_calls``, ``provider_completed_calls``, ``provider_failed_calls``
    (gt_harness/runtime_receipts.py). The ``provider_*_count`` spellings belong
    to the supervisor journal's ``run_terminal`` event and appear in no
    receipt, so a check written against them was UNKNOWN on every real run
    while its fixtures, which invented the keys, passed.
    """
    check_id = "provider_failed_without_provider_failures"
    gt_run = inputs.gt_run or {}
    terminal = gt_run.get("terminal")
    if not isinstance(terminal, str) or not terminal:
        terminal = (inputs.report or {}).get("terminal")
    if not isinstance(terminal, str) or not terminal:
        return _result(check_id, UNKNOWN, "no terminal in gt-run.json or miniswe_report.json")
    if terminal != "provider_failed":
        return _result(check_id, OK, f"terminal={terminal!r}; provider blame not claimed")
    failed = _int(gt_run.get("provider_failed_calls"))
    calls = _int(gt_run.get("provider_calls"))
    completed = _int(gt_run.get("provider_completed_calls"))
    if failed is None or calls is None or completed is None:
        return _result(check_id, UNKNOWN, "gt-run.json omits the provider call counters")
    if failed == 0 and calls == completed:
        return _result(
            check_id,
            CONTRADICTION,
            f"terminal=provider_failed but provider_failed_calls=0 and all {calls} "
            "provider calls completed; the provider is being blamed for another failure",
        )
    return _result(
        check_id,
        OK,
        f"provider_failed_calls={failed} provider_calls={calls} "
        f"provider_completed_calls={completed}",
    )


def check_green_job_zero_graded(
    inputs: Inputs, *, job_conclusion: str | None = None, **_: Any
) -> dict[str, str]:
    """Harbor exits 0 on an errored trial, so success alone proves nothing."""
    check_id = "green_job_zero_graded"
    if not job_conclusion:
        return _result(check_id, UNKNOWN, "no --job-conclusion supplied")
    if inputs.progress is None:
        return _result(check_id, UNKNOWN, f"no {PROGRESS_SCHEMA} receipt found")
    graded = _int(inputs.progress.get("officially_graded"))
    if graded is None:
        graded = sum(1 for row in inputs.progress_tasks if row.get("official_verifier") is True)
    if job_conclusion == "success" and graded == 0:
        return _result(
            check_id,
            WARNING,
            "job conclusion is success with officially_graded=0; a green job is not "
            "evidence that anything was graded",
        )
    return _result(check_id, OK, f"job_conclusion={job_conclusion!r} officially_graded={graded}")


def check_oom_signature(inputs: Inputs, **_: Any) -> dict[str, str]:
    """Cohort 35298094010 lost write-compressor and sanitize-git-repo this way."""
    check_id = "oom_signature"
    supervisor = inputs.supervisor
    if supervisor is None or (
        "child_returncode" not in supervisor and "reason" not in supervisor
    ):
        return _result(check_id, UNKNOWN, "no supervisor block in miniswe_report.json")
    reason = str(supervisor.get("reason") or "")
    if _int(supervisor.get("child_returncode")) == -9 or reason.startswith("initial_index_failed"):
        return _result(check_id, INFO, "oom_kill_during_index")
    return _result(check_id, OK, f"child_returncode={supervisor.get('child_returncode')} reason={reason!r}")


# Each check is registered under the id it reports, so the refusal receipt
# can name every check without running a single one. The pairing is guarded
# by a test that compares these ids with what the checks actually report.
CHECKS: tuple[tuple[str, Callable[..., dict[str, str]]], ...] = (
    ("child_exit_vs_terminal", check_child_exit_vs_terminal),
    ("committed_work_vs_empty_submission", check_committed_work_vs_empty_submission),
    ("valid_run_vs_infra_state", check_valid_run_vs_infra_state),
    ("provider_failed_without_provider_failures", check_provider_failed_without_provider_failures),
    ("green_job_zero_graded", check_green_job_zero_graded),
    ("oom_signature", check_oom_signature),
)

CHECK_IDS: tuple[str, ...] = tuple(check_id for check_id, _check in CHECKS)


def run_checks(
    inputs: Inputs,
    *,
    job_conclusion: str | None = None,
    submitted_patch_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Every check, always, in a fixed order - a silent check is a missing one.

    A check that raises is that one check's UNKNOWN, carrying the exception,
    and the other five still run. H-2 (round 6): one failing check used to
    take the whole run down to the refusal receipt - six UNKNOWNs and exit 2 -
    which erased the contradictions the remaining checks had already found,
    and reported "the receipts could not be read" about receipts that had
    been read. A failure that escapes this loop (``_result`` itself breaking)
    still lands in main's net, which now builds its receipt from constants.

    H-1 (round 7): that UNKNOWN also has to be DISTINGUISHABLE from a
    data-driven one. UNKNOWN is counted by nothing, so when the check that
    raises is the one that would have returned CONTRADICTION, the receipt
    reports zero contradictions and main exits 0 - a green job over a
    contradiction sitting on disk, because the workflow reads the exit code
    and nothing reads receipt-consistency.json. The entry therefore carries
    ``crashed: true``, ``build_receipt`` counts them, and main reports the run
    unresolved. A check that is UNKNOWN because its input said nothing
    (``green_job_zero_graded`` with no ``--job-conclusion``) is not crashed
    and does not change the exit code.

    The entry is still built by ``_result``: a broken ``_result`` is
    input-independent, and it must escape into main's net rather than be
    papered over by a literal written here.
    """
    results: list[dict[str, Any]] = []
    for check_id, check in CHECKS:
        try:
            results.append(
                check(
                    inputs,
                    job_conclusion=job_conclusion,
                    submitted_patch_bytes=submitted_patch_bytes,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one broken check, five good ones
            crashed: dict[str, Any] = dict(
                _result(
                    check_id,
                    UNKNOWN,
                    f"check did not complete; error: {type(exc).__name__}: {exc}",
                )
            )
            crashed["crashed"] = True
            results.append(crashed)
    return results


def build_receipt(inputs: Inputs, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "task_id": inputs.task_id,
        "inputs": {
            _GT_RUN_NAME: str(inputs.gt_run_path) if inputs.gt_run_path else None,
            _REPORT_NAME: str(inputs.report_path) if inputs.report_path else None,
            PROGRESS_SCHEMA: str(inputs.progress_path) if inputs.progress_path else None,
        },
        "checks": checks,
        "contradictions": sum(1 for check in checks if check["severity"] == CONTRADICTION),
        # A check that raised decided nothing. Counted here so a reader - and
        # main's exit code - can tell it apart from an UNKNOWN the inputs
        # themselves produced (H-1, round 7).
        "checks_crashed": sum(1 for check in checks if check.get("crashed") is True),
        "resolution_error": None,
    }


def build_unresolved_receipt(error: str, detail: str) -> dict[str, Any]:
    """The receipt written when the receipts could not be resolved at all.

    The step's ``::error`` tells a reader to see receipt-consistency.json, so
    the file has to exist for every nonzero exit - a refusal that writes
    nothing sends the reader to a path that was never created. It is not a
    check result: ``task_id`` stays null rather than degrading to the artifact
    root's name (``terminal-bench``), which read as a task that was checked,
    and every named check is reported UNKNOWN with the reason.
    """
    message = f"receipts not resolved ({error}): {detail}"
    # The ids come from the static registry and the entries are literals: this
    # receipt is the last thing written when something already failed, so it
    # must not execute a check - nor go through ``_result`` - to name them.
    # H-2 (round 6): enumerating the ids by CALLING run_checks re-ran the code
    # that had just raised, inside the handler for that very exception. An
    # input-independent bug therefore escaped main as exit 1 with a traceback
    # and no receipt at all, while exit 1 is the workflow's "these receipts
    # contradict each other" branch.
    checks = [
        {"check_id": check_id, "severity": UNKNOWN, "message": message}
        for check_id in CHECK_IDS
    ]
    return {
        "schema": SCHEMA,
        "task_id": None,
        "inputs": {_GT_RUN_NAME: None, _REPORT_NAME: None, PROGRESS_SCHEMA: None},
        "checks": checks,
        "contradictions": 0,
        "checks_crashed": 0,
        "resolution_error": error,
        "resolution_detail": detail,
    }


def _unresolved_detail(inputs: Inputs) -> str:
    """Say what WAS found, so "no run receipt" is a falsifiable claim.

    A refusal that only says "nothing was resolved" is indistinguishable from
    the checker having been pointed at the wrong directory, and the reader's
    next move differs completely between the two. So the detail names the
    trial that was found and the harness JSON it actually contained (bounded
    by ``_DETAIL_FILE_LIMIT``): run 35241999929's dead trial lists
    diagnostics.json, incident-replay.json and official-verifier-result.json,
    which says "harbor killed this trial before it wrote a receipt" and not
    "you gave me the wrong path".

    ``inputs.trial`` is the root itself when the CLI was pointed at a trial
    directory (M-2, round 8), so that mode gets the file list too rather than
    the no-trial sentence, which is the one place the two used to swap.
    """
    if inputs.trial is None:
        return (
            f"no Pier trial and no {_GT_RUN_NAME} or {_REPORT_NAME} under "
            f"{inputs.root}"
        )
    names = sorted({path.name for path in harness_receipts(inputs.trial)})
    shown = ", ".join(names[:_DETAIL_FILE_LIMIT]) or "none"
    if len(names) > _DETAIL_FILE_LIMIT:
        shown += f" (+{len(names) - _DETAIL_FILE_LIMIT} more)"
    return (
        f"trial {inputs.trial} wrote no {_GT_RUN_NAME} and no {_REPORT_NAME}; "
        f"harness JSON found there: {shown}"
    )


def _undecidable_detail(inputs: Inputs) -> str:
    """Name the run receipts that were read and decided nothing."""
    read = [
        str(path)
        for path in (inputs.gt_run_path, inputs.report_path)
        if path is not None
    ]
    return (
        "every check is UNKNOWN and none crashed: the run receipt(s) read - "
        + ", ".join(read)
        + " - carry no field any check reads, so nothing about this run was decided"
    )


def _unresolved(exc: BaseException, json_path: str | None) -> int:
    """Report an unhandled read as a receipt, never as a contradiction.

    Exit 1 is the workflow's "these receipts contradict each other" branch,
    and its ``::error`` sends the reader to receipt-consistency.json. An
    exception escaping main gave exactly that exit code with a traceback and
    no file, so the run reported a contradiction that had never been found
    and named evidence that was never written. Every read failure lands here
    instead: the receipt is always written, and rc=1 means contradiction only.
    """
    detail = f"{type(exc).__name__}: {exc}"
    _emit(build_unresolved_receipt("read_error", detail), json_path)
    print(f"::error title=Unresolved receipts::{detail}", file=sys.stderr)
    return 2


def _emit(receipt: dict[str, Any], json_path: str | None) -> bool:
    """Write the receipt to ``--json`` when given, otherwise to stdout.

    Returns False when it could not be written. Every nonzero exit sends the
    reader to this file, so a write that fails - an unwritable directory, a
    path whose parent is a file - has to be said out loud rather than raised
    past main as an exit code that means something else entirely.
    """
    try:
        text = json.dumps(receipt, indent=2, sort_keys=True)
        if json_path:
            path = Path(json_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    except (OSError, ValueError) as exc:
        print(
            f"::error title=Receipt not written::{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "artifact_dir",
        help=(
            "one task's artifact directory: Pier's job directory, the trial "
            "dir itself, or a root holding exactly one <task>__<hash>/agent/"
        ),
    )
    parser.add_argument(
        "--job-conclusion",
        choices=("success", "failure"),
        help="the CI job's own conclusion, which by itself proves nothing",
    )
    parser.add_argument(
        "--submitted-patch-bytes",
        type=int,
        help=(
            "bytes of the patch the grader actually received; overrides the "
            "size read from artifacts/model.patch or the evaluator's "
            "predictions.jsonl"
        ),
    )
    parser.add_argument("--json", dest="json_path", help="write the receipt here instead of stdout")
    args = parser.parse_args(argv)

    try:
        inputs = load_inputs(Path(args.artifact_dir))
    except AmbiguousTrialError as exc:
        _emit(build_unresolved_receipt("ambiguous_trial", str(exc)), args.json_path)
        print(f"::error title=Ambiguous trial::{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - the net below, at the read stage
        return _unresolved(exc, args.json_path)
    # Neither run receipt: nothing about this run was read, whatever the
    # layout. Reporting six UNKNOWNs under a name taken from the tree made an
    # unread artifact tree look like a task that had been read.
    #
    # H-1 (round 6): the progress receipt does not count towards resolution.
    # The workflow copies it into the tree it hands over, so it is present
    # whether or not anything else was found, and it names the task - which
    # is exactly the false-pass shape: a receipt labelled with a real task id
    # whose every check says UNKNOWN, exit 0.
    #
    # H-1 (round 7): neither does a trial DIRECTORY. The gate used to be
    # satisfied by the existence of ``<task>__<hash>/agent/``, which is made
    # by the runner before the agent has produced anything: run 35241999929's
    # trial died inside harbor and its agent/ holds only diagnostics.json,
    # incident-replay.json and official-verifier-result.json. Pointed at that
    # job directory the checker exited 0 with a real task id and six UNKNOWNs
    # - the same false pass, reached through the other branch. What resolves a
    # task is a RUN RECEIPT and nothing else; the flat layout (no trial
    # directory) stays supported on exactly the same terms. The two ways of
    # having none are still named apart, because they send the reader to
    # different places: no trial at all is usually the wrong path, while a
    # trial with no receipt is a run that died.
    if inputs.gt_run is None and inputs.report is None:
        error = "no_trial_found" if inputs.trial is None else "no_run_receipt"
        detail = _unresolved_detail(inputs)
        _emit(build_unresolved_receipt(error, detail), args.json_path)
        print(f"::error title=Unresolved receipts::{detail}", file=sys.stderr)
        return 2
    # run_checks contains a failing check itself now, so this net no longer
    # decides the verdict of five working checks (H-2). It stays because the
    # assembly around them can still break - ``_result`` itself, or
    # build_receipt reading task_id off a malformed receipt - and rc=1 must
    # mean "the receipts contradict each other" and nothing else, ever.
    try:
        checks = run_checks(
            inputs,
            job_conclusion=args.job_conclusion,
            submitted_patch_bytes=args.submitted_patch_bytes,
        )
        receipt = build_receipt(inputs, checks)
    except Exception as exc:  # noqa: BLE001 - see _unresolved
        return _unresolved(exc, args.json_path)
    # Round 9: the third door. A gt-run.json that parses as an object but
    # carries no key any check reads resolved the task, made every check
    # UNKNOWN, and exited 0 - six UNKNOWNs over a real task id, the shape the
    # two gates above exist to refuse. Six of six UNKNOWN with nothing crashed
    # is a run about which nothing was decided, and that is unresolved by
    # definition. A real receipt decides at least one check, so a healthy run
    # cannot trip this: the shipped emitter writes ~25 keys.
    if (
        not receipt["contradictions"]
        and not receipt["checks_crashed"]
        and all(check["severity"] == UNKNOWN for check in checks)
    ):
        detail = _undecidable_detail(inputs)
        _emit(build_unresolved_receipt("no_decidable_check", detail), args.json_path)
        print(f"::error title=Unresolved receipts::{detail}", file=sys.stderr)
        return 2
    written = _emit(receipt, args.json_path)
    # The order is the whole point. rc 1 means "these receipts contradict each
    # other" and it is decided by what was found on disk, so nothing that
    # happened afterwards may downgrade it: L-5 (round 6) had an unwritable
    # --json turn a real contradiction into rc 2, "nothing could be resolved",
    # over a reporting failure. rc 2 is for a run that did NOT resolve: a
    # check that crashed (H-1, round 7) decided nothing, and a receipt that
    # could not be written sends the reader to a file that is not there.
    if receipt["contradictions"]:
        return 1
    if receipt["checks_crashed"] or not written:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
