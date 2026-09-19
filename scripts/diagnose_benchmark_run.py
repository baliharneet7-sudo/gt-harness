"""Provider-free audit of nested Mini-SWE/Harbor diagnostic artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

# Launched by path (python scripts/diagnose_benchmark_run.py) the repository
# root is not on sys.path and neither gt_engine nor the shared annotation
# builder can be imported; every workflow uses python -m, but the path form
# must keep working too (review 14 MEDIUM-1, review 15 follow-up).
if __package__ in (None, ""):
    import sys as _sys

    _REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
    if _REPOSITORY_ROOT not in _sys.path:
        _sys.path.insert(0, _REPOSITORY_ROOT)

from gt_engine.run_diagnostics import diagnose_artifact_root
from scripts.gh_annotations import (
    ANNOTATION_FIELD_LIMIT,
    ANNOTATION_TRUNCATION,
    emit_line,
    gh_command,
    gh_command_escaped,
    gh_escape,
)
from scripts.gt_audit import annotated_capability_rows

# REVIEW-12 MEDIUM. Every line this module prints to stderr lands in the same
# stream the Actions runner parses for WORKFLOW COMMANDS, and every field it
# interpolates is read out of an artifact the model wrote inside its own
# container: a capability row's ``capability``/``state``/``evidence`` come
# straight off ``<task>/agent/diagnostics.json``, and a diagnostics event's
# ``task_id`` and ``phase`` are ``str(row.get(...))`` in
# gt_engine.run_diagnostics._load_events with no character class imposed.
# ``severity`` and ``code`` are the two that are not: the first is validated
# against three names and the second is a closed StrEnum.
#
# A planted ``\n::stop-commands::x\n`` therefore silenced every later
# annotation in the job, and ``\n::error title=Grader::TASK PASSED`` forged a
# verdict - in two workflows that run this on a paid attestation root
# (deepswe_gt_harness_product_p0731.yaml, swelive_gt_harness_paid.yaml).
#
# So: every interpolated field goes through ``gh_escape`` and the annotation
# is built by ``gh_command_escaped``. Escaping only the ``::`` line would
# leave the hole open - the runner does not care which print statement a line
# came from, only that it starts at column zero.
#
# REVIEW-13 MEDIUM-1: the bound is per FIELD, never on the composed line.
# Both lines below are model-written at the head and host-computed at the tail
# (``phase=<artifact> cause=<normalised>``,
# ``evidence=<artifact> [VERDICT: <what the harness decided>]``). A 512-char
# bound applied to the whole line spends the budget on the container's bytes
# and truncates the verdict away - the one part of the line the container
# cannot forge, and the only reason the line is printed at all. So each field
# is bounded on its own and ``gh_command_escaped`` verifies the composition
# rather than cutting it again.

# The collectors write the diagnostics document to exactly these places
# under a trial directory, and the trial sits at the root, one level below it
# (``<task>/``) or two (Pier's ``<job-name>/<task>__<hash>/``). A task
# directory also holds the task's whole repository checkout, so an unbounded
# rglob walks that checkout once per task and can pick a vendored look-alike
# out of it as this task's own document - which then anchors the promotion
# receipts to a directory inside the checkout and reports its verdict as ours.
# A new collector layout is added here deliberately, never discovered by
# walking. Same bounding RULE as gt_audit._MINISWE_REPORT_GLOBS and
# verify_run_receipts._HARNESS_GLOBS, not the same list: those enumerate every
# harness-owned location for any receipt, and this names only the two places a
# collector writes THIS document. Anything wider here is a checkout walk.
_DIAGNOSTICS_GLOBS = (
    "agent/diagnostics.json",
    "agent/gt-state/*/diagnostics.json",
)
_TRIAL_PREFIXES = ("", "*/", "*/*/")


def _is_trial(path: Path) -> bool:
    """A trial directory: one that OWNS the ``agent/`` tree a collector wrote.

    Unlike verify_run_receipts._is_trial and tb2_report._is_trial, the
    directory NAME is no part of the test here. Those two resolve Pier trials,
    always named ``<task>__<hash>``; this walker also has to anchor the flat
    ``<root>/<task>/agent/`` layout, where the directory is named for a task id
    that carries no ``__``. The owned ``agent/`` is the whole signal.
    """
    return path.is_dir() and path.joinpath("agent").is_dir()


def _inside_a_trial(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` sits below a trial, i.e. inside its checkout.

    The rule, and it is the SAME rule in verify_run_receipts and in
    tb2_report (each keeps its own copy - this is a CI widget, those are a gate
    and a reporting tool - and tests/test_tb2_report.py asserts the three
    agree): ``candidate`` is inside a trial when some ancestor between it and
    the resolved ``root``, ``root`` INCLUDED, owns an ``agent/``.

    L-1: the three prefixes were searched with no guard at all, and the deeper
    two reach INSIDE a resolved trial - where a checkout directory that owns an
    ``agent/`` (a vendored package, a fixture tree, ``<trial>/sub__x/agent/``)
    had its diagnostics document read as a task's own. That document is what
    anchors the task directory whose promotion receipts decide the verdict, so
    a checkout's clean receipt could launder a real fault. Nothing below a
    trial is ever a trial, so every ancestor up to ``root`` is tested; ``root``
    itself is always searchable, and when it IS the trial - a caller pointed at
    one task's trial directory rather than at the bundle - its children are the
    checkout and nothing in them is ours.

    M-1 (round 6): both paths are resolved first. ``Path(".").parent`` IS
    ``Path(".")``, so the walk over a RELATIVE root terminated before its first
    step and answered False for everything under it, which put the checkout
    back in the search the moment a caller passed ``.``.

    L-3 (round 6): resolving both sides also means a candidate can resolve
    OUT from under the root. One that does is excluded, never searched.
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


def _diagnostics_documents(root: Path) -> list[Path]:
    """Every diagnostics document in the harness-owned subtrees under ``root``.

    Order is stable (trial depth, then the glob list, then name) so two runs
    over the same tree anchor each task to the same directory.
    """
    found: list[Path] = []
    for prefix in _TRIAL_PREFIXES:
        depth = prefix.count("/")
        for pattern in _DIAGNOSTICS_GLOBS:
            for path in sorted(root.glob(prefix + pattern)):
                if not path.is_file():
                    continue
                trial = root.joinpath(*path.relative_to(root).parts[:depth])
                if not _is_trial(trial) or _inside_a_trial(root, trial):
                    continue
                found.append(path)
    return found


def _task_dirs_by_id(root: Path) -> dict[str, Path]:
    """Map each task id to the directory that owns its ``agent/`` tree.

    diagnose_artifact_root returns capability rows keyed by task id and drops
    the path it read them from, but the promotion receipts live at
    ``<task>/agent/gt-state/*/lsp_receipts/``, so the directory has to be found
    again. Both diagnostics locations (``agent/diagnostics.json`` and the
    gt-state copy of it) sit under the same ``agent/``, so the parent of that
    ``agent/`` is the task directory either way. First path wins, matching
    run_diagnostics' own first-document-wins dedup; an unreadable document is
    skipped rather than guessed at, which leaves the row UNKNOWN.
    """
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for path in _diagnostics_documents(root):
        agent = next((parent for parent in path.parents if parent.name == "agent"), None)
        if agent is None:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        task_id = str(document.get("task_id") or "") if isinstance(document, dict) else ""
        if task_id:
            found.setdefault(task_id, agent.parent)
    return found


def _annotated(root: Path, rows: list[dict]) -> list[dict]:
    """Rows as sealed, plus a no-op verdict on the rows that need one.

    The verdict is gt_audit's classifier, not a second opinion: one classifier
    means this CI widget and the Tier-2 audit cannot disagree about whether a
    task that promoted nothing was right to.

    Copies only - the printed JSON document above is the sealed report and
    keeps the bytes gt_session wrote. A task whose directory cannot be located
    falls through to ``root``, where the receipt glob finds nothing and the row
    classifies UNKNOWN: not being able to look is not a clean bill of health.
    """
    if not rows:
        return []
    task_dirs = _task_dirs_by_id(root)
    annotated: list[dict] = []
    for row in rows:
        task_dir = task_dirs.get(str(row.get("task_id") or ""), root)
        annotated.extend(annotated_capability_rows(task_dir, {"capabilities": [row]}))
    return annotated


def _annotate(kind: str, title: str, line: str) -> None:
    """Emit one annotation for one row, or say why it could not be emitted.

    ``gh_verbatim`` REFUSES a composed message past the line allowance, and it
    is right to: past that it is a caller defect, not a data condition. But
    this renderer runs at the END of a job that has already paid for its run,
    and a ValueError escaping here loses every LATER annotation and the whole
    GITHUB_STEP_SUMMARY over the text of ONE row (REVIEW-14 HIGH-1, which is
    exactly what an oversized line did). A renderer that crashes on
    adversarial input is worse than one that says so, so the refusal is caught
    per row and reported as itself.

    The fallback carries no artifact-derived text at all: ``title`` is a
    closed DiagnosticCode value or a literal, and the length is an integer.
    """
    try:
        emit_line(gh_command_escaped(kind, title, line))
    except ValueError:
        emit_line(
            gh_command(
                "error",
                "Diagnostics renderer",
                f"{title}: line could not be rendered ({len(line)} chars)",
            )
        )


def _lsp_annotation(row: dict) -> str:
    """`` [VERDICT: detail]`` for an annotated row, else ``""``."""
    verdict = str(row.get("lsp_no_op_verdict") or "")
    return f" [{verdict}: {row.get('lsp_no_op_detail')}]" if verdict else ""


# REVIEW-15 MEDIUM: GITHUB_STEP_SUMMARY IS A TABLE ------------------------- #
#
# The escaping above is the RUNNER's syntax and stops at the runner. The step
# summary is markdown, where a row ends at a newline and a cell ends at ``|``
# - and both characters are legal inside a capability row's ``evidence``, a
# diagnostics row's ``task_id`` and everything else this widget reads off an
# artifact the model wrote inside its own container. A planted
# ``broken |<LF>| dense_retrieval | WORKING | yes | yes | all good |`` closed
# the real cell, ended the real row and added a SECOND row asserting that a
# capability worked, in the one widget whose job is to say which did not.
#
# ``%0A`` would be wrong here (markdown does not decode it), so the treatment
# is markdown's: the row separator becomes a space and the cell separator is
# backslash-escaped. Same bound and same ASCII truncation marker as
# gh_escape, from the same module, for the same reason - a model-writable
# field is unbounded and one planted string otherwise buries the widget.
#
# Everything ``str.splitlines`` treats as a terminator is folded, not only
# CR/LF: the summary file is read back by tooling that splits it, and a
# renderer that stops one character short of its reader is the same hole one
# layer up.
_MD_ROW_BREAKS = re.compile(r"[\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def _md_cell(value: object) -> str:
    """One artifact-derived markdown cell: one row, one cell, bounded.

    The bound is applied to the RAW text and the escaping runs after it, so a
    ``\\|`` can never be cut in half - a lone trailing backslash would escape
    the pipe the RENDERER wrote and merge this cell into the next.

    Host-computed literals stay raw - the column headers, ``yes``/``no``
    and ``**NO**`` - because passing them through would make the diff lie
    about which fields are the untrusted ones. The fingerprint IS treated
    even though it is a host-computed digest today: it is read out of the
    same mapping as the two fields beside it, and a cell that is safe only
    because of what the producer currently puts in it is the next hole.
    """
    text = _MD_ROW_BREAKS.sub(" ", str(value))
    if len(text) > ANNOTATION_FIELD_LIMIT:
        text = text[:ANNOTATION_FIELD_LIMIT] + ANNOTATION_TRUNCATION
    # Review 18: escape the backslash FIRST, or a container-written "\|" becomes
    # an escaped backslash followed by a live pipe and a permissive renderer
    # splits the row there. A backtick would close the code span the
    # fingerprint is rendered in and backslash escapes are inert inside a
    # code span, so it is replaced, not escaped. All after the bound.
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("`", "'")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    args = parser.parse_args(argv)
    report = diagnose_artifact_root(args.root, strict=args.strict)
    payload = report.to_mapping()
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    # Summary retention is mandatory. The compatibility flag is accepted but
    # no longer controls whether the artifact exists.
    _ = args.write_summary
    (args.root / "diagnostic-summary.json").write_text(
        rendered + "\n", encoding="utf-8"
    )
    for event in report.diagnostics:
        line = (
            f"[GT][{gh_escape(event.severity)}]"
            f"[{gh_escape(event.code.value)}] "
            f"task={gh_escape(event.task_id)} "
            f"phase={gh_escape(event.phase)} "
            f"cause={gh_escape(event.normalized_cause)}"
        )
        emit_line(line)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            annotation = "error" if event.severity == "ERROR" else "warning"
            _annotate(annotation, event.code.value, line)
    # Capabilities that did not work must be visible at the END of the task,
    # not only as an error string inside a receipt someone has to go and read.
    # A run whose language servers or embedder never came up finishes looking
    # normal otherwise, and the person reading the result is the last one who
    # should have to reconstruct that GT ran with less than GT has.
    def _worked(row: dict) -> str:
        """Tri-valued: a capability never asked to run did not fail to run.

        This column asks "did this work", and bold NO is the loudest cell in
        the table. For a capability deliberately switched off the answer is
        not no, it is not-applicable - printing NO moved the cry-wolf out of
        stderr and left it in the widget a human actually reads.
        """
        if row.get("verified"):
            return "yes"
        return "n/a" if not row.get("triggered") else "**NO**"

    # `lsp_promotion DEGRADED terminal_no_op:nothing_promotable` reads the same
    # for a task with no LSP-serviceable language (extract-elf is C/ELF; run
    # 35293191813 reported exactly this and was right) and for a serviceable
    # language that was never promoted, which is a fault. The verdict is
    # appended to the evidence so the reader is not left guessing; no state, no
    # column and no exit code moves.
    capabilities = _annotated(args.root, [row for row in payload.get("capabilities", [])
                                          if isinstance(row, dict)])
    # Keyed on refused/degraded, not on `not verified`. UNEXERCISED also has
    # verified False, and it is what a capability deliberately switched off
    # reports - so a GT-off control run was named in the did-not-work line and
    # raised a CI error for doing exactly what it was asked. The table below
    # still shows it as not-worked, which is honest; being called out as a
    # failure is not.
    degraded = [row for row in capabilities
                if row.get("refused") or row.get("degraded")]
    for row in degraded:
        line = (
            f"[GT][CAPABILITY][{gh_escape(row.get('state'))}] "
            f"{gh_escape(row.get('capability'))} "
            f"required={gh_escape(row.get('required'))} "
            f"evidence={gh_escape(row.get('evidence'))}"
            f"{gh_escape(_lsp_annotation(row))}"
        )
        emit_line(line)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            severity = "error" if row.get("required") else "warning"
            _annotate(severity, "capability_not_working", line)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## GroundTruth diagnostic summary", "",
            "| Task | Primary | Fingerprint |", "|---|---|---|",
        ]
        lines.extend(
            f"| {_md_cell(row['task_id'])} | {_md_cell(row['primary_diagnostic'])} "
            f"| `{_md_cell(row['fingerprint'][:16])}` |"
            for row in payload["tasks"]
        )
        if capabilities:
            lines.extend([
                "", "### Capabilities", "",
                "| Capability | State | Required | Worked | Evidence |",
                "|---|---|---|---|---|",
            ])
            # The evidence and the verdict are bounded SEPARATELY, and the
            # order matters: ``evidence`` is model-written and the
            # ``[VERDICT: ...]`` after it is the harness's answer to "was
            # promoting nothing right here?". One bound over the composed cell
            # spends the budget on the container's bytes and cuts the verdict
            # off - REVIEW-13 MEDIUM-1, in markdown this time.
            lines.extend(
                f"| {_md_cell(row.get('capability'))} | {_md_cell(row.get('state'))} | "
                f"{'yes' if row.get('required') else 'no'} | "
                f"{_worked(row)} | "
                f"{_md_cell(row.get('evidence'))}{_md_cell(_lsp_annotation(row))} |"
                for row in capabilities
            )
            if degraded:
                names = ", ".join(
                    _md_cell(row.get("capability")) for row in degraded
                )
                lines.extend(["", f"**These did not work: {names}**"])
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
