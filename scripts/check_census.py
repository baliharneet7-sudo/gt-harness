"""Which of GT's checks have ever produced their non-default output?

A check that has never produced its non-default output has not been shown to
work. That covers four things at once, and today produced one of each:

    an ASSERTION that has never failed may be unable to fail
    a QUERY that has never found may be unable to find
    an EMITTER that has never fired may be unable to fire
    a GATE that has never blocked may be unable to block

`red_invalidated_by_edit` is the emitter case: live code at
miniswe_integration.py, zero rows across 143 edit transactions in two runs, so
"correctly silent because no predicate was RED" and "cannot fire" are
indistinguishable from the evidence. The syntax `diagnostics` field is the query
case: zero non-empty values across 182 entries, so "the edits were clean" and
"the field is never populated" are indistinguishable. Both were published as the
favourable reading before anyone asked for a control.

This turns that from a judgement into a table.

SCOPE, stated because a census that overstates its own coverage is the defect it
exists to catch. The observed set is exact - it is every distinct `event` value
in every journal given. The declared set is a REGEX SCAN of gt_engine for event
name literals, and it is incomplete in both directions: events are emitted
through `store.append`, through a local `record` helper, and through conditional
expressions that choose a name, and no pattern catches all three. So a name in
DECLARED-NEVER-OBSERVED is a candidate to investigate, not a proven dead emitter,
and a name absent from DECLARED is not proven absent from the code.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Three shapes, because one pattern does not cover the emitters. Controlled
# against a real journal: a scan that finds fewer names than a single run
# observes is a broken scan, and the first version of this was exactly that.
EMITTER_PATTERNS = (
    re.compile(r'store\.append\(\s*\n?\s*"([a-z_]+)"', re.M),
    re.compile(r'\brecord\(\s*\n?\s*"([a-z_]+)"', re.M),
)
# A third pattern for the conditional-expression shape - a bare string literal
# on its own line - was tried and removed. It matched every such literal in the
# package, inflating the declared set to 106 and filling the never-observed list
# with names like `already_active` and `failed_search` that are refusal reasons,
# not events. A scan that reports non-emitters as dead emitters is worse than one
# that admits it misses some: the first produces work, the second a caveat. The
# two names it was added for are reported as scan gaps instead.


def declared() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "gt_engine").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in EMITTER_PATTERNS:
            names |= set(pattern.findall(text))
    return names


def observed(journals: list[Path]) -> dict[str, collections.Counter]:
    per_run: dict[str, collections.Counter] = {}
    for journal in journals:
        counts: collections.Counter = collections.Counter()
        for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = row.get("event")
            if isinstance(name, str):
                counts[name] += 1
        # The task id is identical across runs of the same task, so keying on it
        # silently collapsed two journals into one - and the collapsed union then
        # listed graph_rebuild_embedding as NEVER OBSERVED, an event this ticket
        # read sixteen of that same morning. The census caught its own instrument
        # the way it is built to catch everyone else's.
        label = next((part for part in reversed(journal.parts) if part.isdigit()
                      or part.startswith("art")), journal.parent.name)
        per_run[label] = counts
    return per_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+",
                        help="run directories or events.jsonl files")
    args = parser.parse_args()

    journals: list[Path] = []
    for raw in args.artifacts:
        path = Path(raw)
        journals.extend(sorted(path.rglob("gt-state/*/events.jsonl")) if path.is_dir()
                        else [path])
    if not journals:
        print("no journals found", file=sys.stderr)
        return 2

    per_run = observed(journals)
    every = set().union(*(set(c) for c in per_run.values()))
    names = declared()

    print(f"journals: {len(journals)}   distinct events observed: {len(every)}   "
          f"names found by the source scan: {len(names)}")
    if missing := sorted(every - names):
        # The scan's own positive control: an event the runs produced that the
        # scan did not find proves the scan is incomplete, and says by how much.
        print(f"\nSCAN INCOMPLETE - observed but not found in source ({len(missing)}):")
        for name in missing:
            print(f"    {name}")

    print("\nOBSERVED, per run:")
    runs = sorted(per_run)
    width = max((len(n) for n in every), default=10)
    print(f"    {'event':{width}}  " + "  ".join(f"{r[:18]:>18}" for r in runs))
    for name in sorted(every):
        cells = "  ".join(f"{per_run[r].get(name, 0):>18}" for r in runs)
        print(f"    {name:{width}}  {cells}")

    dead = sorted(names - every)
    print(f"\nDECLARED IN SOURCE, NEVER OBSERVED IN ANY JOURNAL GIVEN ({len(dead)}):")
    print("    candidates to investigate - an emitter that has never fired has not")
    print("    been shown to be able to fire. Not proof of dead code: this run set")
    print("    may simply never have reached them.")
    for name in dead:
        print(f"    {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
