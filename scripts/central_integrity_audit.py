"""Fail-closed benchmark-integrity audit for the host-owned central runtime.

GroundTruth's evidence may be drawn only from the three legitimate sources
available during the benchmark: the task instruction, the repository source in
the task workspace, and the agent's own observed execution results.  It must
never read, infer, or depend on grader-only artifacts (hidden verifier tests,
the reference solution, held-out test files, or host verifier outputs such as
``tests/``, ``solution/``, ``REF``, ``test_outputs.py``, ``reward.txt``, or
``ctrf.json``).

This audit proves that boundary two ways:

1. **Static source boundary** — the active runtime modules
   (``gt_engine/**`` and ``eval/gt_central_agent.py``) that produce
   model-visible evidence must never open, read, or glob a grader-only
   artifact path.  The completion controller must compile predicates only from
   the task-instruction text and workspace-rooted paths.
2. **Per-receipt evidence provenance** — every model-visible delivery's
   evidence must carry a legal source (task-start instruction, checkout source,
   or observed execution), and no delivered claim/anchor may reference a
   grader-only path.

This is a compliance demonstration, not a change to the benchmark denominator,
verifier, or scoring.  It never excludes a task from the solve-rate
denominator.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gt_engine.delivery_audit import audit_provider_deliveries  # noqa: E402
from gt_engine.observed_facts import (  # noqa: E402
    extract_observed_facts,
)

# Grader-only artifact path markers that must never appear as a read source in
# the active runtime.  These are deliberately specific to hidden verifier /
# reference / held-out artifacts; ordinary source path segments like a
# repository's own ``tests/`` directory are NOT flagged.
GRADER_ONLY_MARKERS: tuple[str, ...] = (
    "/solution/",
    "solution/",
    "test_outputs.py",
    "reward.txt",
    "ctrf.json",
    "/verifier/",
    "verifier/report.json",
    "REF =",
)

# Active runtime modules that produce model-visible evidence / controller
# decisions.  Post-hoc outcome tools (scripts/central_deep_metrics.py,
# scripts/deepswe_outcome.py, ...) read reward.txt AFTER the benchmark purely
# for reporting and are intentionally out of scope: they run post-hoc and are
# never present during the task.  Only these paths are audited.
RUNTIME_DIRS: tuple[str, ...] = ("gt_engine",)
RUNTIME_FILES: tuple[str, ...] = (
    "eval/gt_central_agent.py",
    "eval/miniswe_central_agent.py",
)

# File-read / glob / subprocess call names whose path argument must be legal.
_READ_CALL_NAMES: frozenset[str] = frozenset(
    {
        "open",
        "read_text",
        "read_bytes",
        "readlines",
        "rglob",
        "glob",
        "load",
        "loads",
        "tomllib",
        "subprocess",
        "Popen",
        "check_output",
        "run",
        "getsource",
    }
)

_COMPLETION_COMPILER = "compile_completion_plan"
_COMPLETION_COMPILER_DOC = "Compile all mechanically equivalent predicates"

# Legal evidence origins recorded on deliveries (from context_frontier /
# delivery_audit semantic support).
LEGAL_ORIGINS: frozenset[str] = frozenset(
    {
        "task_start",
        "checkout_source",
        "preexisting_repository",
        "model_authored",
        "observed_external",
        "external_runtime",
        "task_deliverable",
    }
)


def _runtime_paths() -> list[Path]:
    paths: list[Path] = []
    for subdir in RUNTIME_DIRS:
        for candidate in sorted((PROJECT_ROOT / subdir).rglob("*.py")):
            paths.append(candidate)
    for rel in RUNTIME_FILES:
        candidate = PROJECT_ROOT / rel
        if candidate.exists():
            paths.append(candidate)
    return paths


def _is_docstring(node: ast.AST, source_lines: list[str]) -> bool:
    """True when a String constant is a standalone docstring/comment context."""
    parent = getattr(node, "_parent", None)
    if isinstance(parent, ast.Expr):
        return True
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    lineno = getattr(node, "lineno", None)
    if not isinstance(lineno, int) or lineno - 1 >= len(source_lines):
        return False
    stripped = source_lines[lineno - 1].lstrip()
    return stripped.startswith('"""') or stripped.startswith("'''") or stripped.startswith("#")


def _annotate_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node  # type: ignore[attr-defined]


def _path_literal(ast_node: ast.AST) -> str | None:
    """Best-effort extraction of a path/command string from a call/const."""
    if isinstance(ast_node, ast.Constant) and isinstance(ast_node.value, str):
        return ast_node.value
    if isinstance(ast_node, ast.JoinedStr):
        return None
    if isinstance(ast_node, ast.Call) and isinstance(ast_node.func, ast.Name):
        if ast_node.func.id in {"Path", "os.path.join", "PurePosixPath", "PurePath"}:
            return None
    return None


def _static_source_boundary() -> dict[str, object]:
    """Scan active runtime for grader-only read sources and instruction-only
    completion compilation."""

    violations: list[str] = []
    checked_files: list[str] = []
    completion_ok = False

    for path in _runtime_paths():
        rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        checked_files.append(rel)
        source_lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            violations.append(f"{rel}:unparsable")
            continue
        _annotate_parents(tree)

        if _COMPLETION_COMPILER in source and _COMPLETION_COMPILER_DOC in source:
            completion_ok = True

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name not in _READ_CALL_NAMES:
                continue
            # Inspect positional args and string-keyword args for grader markers.
            args: list[str] = []
            for arg in node.args:
                literal = _path_literal(arg)
                if literal:
                    args.append(literal)
            for kw in node.keywords:
                if kw.arg in {"path", "file", "name", "open", "command"}:
                    literal = _path_literal(kw.value)
                    if literal:
                        args.append(literal)
            for arg in args:
                for marker in GRADER_ONLY_MARKERS:
                    if marker in arg:
                        lineno = getattr(node, "lineno", None)
                        violations.append(
                            f"{rel}:{lineno}:read_source_grader_marker:{marker}:{arg.strip()[:80]}"
                        )

        # Also flag any grader marker string that is NOT a docstring/comment and
        # is not clearly an exclusion (never/not/exclude/forbid) — a defensive
        # sweep for markers embedded as data.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            for marker in GRADER_ONLY_MARKERS:
                if marker not in value:
                    continue
                if _is_docstring(node, source_lines):
                    continue
                parent = getattr(node, "_parent", None)
                context_is_exclusion = isinstance(parent, ast.Compare)
                if context_is_exclusion:
                    continue
                lineno = getattr(node, "lineno", None)
                violations.append(
                    f"{rel}:{lineno}:grader_marker_outside_exclusion:{marker}:{value.strip()[:80]}"
                )

    return {
        "checked_files": checked_files,
        "completion_instruction_only": completion_ok,
        "violations": violations,
        "source_boundary_proven": bool(checked_files) and not violations,
    }


def _trajectory_observed_markers(trajectory: dict) -> int:
    """Count mechanically recognizable observed-fact markers in a trajectory's
    tool outputs (source 3).  Uses the same pattern table as the live engine."""

    count = 0
    seen: set[str] = set()
    for message in trajectory.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text += str(part.get("text") or "")
        extra = message.get("extra") or {}
        raw = str(extra.get("raw_output") or "") or text
        command = str(extra.get("command") or "")
        facts = extract_observed_facts(
            command=command,
            output=raw,
            source_revision="audit",
            evidence_action=0,
            eligible_call=1,
            already_delivered=seen,
        )
        for fact in facts:
            seen.add(fact.fact_id)
            count += 1
    return count


def _abstention_gap(receipt: dict, trajectory: dict | None, task: str) -> list[str]:
    """Flag tasks where the model observed decision-relevant facts (source 3)
    but GT delivered none of them — the extract-elf recurrence gate."""

    observed = (receipt.get("observed_facts") or {}).get("fact_deliveries") or []
    if observed:
        return []
    if trajectory is None:
        return []
    markers = _trajectory_observed_markers(trajectory)
    if markers:
        return [
            f"{task}:observed_fact_abstention_gap:{markers}_markers_seen_but_0_delivered"
        ]
    return []


def _receipt_integrity(receipt: dict, task: str) -> tuple[list[dict], list[str]]:
    """Validate every model-visible delivery's evidence provenance is legal."""

    failures: list[str] = []
    rows: list[dict] = []
    all_rows, _delivery_failures, _totals = audit_provider_deliveries(receipt, task=task)
    for row in all_rows:
        raw = row.get("raw") or {}
        claims_legal = True
        # Inspect selected_evidence / claim_metadata origin+authority.
        for evidence in (row.get("selected_evidence") or []) + (row.get("claim_metadata") or []):
            if not isinstance(evidence, dict):
                continue
            origin = str(evidence.get("origin") or "")
            if origin and origin not in LEGAL_ORIGINS:
                failures.append(
                    f"{task}:illegal_evidence_origin:{row['surface']}:{row['surface_index']}:{origin}"
                )
                claims_legal = False
        # Inspect delivered anchors/facts for grader path markers.
        for key in ("claim_anchors", "anchors", "fact_paths", "paths"):
            for item in (raw.get(key) or ()):
                text = str(item)
                for marker in GRADER_ONLY_MARKERS:
                    if marker in text:
                        failures.append(
                            f"{task}:delivery_grader_path:{row['surface']}:"
                            f"{row['surface_index']}:{marker}:{text[:60]}"
                        )
        for fact in (raw.get("facts") or ()):
            if not isinstance(fact, dict):
                continue
            path = str(fact.get("path") or "")
            for marker in GRADER_ONLY_MARKERS:
                if marker in path:
                    failures.append(
                        f"{task}:delivery_grader_fact_path:{row['surface']}:"
                        f"{row['surface_index']}:{marker}:{path[:60]}"
                    )
        rows.append(
            {
                "surface": row["surface"],
                "surface_index": row["surface_index"],
                "claims_legal": claims_legal,
                "chars": row.get("chars"),
            }
        )
    return rows, failures


def audit_run_root(root: Path) -> dict:
    """Run the static source boundary plus per-receipt provenance over a tree."""

    static = _static_source_boundary()
    static_failures = list(static["violations"])
    receipts = sorted(root.rglob("central_receipt.json")) if root.exists() else []
    per_task: dict[str, object] = {}
    receipt_failures: list[str] = []
    for receipt_path in receipts:
        task = receipt_path.parent.parent.name
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt_failures.append(f"{task}:unreadable_receipt")
            continue
        rows, failures = _receipt_integrity(receipt, task=task)
        per_task[task] = {
            "deliveries": rows,
            "delivery_integrity_ok": not failures,
            "delivery_failures": failures,
        }
        receipt_failures.extend(failures)
        trajectory_path = receipt_path.parent / "miniswe_trajectory.json"
        trajectory = None
        if trajectory_path.exists():
            try:
                trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                trajectory = None
        gap_failures = _abstention_gap(receipt, trajectory, task=task)
        per_task[task]["abstention_gap"] = gap_failures
        receipt_failures.extend(failures)

    all_failures = static_failures + receipt_failures
    abstention_gaps = [
        gap
        for result in per_task.values()
        for gap in (result.get("abstention_gap") or [])
    ]
    proven = bool(static["checked_files"]) and not all_failures
    return {
        "schema": "gt.central_integrity_audit.v1",
        "run_root": str(root.resolve()) if root.exists() else "",
        "static": static,
        "receipts_audited": len(receipts),
        "per_task": per_task,
        "abstention_gaps": abstention_gaps,
        "failures": all_failures,
        "audit_status": "INTEGRITY_CERTIFIED" if proven else "INTEGRITY_FAILED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Optional run-root tree containing central_receipt.json files to audit.",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    report = audit_run_root(args.run_root)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    static_ok = bool(report["static"]["source_boundary_proven"])
    print("EVIDENCE_SOURCE_ALLOWLIST_PROVEN" if static_ok else "EVIDENCE_SOURCE_ALLOWLIST_FAILED")
    print(
        "NO_GRADER_ACCESS_PROVEN"
        if report["audit_status"] == "INTEGRITY_CERTIFIED"
        else "NO_GRADER_ACCESS_FAILED"
    )
    return 0 if report["audit_status"] == "INTEGRITY_CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
