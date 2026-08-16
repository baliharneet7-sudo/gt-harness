"""Replay archived GT-on trajectories against the task-decisive mechanism.

For each archived task directory (containing ``central_receipt.json`` and
``miniswe_trajectory.json``), this script reconstructs the task inputs that
the live agent used — the instruction (from the trajectory's user message)
and the required validation/deliverable catalog rows (from the receipt's
persistent-state catalog) — and re-runs the deterministic decisive
derivation over the workspace.

The workspace itself is reconstructed conservatively from the trajectory's
own tool observations (``cat``/``head``/``sed`` outputs that are provably
exact file reads).  Every reconstructed entry is labeled
``reconstructed=true``; a decisive path that cannot be reconstructed is
reported as ``workspace_incomplete_for_path`` and its detector abstains.
This replay therefore proves the derivation's *effect on the first
provider request* (frame moved to call 1) using only archived artifacts; it
does not claim full workspace fidelity.

Per task the report shows:

- task class (which detectors would fire),
- derived decisive facts (bounded text),
- the archived call-1 persistent context characters,
- ``frame_shift_to_call_1`` = the archived call 1 carried no persistent
  frame (0 chars) and the derivation now produces a decisive frame for
  call 1.

Usage:
    python -m scripts.central_decisive_replay <task-dir> [<task-dir> ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from gt_engine.decisive_derivation import (
    DecisiveStatus,
    WorkspaceEntry,
    derive_decisive_facts,
)

CAT_READ_RE = re.compile(r"(?:^|&&)\s*cat(?:\s+-[A-Za-z]+)?\s+([^\s&;|>]+)")
LS_DIR_RE = re.compile(
    r"(?:^|&&)\s*ls\s+(?:-[A-Za-z]+\s+)?([A-Za-z0-9_./~][^\s&;|]*)"
)
FIND_RE = re.compile(
    r"(?:^|&&)\s*find\s+([^\s&;|]+?)\s+-type\s+f(?:\s+-not\s+-path\s+'\S*\.git\S*'\s*)?"
)
OD_RE = re.compile(r"(?:^|&&)\s*od\s+-A\s+x\s+-t\s+x1z?\s+([^\s&;|]+)")
CD_RE = re.compile(r"^\s*cd\s+(\S+)\s*(?:&&\s*)?")
WRITE_RE = re.compile(r"(?:^|\s)(?:>|>>|2>)\s*(\S+)")
CAT_WRITE_RE = re.compile(r"^\s*cat\s+>\s+(\S+)")
TEE_RE = re.compile(r"(?:^|\s)tee\s+(\S+)")
LS_ROW_RE = re.compile(
    r"^[-d]\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+\S+\s+(.+)$",
    re.MULTILINE,
)
OD_LINE_RE = re.compile(r"^([0-9a-f]+)\s+((?:[0-9a-f]{4}\s+)+)", re.MULTILINE)


def _norm(path: str, cwd: str) -> str:
    path = str(path or "").strip().strip("'\"")
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"{cwd.rstrip('/')}/{path}"
    path = path.replace("\\", "/")
    if path == "/app" or path.startswith("/app/"):
        path = path[5:]
    path = re.sub(r"/{2,}", "/", path)
    path = re.sub(r"(^|/)\./", r"\1", path)
    return path.lstrip("/")


def _instruction(trajectory: dict) -> str:
    for message in trajectory.get("messages") or ():
        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "user" and isinstance(content, str) and "Please solve" in content:
            return content
    return ""


def _catalog_rows(receipt: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    validation: list[str] = []
    deliverables: list[str] = []
    ps = receipt.get("persistent_execution_state") or {}
    catalog = (ps.get("initialization") or {}).get("catalog") or {}
    for item in catalog.get("items") or ():
        kind = str(item.get("kind") or "")
        required = bool(item.get("required"))
        anchors = item.get("anchors") or ()
        path = str(item.get("path") or "")
        if kind == "validation" and required and anchors:
            validation.append(str(anchors[0]))
        elif kind == "deliverable" and required and path:
            deliverables.append(path)
    return tuple(dict.fromkeys(validation)), tuple(dict.fromkeys(deliverables))


def _reconstructed_workspace(trajectory: dict) -> tuple[WorkspaceEntry, ...]:
    """Conservative workspace reconstruction from exact tool reads only.

    The trajectory stores the executed command in each assistant tool call
    and the result in the following tool message.  Only single-target
    ``cat``/``head``/``sed -n`` reads whose output is a plain file body are
    used; everything else is ignored.  The result is a bounded, honestly
    labeled approximation of the workspace, never a claim of full fidelity.
    """

    import hashlib

    pending_commands: list[str] = []
    cwd = "/app"
    entries: dict[str, bytes] = {}
    presence: dict[str, int] = {}
    written: set[str] = set()
    for message in trajectory.get("messages") or ():
        role = str(message.get("role") or "")
        if role == "assistant":
            for call in message.get("tool_calls") or ():
                function = call.get("function") or {}
                if str(function.get("name") or "") != "bash":
                    continue
                arguments = function.get("arguments") or ""
                try:
                    payload = json.loads(arguments)
                except (TypeError, ValueError):
                    continue
                command = str(payload.get("command") or "")
                if command:
                    pending_commands.append(command)
            continue
        if role != "tool" or not pending_commands:
            continue
        command = pending_commands.pop(0)
        content = message.get("content") or ""
        if not isinstance(content, str):
            continue
        output_match = re.search(r"<output>(.*)</output>", content, re.DOTALL)
        if output_match is None:
            continue
        output = output_match.group(1)

        cd_match = CD_RE.match(command)
        if cd_match is not None:
            cwd = cd_match.group(1).rstrip("/")
        # Track writes so later presence observations of model-created files
        # (post-task-start state) are never mistaken for the initial workspace.
        for raw in (*WRITE_RE.findall(command), *CAT_WRITE_RE.findall(command)):
            normalized = _norm(raw, cwd)
            if normalized:
                written.add(normalized)

        # Exact file-body reads: cat with a single plausible target.
        match = CAT_READ_RE.search(command)
        if match is not None:
            target = _norm(match.group(1), cwd)
            if (
                target
                and target not in written
                and target not in entries
                and ("." in target.rsplit("/", 1)[-1] or target.startswith("/"))
            ):
                data = output.encode("utf-8", "replace")[:2048]
                entries[target] = data

        # Exact binary head bytes: od -A x -t x1z <path> first line.
        od_match = OD_RE.search(command)
        if od_match is not None:
            target = _norm(od_match.group(1), cwd)
            if target and target not in written and target not in entries:
                first = OD_LINE_RE.search(output)
                if first is not None and first.group(1) == "0":
                    hexes = re.sub(r"\s+", "", first.group(2))
                    data = bytes.fromhex(hexes[:64])
                    entries[target] = data

        # Presence-only evidence: ls -la rows prove existence, not content.
        ls_match = LS_DIR_RE.search(command)
        if ls_match is not None:
            directory = _norm(ls_match.group(1), cwd)
            for row in LS_ROW_RE.finditer(output):
                name = row.group(2).strip()
                if name in {".", ".."} or "/" in name:
                    continue
                normalized = _norm(f"{directory}/{name}", "/")
                if normalized not in written:
                    presence[normalized] = presence.get(normalized, 0) + 1

        # Presence-only evidence: find <dir> -type f lists exact paths.
        find_match = FIND_RE.search(command)
        if find_match is not None:
            directory = _norm(find_match.group(1), cwd)
            for line in output.splitlines():
                line = line.strip()
                if not line or not line.startswith(".") and not line.startswith("/"):
                    continue
                normalized = _norm(line, cwd if not line.startswith("/") else "/")
                if normalized and normalized not in written:
                    presence[normalized] = presence.get(normalized, 0) + 1

    for path in sorted(presence):
        if path in entries:
            continue
        entries[path] = b""
    return tuple(
        WorkspaceEntry(
            path=path,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest() if data else "",
            head=data,
            text=data.decode("utf-8", "replace")[:4096],
        )
        for path, data in sorted(entries.items())
    )


def _replay_task(task_dir: Path) -> dict:
    receipt_path = next(iter(sorted(task_dir.rglob("*/central_receipt.json"))), None)
    trajectory_path = next(
        iter(sorted(task_dir.rglob("*/miniswe_trajectory.json"))), None
    )
    if receipt_path is None or trajectory_path is None:
        return {"task": task_dir.name, "error": "missing receipt or trajectory"}
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))

    instruction = _instruction(trajectory)
    validation, deliverables = _catalog_rows(receipt)
    workspace = _reconstructed_workspace(trajectory)
    derivation = derive_decisive_facts(
        instruction=instruction,
        workspace=workspace,
        validation_commands=validation,
        deliverables=deliverables,
        source_revision=str(receipt.get("source_revision") or "replay"),
    )

    call_one_chars = 0
    for row in receipt.get("model_call_contexts") or ():
        if int(row.get("call") or 0) == 1:
            call_one_chars = int(row.get("persistent_execution_state_chars") or 0)
            break

    task_cwd = (receipt.get("task_working_directory") or {}).get("resolved") or "/app"
    decisive_paths = {fact.path for fact in derivation.facts if fact.path}
    reconstructed_paths = {entry.path for entry in workspace}
    incomplete = sorted(decisive_paths - reconstructed_paths)

    return {
        "task": task_dir.name,
        "instruction_chars": len(instruction),
        "catalog_validation": list(validation),
        "catalog_deliverables": list(deliverables),
        "reconstructed_entries": [
            entry.path for entry in workspace if entry.text or entry.head
        ],
        "presence_only_entries": [
            entry.path for entry in workspace if not entry.text and not entry.head
        ],
        "derivation_status": derivation.status.value,
        "reason_codes": list(derivation.reason_codes),
        "facts": [fact.as_dict() for fact in derivation.facts],
        "workspace_incomplete_for_path": incomplete,
        "archived_call_1_persistent_chars": call_one_chars,
        "frame_shift_to_call_1": bool(
            derivation.status is DecisiveStatus.DERIVED and call_one_chars == 0
        ),
        "task_cwd": task_cwd,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_dirs", nargs="+")
    args = parser.parse_args(argv)

    reports = [_replay_task(Path(path)) for path in args.task_dirs]
    for report in reports:
        if "error" in report:
            print(f"{report['task']}: ERROR {report['error']}")
            continue
        print(f"== {report['task']} ==")
        print(f"instruction_chars={report['instruction_chars']}")
        print(f"validation={report['catalog_validation'] or '-'}")
        print(f"deliverables={report['catalog_deliverables'] or '-'}")
        print(
            f"reconstructed_workspace={report['reconstructed_entries'] or '-'} "
            f"(reconstructed=true)"
        )
        print(
            f"presence_only_workspace={report['presence_only_entries'] or '-'} "
            f"(existence from ls, no content)"
        )
        print(f"derivation={report['derivation_status']} reasons={report['reason_codes'] or '-'}")
        for fact in report["facts"]:
            print(
                f"  fact kind={fact['kind']} path={fact['path'] or '-'} "
                f"gap={fact['gap_text']!r}"
            )
        print(
            f"archived_call_1_persistent_chars={report['archived_call_1_persistent_chars']}"
        )
        print(
            f"frame_shift_to_call_1={report['frame_shift_to_call_1']} "
            f"incomplete_for={report['workspace_incomplete_for_path'] or '-'}"
        )
        print()
    shifted = sum(bool(report.get("frame_shift_to_call_1")) for report in reports)
    print(f"CENTRAL_DECISIVE_REPLAY shifted={shifted}/{len(reports)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())