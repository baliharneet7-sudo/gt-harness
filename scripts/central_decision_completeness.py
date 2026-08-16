"""Decision-completeness gate for the task-decisive context mechanism.

The task-decisive hypothesis is: the deterministic frame, delivered at the
first eligible call, names the concrete gap between the workspace state and
the task goal, so that any sampled reasoning path that reads it can reach the
correct result.  This script measures the deterministic half of that claim
without any model call:

1. **Frame completeness.**  Every task-decisive fact derived from the three
   legal sources (instruction, workspace scan, catalog) must be present in
   the delivered initial frame.  A derived fact that is missing from the
   frame is a delivery defect and fails the gate.

2. **Re-derivation parity.**  The probe re-derives decisive facts from the
   instruction plus the *delivered frame text alone* (no workspace).  When
   the frame is complete this re-derivation reproduces the same facts,
   proving the frame is self-sufficient: a solver that reads only the
   instruction and the frame is not missing anything the host could know.

This is the intrinsic decision-completeness gate: it is measured inside the
GT-on run and needs no GT-off arm and no temperature-0 solver.  Outcome
invariance across rollouts is a separate, later gate.

Usage:
    python -m scripts.central_decision_completeness --workspace <dir> \\
        --instruction <text> [--validation pytest -q] [--deliverable path]
    python -m scripts.central_decision_completeness --receipt <receipt.json> \\
        [--workspace <dir>] [--instruction <text>]

The receipt form extracts the instruction and catalog rows (required
validation / deliverable) from a central receipt so the same inputs the live
agent used are re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gt_engine.decisive_derivation import (
    DecisiveStatus,
    build_workspace_scan,
    derive_decisive_facts,
)

GATE_NAME = "DECISION_COMPLETENESS_GATE"


def _receipt_inputs(receipt: dict) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    instruction = ""
    validation_commands: list[str] = []
    deliverables: list[str] = []

    def walk(value) -> None:
        nonlocal instruction
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "task" and isinstance(item, str) and not instruction:
                    instruction = item
                elif key in {"validation_commands", "required_checks"} and isinstance(
                    item, (list, tuple)
                ):
                    validation_commands.extend(str(x) for x in item)
                elif key in {"deliverables", "task_deliverables"} and isinstance(
                    item, (list, tuple)
                ):
                    deliverables.extend(str(x) for x in item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(receipt)
    if not instruction:
        raise ValueError("receipt contains no task instruction text")
    return instruction, tuple(dict.fromkeys(validation_commands)), tuple(
        dict.fromkeys(deliverables)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=False, default=None)
    parser.add_argument("--instruction", required=False, default=None)
    parser.add_argument("--validation", action="append", default=[])
    parser.add_argument("--deliverable", action="append", default=[])
    parser.add_argument("--receipt", required=False, default=None)
    parser.add_argument("--frame", required=False, default=None)
    args = parser.parse_args(argv)

    instruction = args.instruction
    validation_commands = tuple(args.validation)
    deliverables = tuple(args.deliverable)
    if args.receipt:
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
        (
            receipt_instruction,
            receipt_validation,
            receipt_deliverables,
        ) = _receipt_inputs(receipt)
        instruction = instruction or receipt_instruction
        validation_commands = validation_commands or receipt_validation
        deliverables = deliverables or receipt_deliverables

    if not instruction or not args.workspace:
        parser.error("--workspace and --instruction (or a --receipt) are required")

    workspace_root = Path(args.workspace)
    if not workspace_root.is_dir():
        parser.error(f"workspace directory not found: {workspace_root}")

    scan = build_workspace_scan(str(workspace_root))
    derivation = derive_decisive_facts(
        instruction=instruction,
        workspace=scan,
        validation_commands=validation_commands,
        deliverables=deliverables,
        source_revision="replay",
    )

    lines: list[str] = []
    failures: list[str] = []

    lines.append(f"{GATE_NAME} workspace={workspace_root}")
    lines.append(f"instruction_chars={len(instruction)}")
    lines.append(f"scan_entries={len(scan)}")
    lines.append(f"derivation_status={derivation.status.value}")
    lines.append(f"derivation_reasons={','.join(derivation.reason_codes) or '-'}")
    lines.append(f"derived_fact_count={len(derivation.facts)}")
    for fact in derivation.facts:
        lines.append(
            f"fact kind={fact.kind.value} path={fact.path or '-'} line={fact.line} "
            f"gap={fact.gap_text!r}"
        )

    frame_text = instruction
    if args.frame:
        frame_text = args.frame
    elif args.receipt:
        frame_candidates = _receipt_frames(receipt)
        if frame_candidates:
            frame_text = frame_candidates[0]

    # 1. Frame completeness: every derived fact must be covered by the
    #    delivered initial frame text.
    covered = 0
    for fact in derivation.facts:
        present = bool(fact.gap_text) and fact.gap_text in frame_text
        covered += int(present)
        if not present:
            failures.append(f"frame_missing_fact kind={fact.kind.value} path={fact.path}")
    lines.append(f"frame_covered_facts={covered}/{len(derivation.facts)}")

    # 2. Re-derivation parity: re-derive from instruction + frame alone.  The
    #    frame must be self-sufficient for the facts the host could derive.
    probe = derive_decisive_facts(
        instruction=frame_text,
        workspace=scan,
        validation_commands=validation_commands,
        deliverables=deliverables,
        source_revision="probe",
    )
    parity = len(probe.facts) >= len(derivation.facts) and all(
        any(p.kind is f.kind and p.path == f.path for p in probe.facts)
        for f in derivation.facts
    )
    lines.append(f"re_derivation_parity={'PASS' if parity else 'FAIL'}")
    if not parity:
        failures.append("re_derivation_parity_failed")

    if derivation.status is DecisiveStatus.ABSTAINED:
        lines.append("derivation_abstained=true")
        lines.append(f"{GATE_NAME} = PASS (abstention is the honest outcome)")

    if failures:
        lines.append(f"{GATE_NAME} = FAIL")
        lines.extend(f"FAIL: {failure}" for failure in failures)
        print("\n".join(lines))
        return 1

    lines.append(f"{GATE_NAME} = PASS")
    print("\n".join(lines))
    return 0


def _receipt_frames(receipt: dict) -> list[str]:
    """Collect rendered provider-context frame texts from a central receipt."""
    frames: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"rendered_text", "frame_text"} and isinstance(item, str) and item:
                    frames.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(receipt)
    return frames


if __name__ == "__main__":
    sys.exit(main())