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
from gt_engine.delivery_budget import REFUSAL_EVENTS  # noqa: E402

# Which journal events prove a declared boundary was reached. Only boundaries
# derivable UNAMBIGUOUSLY appear here: the feature vocabulary (edit_result,
# submit, search_result, file_view, test_result, tool_result) and the journal's
# own (task_start, before_action, after_action) are different vocabularies, and
# inventing a join between them is the mistake this file exists to stop making.
# A boundary absent from this map is reported unknown, never assumed.
BOUNDARY_EVIDENCE = {
    "task_start": ("runtime_layout",),
    "edit_result": ("edit_transaction",),
}

# The submit boundary is decided by a POSITIVE DECLARATION, not by an absence.
# session_closed fires once on every path and carries how the run ended, so
# reading its terminal says "this run ended by exhausting its budget" rather
# than "the conditional branch that logs a submit was not taken". The obvious
# candidate, submit_decision, sits inside `if not self.can_enforce:` - deriving
# never-happened from an unlogged conditional is the absent-means-negative shape
# this file exists to avoid, and it would have been wrong for an enforcing run.
#
# A run killed before close writes no session_closed at all. That is genuinely
# unknown and must not read as NOT_REACHED, which is the distinction that makes
# this derivation safe where the other was not.
SUBMIT_TERMINALS = frozenset({"submitted", "submitted_verified", "submitted_unverified"})

SCHEMA = "gt.feature_accounting.v1"


def account(events: list[dict]) -> dict:
    """Resolve each DELIVERY once, then count deliveries - never events.

    The two identity-bearing event classes are disjoint and describe the same
    deliveries from opposite sides: decision_context_unit_prepared / admitted /
    refused carry supersession_key, while delivery_prepared / receipt /
    evidence_delivery / context_addition_delivery carry evidence_type. Both
    carry delivery_identity.

    Attributing per EVENT counts one delivery up to four times and, worse, can
    place a single delivery in a feature via one row and in the unattributed
    bucket via another - which is what made 306 context_delta rows look
    unclaimed while the same deliveries were already attributed to obligations
    through their supersession key. Resolve identity -> feature first, taking
    the declared supersession key over the lane kind, then count identities.
    """
    identity_feature: dict[str, str] = {}
    identity_refused: dict[str, bool] = {}
    identity_kinds: dict[str, str] = {}
    reached: collections.Counter[str] = collections.Counter()
    terminal: str | None = None

    for event in events:
        name = str(event.get("event") or "")
        for boundary, markers in BOUNDARY_EVIDENCE.items():
            if name in markers:
                reached[boundary] += 1

        if name == "session_closed":
            terminal = str(event.get("terminal") or "")
        supersession = str(event.get("supersession_key") or "")
        evidence_type = str(event.get("evidence_type") or "")
        if not supersession and not evidence_type:
            continue
        # A row without a delivery_identity is not a delivery. `receipt` rows
        # carry an evidence_type but no identity - they are receipts FOR
        # deliveries - and giving each one a synthetic unit inflated every
        # count by the number of receipts. The unit is the delivery or nothing.
        unit = str(event.get("delivery_identity") or "")
        if not unit:
            continue

        # The producer's declared identity beats the envelope. supersession_key
        # says what a delivery IS ("obligations:task"); evidence_type on those
        # same deliveries is the prompt-lane KIND (context_contract for the
        # first contract delivery, context_delta for every one after,
        # gt_session.py:582), which says only how its bytes are budgeted.
        feature = None
        if supersession:
            feature = feature_for_evidence(supersession) or feature_for_evidence(
                supersession.split(":", 1)[0]
            )
        if not feature and evidence_type:
            feature = feature_for_evidence(evidence_type)
        if feature:
            identity_feature[unit] = feature
        else:
            identity_kinds.setdefault(unit, supersession or evidence_type)
        if name in REFUSAL_EVENTS:
            identity_refused[unit] = True

    delivered: collections.Counter[str] = collections.Counter()
    refused: collections.Counter[str] = collections.Counter()
    for unit, feature in identity_feature.items():
        (refused if identity_refused.get(unit) else delivered)[feature] += 1
    unattributed = collections.Counter(
        kind for unit, kind in identity_kinds.items() if unit not in identity_feature
    )

    rows = []
    # All 19 identities, not the 12 owners. Seven of the 19 are capability
    # aliases whose evidence is produced by another feature (CAPABILITY_OWNERS),
    # and collapsing them silently reported a 12-row table for a 19-feature
    # census - a reader counting rows would conclude seven features had been
    # dropped. Show every identity; an alias states its owner and inherits its
    # state, so nothing is double counted and nothing is hidden.
    for feature in sorted(DIRECT_FEATURES):
        owner = CAPABILITY_OWNERS.get(feature)
        source = owner or feature
        count, declined = delivered[source], refused[source]
        boundaries = tuple(DIRECT_FEATURES[source].get("boundaries", ()))
        derivable = [b for b in boundaries if b in BOUNDARY_EVIDENCE]
        hits = {b: reached[b] for b in derivable if reached[b]}
        if "submit" in boundaries and terminal is not None:
            derivable.append("submit")
            if terminal in SUBMIT_TERMINALS:
                hits["submit"] = 1
        if count:
            state, evidence = "DELIVERED", f"{count} deliveries the model saw"
        elif declined:
            state, evidence = "REFUSED", f"{declined} refusals"
        elif hits:
            # The distinction that matters, derived rather than left to a reader
            # who happens to know which features are post-edit. "The boundary
            # happened 105 times and this feature said nothing" is a symptom;
            # "the boundary never happened" is not.
            state = "SILENT"
            evidence = "delivered nothing at " + ", ".join(
                f"{b} x{n}" for b, n in sorted(hits.items()))
        elif derivable:
            state = "NOT_REACHED"
            evidence = "its boundary never occurred: " + ", ".join(sorted(derivable))
            if "submit" in derivable and terminal:
                evidence += f" (run ended {terminal})"
        else:
            state = "BOUNDARY_UNKNOWN"
            evidence = "no journal evidence defines " + ", ".join(sorted(boundaries))
        if owner:
            evidence = f"via {owner}: {evidence}"
        rows.append({
            "feature": feature,
            "alias_of": owner or "",
            "state": state,
            "delivered": count,
            "refused": declined,
            "evidence": evidence,
            "kind": DIRECT_FEATURES[feature].get("kind", ""),
            "boundaries": list(boundaries),
            "boundaries_reached": hits,
            # The owner's two questions, separated. A feature declares a
            # trigger; the only things worth knowing are whether that trigger
            # fired and, if it did, whether the feature then did its job.
            # Collapsing them loses the distinction that matters: a feature that
            # never had the chance is not a feature that failed.
            "triggered": {
                "DELIVERED": "yes", "REFUSED": "yes", "SILENT": "yes",
                "NOT_REACHED": "no", "BOUNDARY_UNKNOWN": "unknown",
            }[state],
            "worked": {
                "DELIVERED": "yes", "REFUSED": "no", "SILENT": "no",
                "NOT_REACHED": "n/a", "BOUNDARY_UNKNOWN": "unknown",
            }[state],
            "trigger": DIRECT_FEATURES[source].get("trigger", ""),
        })
    return {
        "schema": SCHEMA,
        "journal_rows": len(events),
        "identities": len(rows),
        "direct_features": sum(1 for row in rows if not row["alias_of"]),
        "capability_aliases_shown": sum(1 for row in rows if row["alias_of"]),
        "deliveries_resolved": len(identity_feature),
        "delivered": sum(1 for row in rows if row["state"] == "DELIVERED"),
        "refused": sum(1 for row in rows if row["state"] == "REFUSED"),
        "silent": sum(1 for row in rows if row["state"] == "SILENT"),
        "not_reached": sum(1 for row in rows if row["state"] == "NOT_REACHED"),
        "boundary_unknown": sum(1 for row in rows if row["state"] == "BOUNDARY_UNKNOWN"),
        "boundaries_reached": dict(sorted(reached.items())),
        "terminal": terminal,
        "capability_aliases": dict(sorted(CAPABILITY_OWNERS.items())),
        "unattributed_evidence": dict(unattributed.most_common()),
        "unattributed_total": sum(unattributed.values()),
        "rows": rows,
    }


def render(report: dict) -> str:
    lines = [
        f"{'FEATURE':22s} {'TRIGGERED':10s} {'WORKED':7s} EVIDENCE FROM THE RUN",
        "-" * 96,
    ]
    for row in report["rows"]:
        lines.append(
            f"{row['feature']:22s} {row['triggered']:10s} {row['worked']:7s} {row['evidence']}"
        )
    lines.append("-" * 96)
    t = collections.Counter(row["triggered"] for row in report["rows"])
    w = collections.Counter(row["worked"] for row in report["rows"])
    lines.append(
        f"TRIGGERED  yes {t['yes']}  no {t['no']}  unknown {t['unknown']}"
        f"      WORKED  yes {w['yes']}  no {w['no']}  n/a {w['n/a']}  unknown {w['unknown']}"
    )
    lines.append(
        f"{report['identities']} identities = {report['direct_features']} features"
        f" + {report['capability_aliases_shown']} capability aliases"
        f"   ({report['journal_rows']} journal rows, terminal {report.get('terminal')})"
    )
    lines.append("")
    lines.append("WHAT EACH ONE IS WAITING FOR:")
    for row in report["rows"]:
        if row["trigger"]:
            lines.append(f"  {row['feature']:22s} {row['trigger']}")
    if report["unattributed_total"]:
        lines.append("")
        lines.append(
            f"UNATTRIBUTED evidence ({report['unattributed_total']} items) - "
            "a type no feature claims:"
        )
        for kind, count in report["unattributed_evidence"].items():
            lines.append(f"    {kind:38s} {count}")
    return chr(10).join(lines)


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
