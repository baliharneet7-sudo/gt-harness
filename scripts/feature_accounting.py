"""Say which GT features worked in a run, from the run's own evidence.

Why this is not the feature matrix
----------------------------------
``gt_engine.feature_matrix`` decides each feature by running a TEST:
``FEATURE_EVIDENCE`` and ``FEATURE_NEGATIVE_EVIDENCE`` map a feature to pytest
node ids. That answers "does the test pass", which is a statement about the
suite, not about the benchmark run. It is the wrong instrument for the question
the owner asks of every run - which features worked and which did not - and it
answers it identically whether the run solved the task or died in construction.

This derives the answer from the journal the run actually wrote. Every delivery
carries an ``evidence_type``, and ``attribution.feature_for_evidence`` already
maps those onto the census identities, so nothing new has to be invented or
maintained alongside the producer.

Three states, and the third is not a failure
--------------------------------------------
DELIVERED      the feature put evidence in front of the model, with a count.
REFUSED        it was reached and declined, which is a working feature saying no.
NOT TRIGGERED  its precondition never occurred in this task.

Keeping NOT TRIGGERED distinct from REFUSED is the whole point. A task with no
new files cannot exercise ``newfile_precedent``, and reporting that as a failure
would train a reader to ignore the column. But a POST-EDIT feature silent across
a run with a hundred edits is not untriggered by nature - it is a symptom, and
run 34064560259 is the case: the graph was frozen at task start, so
``syntax_result``, ``signature_delta`` and ``covering_red`` had nothing to fire
against and the accounting showed 4 of 12.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gt_engine.attribution import (  # noqa: E402
    CAPABILITY_OWNERS,
    DIRECT_FEATURES,
    feature_for_evidence,
)

SCHEMA = "gt.feature_accounting.v1"


def account(events: list[dict]) -> dict:
    delivered: collections.Counter[str] = collections.Counter()
    refused: collections.Counter[str] = collections.Counter()
    for event in events:
        feature = feature_for_evidence(event.get("evidence_type"))
        if not feature:
            continue
        name = str(event.get("event") or "")
        if "refus" in name or "abstain" in name:
            refused[feature] += 1
        else:
            delivered[feature] += 1

    rows = []
    for feature in sorted(DIRECT_FEATURES):
        if feature in CAPABILITY_OWNERS:
            continue  # an alias; its owner reports for it
        count, declined = delivered[feature], refused[feature]
        if count:
            state, evidence = "DELIVERED", f"{count} deliveries the model saw"
        elif declined:
            state, evidence = "REFUSED", f"{declined} refusals"
        else:
            state, evidence = "NOT_TRIGGERED", "no evidence of this type in the run"
        rows.append({
            "feature": feature,
            "state": state,
            "delivered": count,
            "refused": declined,
            "evidence": evidence,
            "kind": DIRECT_FEATURES[feature].get("kind", ""),
            "boundaries": list(DIRECT_FEATURES[feature].get("boundaries", ())),
        })
    return {
        "schema": SCHEMA,
        "journal_rows": len(events),
        "direct_features": len(rows),
        "delivered": sum(1 for row in rows if row["state"] == "DELIVERED"),
        "refused": sum(1 for row in rows if row["state"] == "REFUSED"),
        "not_triggered": sum(1 for row in rows if row["state"] == "NOT_TRIGGERED"),
        "capability_aliases": dict(sorted(CAPABILITY_OWNERS.items())),
        "rows": rows,
    }


def render(report: dict) -> str:
    lines = [f"{'FEATURE':22s} {'STATE':14s} EVIDENCE FROM THE RUN", "-" * 74]
    for row in report["rows"]:
        lines.append(f"{row['feature']:22s} {row['state']:14s} {row['evidence']}")
    lines.append("-" * 74)
    lines.append(
        f"{report['delivered']} delivered, {report['refused']} refused, "
        f"{report['not_triggered']} never triggered, of "
        f"{report['direct_features']} direct features "
        f"({report['journal_rows']} journal rows)"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", help="events.jsonl from the run, or a directory holding it")
    parser.add_argument("--json-out", help="write the gt.feature_accounting.v1 report here")
    args = parser.parse_args()

    path = Path(args.journal)
    if path.is_dir():
        found = sorted(path.rglob("events.jsonl"))
        if not found:
            print(f"no events.jsonl under {path}", file=sys.stderr)
            return 2
        path = found[0]
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = account(events)
    print(render(report))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
