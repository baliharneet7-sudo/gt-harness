"""Small, dependency-free terminal diff unwrapper used by Live Lite metrics."""
from __future__ import annotations

import re

_PREFIX = re.compile(r"^(?:diff |index |--- |\+\+\+ |@@ |\+|-| |\\|new |old |deleted |rename|similarity|Binary|copy )")
_MARKERS = (
    "\nSaved trajectory", "\nAgent wants to finish", "\n=== Pro Trial",
    "\nEVAL_DEFERRED:", "\nPRO_EVAL_", "\nGT_RUN_PROOF", "\n[MEMLOG ",
    "\n[GT_DEEP]", "\n[RESMON]", "\nbash: line", "\nSubmit message:",
)


def _valid(line: str) -> bool:
    return line == "" or _PREFIX.match(line) is not None


def unwrap_patch(raw: str) -> tuple[str, dict[str, int]]:
    lines = raw.replace("\r", "").split("\n")
    out: list[str] = []
    joined = 0
    for line in lines:
        if not out:
            out.append(line)
            continue
        prev = out[-1]
        if ((line.startswith("b/") and prev.startswith(("diff --git a/", "+++ ")))
                or (line.startswith("a/") and prev.startswith("--- "))):
            out[-1] = prev + ("" if prev.endswith(" ") else " ") + line
            joined += 1
        elif not _valid(line):
            out[-1] = prev + line
            joined += 1
        else:
            out.append(line)
    return "\n".join(out), {
        "original_lines": len(lines), "joined_lines": joined, "output_lines": len(out)
    }


def extract_patch_from_log(log_text: str) -> str | None:
    pos = log_text.rfind("COMPLETE_TASK_AND_SUBMIT")
    if pos < 0:
        return None
    region = log_text[pos:]
    for marker in ("\nExit:\n", "\nExit:\r\n"):
        cut = region.find(marker)
        if cut >= 0:
            region = region[cut + len(marker):]
            break
    start = region.find("diff --git")
    if start < 0:
        return None
    raw = region[start:]
    for marker in _MARKERS:
        cut = raw.find(marker)
        if cut > 0:
            raw = raw[:cut]
    lines = raw.split("\n")
    while lines and (not lines[-1].strip() or not _valid(lines[-1])):
        lines.pop()
    patch = "\n".join(lines)
    return patch if len(patch) >= 10 else None
