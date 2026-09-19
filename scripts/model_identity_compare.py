"""Cross-host greedy comparison of model-probe receipts (``--compare``).

Reached through ``python -m scripts.model_identity_probe --compare R1 R2 [...]
--json OUT``; the probe owns the CLI, the receipt writer and the annotations,
this module owns the comparison. It imports the probe's primitives, and the
probe imports this module only inside ``main`` so the two never import each
other at load time.

Input: probe receipts over the SAME refs file, one per host. Refused (rc 2):
fewer than two paths, a path given twice, receipts over different refs, two
receipts for the same (base_url, provider routing). Excluded and reported:
receipts made under an override (a different host class, e.g. the
DeepSeek-native control, which ``native_fingerprint`` judges instead) and
receipts that are not self-consistent (``self_consistent`` not true: a host
that ignored temperature 0, or whose output was empty so nothing was hashed).

RULE, per pair of remaining hosts. A task is comparable when both hosts
hashed it; a replay whose content, reasoning text and tool calls were all
empty is not hashed, because an empty output hashes to the same constant on
every host and would read as agreement. With N comparable tasks: agreement on
at least ceil(N/2) is PASS, fewer is FAIL, N = 0 is UNKNOWN. Any FAIL pair is
DISAGREES (rc 1); otherwise any UNKNOWN pair, or no pair at all, is
UNRESOLVED (rc 2); otherwise AGREES (rc 0).

The bar is a majority because fp8 kernels on different hardware and batch
shapes can diverge on a greedy tie, and because hosts parse reasoning
differently (where reasoning ends and content starts, whether reasoning is
returned at all): a reasoning-parser difference produces a FALSE disagreement
on the same weights. Read ``completion_tokens``/``finish_reason`` beside a
disagreeing hash before concluding the model differs. Agreement is evidence,
not proof: the receipt says ``does_not_prove: ["weights"]``.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

from scripts.model_identity_probe import (
    DOES_NOT_PROVE,
    FAIL,
    PASS,
    SCHEMA,
    UNKNOWN,
    ProbeError,
    _dict,
    _verdict,
)

COMPARE_VERDICTS = ("AGREES", "DISAGREES")
COMPARE_SCOPE = ["greedy_agreement_across_hosts"]


def _load_probe_receipt(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or doc.get("mode") != "probe":
        raise ValueError("compare_receipt_invalid")
    hashes = _dict(_dict(doc.get("checks")).get("greedy")).get("hashes")
    if not isinstance(hashes, list):
        raise ValueError("compare_receipt_invalid")
    return doc


def _host_key(receipt: dict[str, Any]) -> str:
    return json.dumps([receipt.get("base_url"), receipt.get("provider_routing")], sort_keys=True)


def _pair(i: int, a: dict[str, Any], j: int, b: dict[str, Any]) -> dict[str, Any]:
    tables = [
        {h["task"]: h["sha256"] for h in r["checks"]["greedy"]["hashes"] if h.get("sha256")}
        for r in (a, b)
    ]
    rows = [
        {"task": task, "agree": sha == tables[1][task], "hashes": [sha, tables[1][task]]}
        for task, sha in tables[0].items()
        if task in tables[1]
    ]
    agreeing = sum(row["agree"] for row in rows)
    required = math.ceil(len(rows) / 2)
    if not rows:
        severity = UNKNOWN
    else:
        severity = PASS if agreeing >= required else FAIL
    return {
        "hosts": [i, j],
        "severity": severity,
        "compared": len(rows),
        "agreeing": agreeing,
        "required": required,
        "tasks": rows,
    }


def _greedy_pairs(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    excluded, eligible = [], []
    for index, receipt in enumerate(receipts):
        if receipt.get("override"):
            excluded.append({"index": index, "reason": "override"})
        elif receipt.get("self_consistent") is not True:
            excluded.append({"index": index, "reason": "not_self_consistent"})
        else:
            eligible.append(index)
    pairs = [_pair(i, receipts[i], j, receipts[j]) for i, j in itertools.combinations(eligible, 2)]
    severities = {pair["severity"] for pair in pairs}
    if FAIL in severities:
        severity = FAIL
    elif not pairs or UNKNOWN in severities:
        severity = UNKNOWN
    else:
        severity = PASS
    return {
        "severity": severity,
        "rule": "per host pair: PASS when greedy hashes agree on at least ceil(N/2) of the "
        "N tasks both hashed (empty outputs are not hashed); N = 0 is UNKNOWN; "
        "any FAIL pair fails the comparison",
        "excluded": excluded,
        "pairs": pairs,
    }


def _hosts(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "base_url": r.get("base_url"),
            "model": r.get("model"),
            "provider_routing": r.get("provider_routing"),
            "override": r.get("override"),
            "self_consistent": r.get("self_consistent"),
            "status": r.get("status"),
        }
        for r in receipts
    ]


def run_compare(paths: list[Path]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "compare",
        "inputs": [str(path) for path in paths],
        "hosts": [],
        "provider_calls": 0,
        "scope": COMPARE_SCOPE,
        "does_not_prove": DOES_NOT_PROVE,
        "checks": {"greedy": {"severity": UNKNOWN, "excluded": [], "pairs": []}},
    }
    error_code = None
    try:
        if len(paths) < 2:
            raise ProbeError("compare_needs_two_receipts")
        if len({path.resolve() for path in paths}) != len(paths):
            raise ProbeError("compare_duplicate_receipt")
        try:
            receipts = [_load_probe_receipt(path) for path in paths]
        except (OSError, ValueError) as exc:
            raise ProbeError("compare_receipt_invalid") from exc
        receipt["hosts"] = _hosts(receipts)
        if len({r.get("refs_sha256") for r in receipts}) != 1:
            raise ProbeError("compare_refs_mismatch")
        receipt["refs_sha256"] = receipts[0].get("refs_sha256")
        if len({_host_key(r) for r in receipts}) != len(receipts):
            raise ProbeError("compare_duplicate_host")
        receipt["checks"]["greedy"] = _greedy_pairs(receipts)
        if not receipt["checks"]["greedy"]["pairs"]:
            raise ProbeError("compare_needs_two_eligible_receipts")
    except ProbeError as exc:
        error_code = str(exc)
    status, exit_code = _verdict(receipt["checks"], error_code, ("greedy",), COMPARE_VERDICTS)
    receipt.update(
        status=status,
        exit_code=exit_code,
        error_code=error_code,
        proven=COMPARE_SCOPE if exit_code == 0 else [],
    )
    return receipt
