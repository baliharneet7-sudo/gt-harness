"""Prove a staged change did not break what depends on it.

Three defects in three consecutive commits shared one shape: the change's effect
was wider than the function edited.

  args.state_dir inside build_agent   wider than the LINE  - no args in scope
  successful_receipt fixture          wider than the TEST  - shared by 8 tests
  os.environ.setdefault in build_agent wider than the RUN  - retrieval.py reads
                                       the same variable, process-global

Each was caught, twice by executing the line and once by CI, and the rate rose
while moving faster toward a dispatch. Rules addressed to oneself fail exactly
when attention is elsewhere; this runs whether or not anyone remembers it.

Three checks, matched to the three shapes:

1. RUFF over staged Python. F821 undefined-name is already selected in
   pyproject; it catches the NameError class outright and costs a second.

2. THE DERIVED SUITES, IN ONE PYTEST PROCESS. Collect the tests that reference
   any symbol whose definition the diff touches, and run them TOGETHER. Running
   them per-file is what HIDES a process-global mutation: the env leak passed in
   isolation and failed only in aggregate. Isolation is the failure mode here,
   not the safety net.

3. A PROMPT on process-global mutation. Warn, never block - an operator override
   written through os.environ is legitimate, and a hard block on a legitimate
   pattern is how hooks get bypassed.

What BLOCKS and what REPORTS, and why the line is where it is
------------------------------------------------------------
Ruff blocks: it is deterministic, environment-independent, and F821 is exactly
the NameError class.

The derived suites REPORT. They cannot block, because this repository's local
interpreter resolves `groundtruth` to a working checkout at a different revision
than the pinned wheel, so a large set of suites fails here for reasons no commit
caused. A gate that refuses every commit is a gate that gets bypassed within the
hour, and then catches nothing at all - which is worse than one that reports.

The authority for green remains the CI gate, which has the pinned wheel and a
clean interpreter and already runs everything. What this adds is the derived set
IN ONE PROCESS, printed before the push rather than six minutes into CI - and
that single-process property is the part that matters, because the env leak
passed in isolation and failed only in aggregate.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GLOBAL_MUTATION = re.compile(
    r"^\+\s*(?:os\.environ\[[^\]]+\]\s*=|os\.environ\.setdefault\(|os\.environ\.update\(|"
    r"sys\.path\.insert\(|logging\.basicConfig\(|warnings\.filterwarnings\()"
)
DEFINITION = re.compile(r"^\+?\s*(?:def|class)\s+([A-Za-z_]\w*)")


def _staged() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         capture_output=True, text=True, cwd=ROOT).stdout
    return [line for line in out.splitlines() if line.endswith(".py")]


def main() -> int:
    staged = _staged()
    if not staged:
        return 0
    diff = subprocess.run(["git", "diff", "--cached", "-U0", "--"] + staged,
                          capture_output=True, text=True, cwd=ROOT).stdout

    # (1) undefined names and the rest of the configured ruff selection
    ruff = subprocess.run([sys.executable, "-m", "ruff", "check", *staged],
                          capture_output=True, text=True, cwd=ROOT)
    if ruff.returncode != 0:
        print(ruff.stdout or ruff.stderr, file=sys.stderr)
        print("blast-radius gate: ruff refused the staged files", file=sys.stderr)
        return 1

    # (3) prompt, never block
    for line in diff.splitlines():
        if GLOBAL_MUTATION.match(line):
            print(f"blast-radius NOTE: {line.strip()}", file=sys.stderr)
            print("  this mutates process-global state. Is the blast radius the "
                  "process or the function? retrieval.py reads os.environ too.",
                  file=sys.stderr)

    # (2) every test file referencing a touched definition, in ONE process
    touched = {m.group(1) for line in diff.splitlines() if (m := DEFINITION.match(line))}
    touched |= {Path(p).stem for p in staged if not p.startswith("tests/")}
    suites = {p for p in staged if p.startswith("tests/")}
    if touched:
        pattern = r"\b(" + "|".join(sorted(re.escape(t) for t in touched if len(t) > 3)) + r")\b"
        for test in (ROOT / "tests").glob("test_*.py"):
            try:
                if re.search(pattern, test.read_text(encoding="utf-8", errors="ignore")):
                    suites.add(test.relative_to(ROOT).as_posix())
            except OSError:
                continue
    if not suites:
        print("blast-radius gate: no dependent suite derived; nothing to prove", file=sys.stderr)
        return 0
    ordered = sorted(suites)
    print(f"blast-radius gate: {len(ordered)} suite(s), one process:", file=sys.stderr)
    for s in ordered:
        print(f"    {s}", file=sys.stderr)
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header",
                           "-p", "no:cacheprovider", *ordered],
                          capture_output=True, text=True, cwd=ROOT)
    tail = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAILED") or " passed" in ln
            or " failed" in ln or " error" in ln]
    for line in tail[-12:]:
        print(f"    {line}", file=sys.stderr)
    if proc.returncode != 0:
        print("blast-radius gate: the derived set is NOT green. This does not block - "
              "the local interpreter resolves `groundtruth` to a different revision "
              "than the pinned wheel - but read the failures above before pushing, "
              "and treat any that name a symbol you just changed as yours.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
