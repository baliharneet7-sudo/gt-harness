"""Provider-free audit of nested Mini-SWE/Harbor diagnostic artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from gt_engine.run_diagnostics import diagnose_artifact_root
from scripts.gt_audit import annotated_capability_rows

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


def _lsp_annotation(row: dict) -> str:
    """`` [VERDICT: detail]`` for an annotated row, else ``""``."""
    verdict = str(row.get("lsp_no_op_verdict") or "")
    return f" [{verdict}: {row.get('lsp_no_op_detail')}]" if verdict else ""


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
            f"[GT][{event.severity}][{event.code.value}] task={event.task_id} "
            f"phase={event.phase} cause={event.normalized_cause}"
        )
        print(line, file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            annotation = "error" if event.severity == "ERROR" else "warning"
            print(f"::{annotation} title={event.code.value}::{line}", file=sys.stderr)
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
            f"[GT][CAPABILITY][{row.get('state')}] {row.get('capability')} "
            f"required={row.get('required')} evidence={row.get('evidence')}"
            f"{_lsp_annotation(row)}"
        )
        print(line, file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            severity = "error" if row.get("required") else "warning"
            print(f"::{severity} title=capability_not_working::{line}", file=sys.stderr)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## GroundTruth diagnostic summary", "",
            "| Task | Primary | Fingerprint |", "|---|---|---|",
        ]
        lines.extend(
            f"| {row['task_id']} | {row['primary_diagnostic']} | `{row['fingerprint'][:16]}` |"
            for row in payload["tasks"]
        )
        if capabilities:
            lines.extend([
                "", "### Capabilities", "",
                "| Capability | State | Required | Worked | Evidence |",
                "|---|---|---|---|---|",
            ])
            lines.extend(
                f"| {row.get('capability')} | {row.get('state')} | "
                f"{'yes' if row.get('required') else 'no'} | "
                f"{_worked(row)} | "
                f"{row.get('evidence')}{_lsp_annotation(row)} |"
                for row in capabilities
            )
            if degraded:
                names = ", ".join(str(row.get("capability")) for row in degraded)
                lines.extend(["", f"**These did not work: {names}**"])
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
