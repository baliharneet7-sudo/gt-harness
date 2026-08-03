"""ENGINE meta-audit — Gate 2: prove the readiness audit can detect lies.

The readiness audit (Gate 1) is only trustworthy if it FAILS when a defect is
present. This meta-audit plants REAL defects into the pipeline (via targeted
monkeypatches of the producer/gate path) and asserts the audit catches each:

  M1. empty-evidence fact injected -> payload_true must go red
  M2. internal ID injected into a fact payload -> no_internal_ids must go red
  M3. predictive fact injected into a non-tool message -> non_predictive red
  M4. detached fact (appended after the run, not bound to an action) ->
      correct_time red

Plus:
  M5. independent re-derivation: a second parser recomputes delivery counts
      from raw observations; must exactly match the audit.
  M6. ground-truth: every fact's target/file resolves to a real path in the
      scenario workspace.

Exit 0 iff every mutation is caught AND re-derivation matches AND ground-truth
holds. This is the gate that makes "READY" mean something.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from engine_readiness_audit import (  # noqa: E402
    FACT_RE,
    INTERNAL_ID_RE,
    _model_messages,
    audit_feature,
)
from engine_readiness_scenarios import SCENARIOS  # noqa: E402
from engine_smoke_e2e import TASK  # noqa: E402

# The audit's detection predicate for each cell (the thing a mutation must trip).
EMPTY_RE = re.compile(r'"evidence": ""')


def main() -> int:
    import gt_engine.engine.runner as runner

    checks: list[tuple[str, bool]] = []

    # --- M1: empty-evidence fact must make payload_true red -------------------
    # Plant a defect at the SOURCE: an empty-evidence covering_red producer.
    # The audit's payload_true (parsed from observed bytes) must then be False.
    orig_postflight = runner._postflight_facts

    def empty_postflight(*a, **k):
        facts = orig_postflight(*a, **k)
        out = []
        for f in facts:
            if f.owner == "covering_red":
                from gt_engine.engine.contracts import EvidenceArtifact

                f = EvidenceArtifact(
                    artifact_id=f.artifact_id, owner=f.owner, semantics=f.semantics,
                    content={"evidence": "", "target": "src/mod.py"},
                    anchors=f.anchors, producer=f.producer,
                    producer_version=f.producer_version,
                    freshness_revision=f.freshness_revision, coverage=f.coverage,
                    model_visible=True,
                )
            out.append(f)
        return tuple(out)

    runner._postflight_facts = empty_postflight
    try:
        res = audit_feature("covering_red", SCENARIOS["covering_red"][0],
                            SCENARIOS["covering_red"][1])
    finally:
        runner._postflight_facts = orig_postflight
    payload_true = res["owners"]["covering_red"]["payload_true"]
    m1_caught = not payload_true  # empty payload must FAIL payload_true
    checks.append(("M1 empty-evidence -> payload_true red", m1_caught))

    # --- M2: internal ID in payload must make no_internal_ids red -------------
    orig_facts = runner._obligations_fact

    def leaky_obligations(**kw):
        fact = orig_facts(**kw)
        if fact is None:
            return None
        from gt_engine.engine.contracts import EvidenceArtifact

        return EvidenceArtifact(
            artifact_id=fact.artifact_id, owner=fact.owner, semantics=fact.semantics,
            content={**dict(fact.content), "matched": ["obl-deadbeef00"]},
            anchors=fact.anchors, witnesses=fact.witnesses, producer=fact.producer,
            producer_version=fact.producer_version,
            freshness_revision=fact.freshness_revision, coverage=fact.coverage,
            model_visible=True,
        )

    runner._obligations_fact = leaky_obligations
    try:
        res = audit_feature("obligations", SCENARIOS["obligations"][0],
                            SCENARIOS["obligations"][1])
    finally:
        runner._obligations_fact = orig_facts
    no_ids = res["owners"]["obligations"]["no_internal_ids"]
    m2_caught = not no_ids  # internal ID must FAIL no_internal_ids
    checks.append(("M2 internal-ID -> no_internal_ids red", m2_caught))

    # --- M3: predictive fact must make non_predictive red ---------------------
    # A fact rendered into a system/user message (before any action). The audit
    # parses the full stream and flags non-tool facts as predictive.
    built = SCENARIOS["localization"][0]()
    agent = built[0]
    orig_prepare = agent.model._prepare_messages_for_api
    leaked = {"detected": False}

    def leak_prepare(messages):
        for it in messages:
            if it.get("role") in ("system", "user") and not leaked["detected"]:
                c = str(it.get("content") or "")
                it["content"] = c + "\n<fact owner=\"localization\">{\"target\": \"a.py\"}</fact>"
                leaked["detected"] = True
        return orig_prepare(messages)

    agent.model._prepare_messages_for_api = leak_prepare
    res = audit_feature("localization", SCENARIOS["localization"][0],
                        SCENARIOS["localization"][1], built=built)
    non_pred = res["owners"]["localization"]["non_predictive"]
    m3_caught = (not non_pred) and leaked["detected"]
    checks.append(("M3 predictive fact -> non_predictive red", m3_caught))

    # --- M4: detached fact -> correct_time red --------------------------------
    # A fact appended to a tool message that does NOT follow an assistant action.
    built = SCENARIOS["recovery"][0]()
    agent = built[0]
    orig_prepare = agent.model._prepare_messages_for_api
    detached = {"detected": False}

    def detach_prepare(messages):
        if not detached["detected"]:
            # inject a stray tool message (not preceded by an assistant action)
            # directly into the input the audit's spy records
            messages.append({
                "role": "tool",
                "content": "<result action=\"stray\" decision=\"augment\">"
                           "<fact owner=\"recovery\">{\"evidence\": \"stray\", "
                           "\"target\": \"src/mod.py\"}</fact></result>",
            })
            detached["detected"] = True
        return orig_prepare(messages)

    agent.model._prepare_messages_for_api = detach_prepare
    res = audit_feature("recovery", SCENARIOS["recovery"][0],
                        SCENARIOS["recovery"][1], built=built)
    correct_time = res["owners"]["recovery"]["correct_time"]
    m4_caught = (not correct_time) and detached["detected"]
    checks.append(("M4 detached fact -> correct_time red", m4_caught))

    # --- M5: independent re-derivation exact match ----------------------------
    match_ok = True
    for feature, (builder, owners) in SCENARIOS.items():
        agent, adapter, graph_db, root = builder()
        stream = _model_messages(agent)
        agent.run(TASK)
        tool_obs = [c for r, c in stream if r == "tool"]
        counts: dict[str, int] = {}
        for o in tool_obs:
            for fm in FACT_RE.finditer(o):
                owner = fm.group(1)
                counts[owner] = counts.get(owner, 0) + 1
        res = audit_feature(feature, SCENARIOS[feature][0],
                            SCENARIOS[feature][1])
        for owner in owners:
            audited = res["owners"].get(owner, {}).get("n_delivered", 0)
            if owner == "submit_refusal":
                indep = 1 if any('decision="suppress"' in o for o in tool_obs) else 0
            else:
                indep = counts.get(owner, 0)
            if audited != indep:
                match_ok = False
                print(f"  M5 MISMATCH {feature}/{owner}: audit={audited} indep={indep}")
    checks.append(("M5 independent re-derivation exact match", match_ok))

    # --- M6: ground-truth anchors resolve to real paths -----------------------
    gt_ok = True
    for feature, (builder, owners) in SCENARIOS.items():
        agent, adapter, graph_db, root = builder()
        tool_obs = [c for r, c in _model_messages(agent) if r == "tool"]
        agent.run(TASK)
        for o in tool_obs:
            for fm in FACT_RE.finditer(o):
                owner, body = fm.group(1), fm.group(2)
                for m in re.finditer(r'"(?:target|file)":\s*"([^"]+)"', body):
                    anchor = m.group(1)
                    if anchor.startswith(".gt") or "gt-state" in anchor:
                        continue
                    if not (Path(root) / anchor).exists():
                        gt_ok = False
                        print(f"  M6 MISSING {feature}/{owner}: {anchor} not under {root}")
    checks.append(("M6 ground-truth anchors resolve", gt_ok))

    all_ok = all(ok for _, ok in checks)
    print("META-AUDIT (Gate 2)")
    for name, ok in checks:
        print(f"  {'OK ' if ok else 'FAIL'} {name}")
    print("META READY" if all_ok else "META NOT READY")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
