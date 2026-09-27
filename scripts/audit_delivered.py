"""Check every claim a delivered [GT] block makes against the workspace.

"A feature fired" is not "the feature was right". Each fact line of a block
cites locations - a definition, a caller's call line, a callee, a test, a
slice line, a function that uses a name. This module re-reads the cited
source and classifies each citation:

  confirmed   the cited line says what the block claims
  wrong       it does not (wrong line, wrong name, stale text)
  unchecked   the claim cites no checkable location

Used by ``scripts/replay_attached.py --audit`` while the replayed workspace
is in the exact state the agent saw.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SITE = re.compile(r"([A-Za-z_$][\w.$<>]*)(?: \[[^\]]*\])? \(([^():]+):(\d+)(?:[,)][^)]*)?\)")
SLICE_ROW = re.compile(r"^\s+([^\s:]+):(\d+): (.*)$")
MAX_EXAMPLES = 6


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1].split("<")[0]


@dataclass
class Audit:
    counts: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    wrong_examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def note(self, claim: str, verdict: str, example: str = "") -> None:
        self.counts[claim][verdict] += 1
        if verdict == "wrong" and len(self.wrong_examples[claim]) < MAX_EXAMPLES:
            self.wrong_examples[claim].append(example[:220])

    def as_dict(self) -> dict:
        return {"counts": {k: dict(v) for k, v in sorted(self.counts.items())},
                "wrong_examples": dict(self.wrong_examples)}


class Source:
    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, list[str] | None] = {}

    def lines(self, path: str) -> list[str] | None:
        if path not in self._cache:
            try:
                self._cache[path] = (self.root / path).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self._cache[path] = None
        return self._cache[path]

    def line(self, path: str, number: int) -> str | None:
        lines = self.lines(path)
        if lines is None or not 0 < number <= len(lines):
            return None
        return lines[number - 1]

    def window(self, path: str, number: int, radius: int) -> str:
        lines = self.lines(path) or []
        return "\n".join(lines[max(0, number - 1 - radius): number + radius])


def _available(src: Source, audit: Audit, claim: str, path: str) -> bool:
    """A cited file the replay could not reconstruct cannot be judged."""
    if src.lines(path) is None:
        audit.note(claim, "unverifiable")
        return False
    return True


def _check_definition(src: Source, audit: Audit, claim: str, name: str, path: str, number: int) -> None:
    if not _available(src, audit, claim, path):
        return
    text = src.line(path, number)
    short = _short(name)
    # Decorators and multi-line signatures put the name a line or two below.
    ok = text is not None and any(short in (src.line(path, number + k) or "") for k in range(0, 4))
    audit.note(claim, "confirmed" if ok else "wrong", f"{name} @ {path}:{number} -> {text!r}")


def _check_call(src: Source, audit: Audit, claim: str, callee: str, caller: str, path: str, number: int) -> None:
    if not _available(src, audit, claim, path):
        return
    text = src.line(path, number)
    short = _short(callee)
    ok = text is not None and any(short in (src.line(path, number + k) or "") for k in (0, 1, -1))
    audit.note(claim, "confirmed" if ok else "wrong",
               f"{caller} calls {callee}? @ {path}:{number} -> {text!r}")


def audit_block(block: str, src: Source, audit: Audit) -> None:
    lines = block.splitlines()
    head = lines[0] if lines else ""
    kind = ("grep" if "graph context for your search" in head else "edit" if "after your edit" in head
            else "failure" if "about this failure" in head else "plan" if "task plan" in head else "other")
    subject = ""
    for raw in lines[1:]:
        s = raw.strip()
        if kind == "grep":
            m = re.match(r"^(\S+) \((\w+)\) ([^:\s]+):(\d+)$", s)
            if m:
                subject = m.group(1)
                _check_definition(src, audit, "F2 definition", subject, m.group(3), int(m.group(4)))
                continue
            if s.startswith("called by:") and subject:
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    _check_call(src, audit, "F4 caller call-line", subject, name, path, int(number))
            elif s.startswith("calls:") and subject:
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    _check_definition(src, audit, "F4 callee definition", name, path, int(number))
            elif " (not a definition) is used in:" in s:
                ident = s.split(" (not a definition)")[0].strip()
                for name, path, number in SITE.findall(s.split("is used in:", 1)[1]):
                    if not _available(src, audit, "F3/F15 name usage", path):
                        continue
                    ok = ident in src.window(path, int(number), 150)
                    audit.note("F3/F15 name usage", "confirmed" if ok else "wrong",
                               f"{ident} in {name} @ {path}:{number}")
            elif s.startswith(("overridden by:", "overrides:", "extended/implemented by:")):
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    _check_definition(src, audit, "F7 dispatch target", name, path, int(number))
            elif s.startswith("injected into:"):
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    _check_definition(src, audit, "F8 injection site", name, path, int(number))
        elif kind == "edit":
            m = re.match(r"^(\S+) is called by: (.*)$", s)
            if m:
                for name, path, number in SITE.findall(m.group(2)):
                    _check_call(src, audit, "F4/F13 caller of changed fn", m.group(1), name, path, int(number))
            elif s.startswith("changed:"):
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    audit.note("F13 changed fn", "unchecked")  # pre-edit coordinates; the file moved
            elif s.startswith("tests reaching") or s.startswith("test "):
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    _check_definition(src, audit, "F20 test/exercised location", name, path, int(number))
        elif kind == "failure":
            row = SLICE_ROW.match(raw)
            if row:
                path, number, text = row.group(1), int(row.group(2)), row.group(3).strip()
                actual = (src.line(path, number) or "").strip()
                audit.note("F14-17 slice line", "confirmed" if actual == text else "wrong",
                           f"{path}:{number} block={text!r} file={actual!r}")
            elif s.startswith(("failing test:", "failure surfaced in:")):
                for name, path, number in SITE.findall(s.split(":", 1)[1]):
                    lines_ = src.lines(path) or []
                    ok = 0 < int(number) <= len(lines_)
                    audit.note("F20 failure location", "confirmed" if ok else "wrong", f"{name} @ {path}:{number}")
        elif kind == "plan":
            if "->" in s:
                for name, path, number in SITE.findall(s.split("->", 1)[1]):
                    _check_definition(src, audit, "plan anchor", name, path, int(number))


def audit_output(text: str, root: Path, audit: Audit) -> None:
    src = Source(root)
    for chunk in text.split("[GT]")[1:]:
        audit_block("[GT]" + chunk.split("\n\n[GT]")[0], src, audit)


__all__ = ["Audit", "audit_output"]
