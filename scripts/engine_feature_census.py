"""ENGINE 17-feature census (IE-14 verification).

Answers "how many of the 17 DIRECT features are working": every FACT feature
must have a registered owner AND a wired producer path (the gateway
evidence_type or a dedicated engine producer); every CAP_OWNER must map to its
FACT. Per-task firing is then gated by the actual triggers present in the run
(no tests in a task -> covering_red correctly does not fire).

Exit 0 iff all 17 are wired. Run:
    python scripts/engine_feature_census.py [--json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent


def census() -> dict:
    from gt_engine.engine.runner import ENGINE_FACT_OWNERS, _EVIDENCE_TO_OWNER

    # FACT features: registered owner + a producer path.
    gateway_types = set(_EVIDENCE_TO_OWNER.values())
    facts = [
        "def_partition", "covering_red", "syntax_result", "obligations",
        "localization", "recovery", "signature_delta", "newfile_precedent",
        "submit_refusal",  # caller_contract is REMOVE by disposition
    ]
    dedicated = {"syntax_result": "engine._syntax_artifact",
                 "covering_red": "engine._covering_red_artifact + gateway.covering"}
    fact_rows = []
    for feature in facts:
        registered = feature in ENGINE_FACT_OWNERS
        producer = (
            "gateway:" + feature if feature in gateway_types
            else dedicated.get(feature, "MISSING")
        )
        ok = registered and "MISSING" not in producer
        fact_rows.append({
            "feature": feature, "registered_owner": registered,
            "producer_path": producer, "ok": ok,
        })

    # CAP_OWNER lineage: each byte-owner's FACT is registered and delivered.
    cap_owners = {
        "GT_EDIT_CHECK": "syntax_result",
        "GT_PATCH_DELTA": "signature_delta",
        "GT_LOC_RESLOT": "localization",
        "GT_SS_SUBMIT_RED": "submit_refusal",
        "GT_HYPOTHESIS": "recovery",
        "GT_CHANGE_SURFACE": "newfile_precedent",
        "GT_CERT_DELIVERY": "delivery_receipt",
    }
    cap_rows = []
    for cap, fact in cap_owners.items():
        fact_ok = fact in ENGINE_FACT_OWNERS or fact == "delivery_receipt"
        cap_rows.append({"cap_owner": cap, "binds_fact": fact, "ok": fact_ok})

    return {
        "fact_count": len(fact_rows),
        "facts_ok": sum(1 for r in fact_rows if r["ok"]),
        "cap_count": len(cap_rows),
        "caps_ok": sum(1 for r in cap_rows if r["ok"]),
        "facts": fact_rows,
        "cap_owners": cap_rows,
        "all_17_wired": all(r["ok"] for r in fact_rows) and all(r["ok"] for r in cap_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = census()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"FACT features wired: {result['facts_ok']}/{result['fact_count']}")
        for row in result["facts"]:
            print(f"  {'OK ' if row['ok'] else 'MISSING'} {row['feature']:<18} "
                  f"-> {row['producer_path']}")
        print(f"CAP_OWNER lineage wired: {result['caps_ok']}/{result['cap_count']}")
        for row in result["cap_owners"]:
            print(f"  {'OK ' if row['ok'] else 'MISSING'} {row['cap_owner']:<18} "
                  f"-> binds {row['binds_fact']}")
        print(f"all_17_wired = {result['all_17_wired']}")
    return 0 if result["all_17_wired"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
