# Task-decisive context: enterprise-pattern grounding (2026-08-16)

## 1. What we built and why

GroundTruth's determinism guarantee covers tasks whose decisive fact is
derivable from the three legal benchmark sources (task instruction,
repository source in the workspace, observed execution results). The new
`gt_engine.decisive_derivation.py` module computes that decisive fact
host-side, deterministically, at task start: a small fixed set of gap
detectors (required validation command, required deliverable absence,
binary-format recognition, credential-class presence) over a bounded
workspace scan (512 files, 2048 head bytes, 4096 text chars, depth 12). The
resulting 1-6 bounded facts are rendered at the **first eligible provider
call** inside the existing persistent-state frame, with the neutral header
`Task-decisive context:`, authority `deterministic_derived`, materiality
`task_decisive_evidence`, and origin
`TASK_DELIVERABLE`/`PREEXISTING_REPOSITORY`.

Constraints honored: exactly one bootstrap call + normal executor calls (no
extra LLM call, no temperature-0 solver), unchanged delivery budgets
(priority-only change), no grader-only artifacts ever read (integrity
audit: all inputs are instruction text + workspace bytes), fail-open
abstention on any uncertainty (`ABSTAINED` with typed reason codes).

An instruction-mentioned-path detector (`anchor_presence`) was built in the
first iteration, then **removed** after audit: task-start localization by
raw instruction matching is listed as never provider-visible in
`.research/gt-semantic-context/FINAL_GT_IDENTITY.md`, while the certified
focus surface ("Certified related repository file: …") is the approved
task-start localization form. All defects found in the fix round and their
fixes are recorded in
`details_done/GT_TASK_DECISIVE_CONTEXT_FIX_AUDIT_20260816.md`.

## 2. The enterprise pattern this implements

Mainstream coding harnesses converged on the same observation: an agent's
outcome is set less by its sampling temperature than by whether the
decision-relevant facts are already in its context. The concrete patterns:

1. **Context engineering as the product** (Anthropic): the documented
   result of Anthropic's agent research is that the dominant lever is
   context quality — give the model the right facts up front, in the right
   structure, and the model stops hunting. Our mechanism is the host-side
   deterministic version of that: instead of spending model calls to
   discover "what is the required check / what output is expected", the
   host computes and states it.
2. **Deterministic evidence gathering** (Sourcegraph MCP, GitHub's
   "knowledge-as-product" line): the host owns retrieval and presents
   certified evidence in the prompt; the model does not negotiate for
   facts. GT's persistent execution state, hybrid retrieval, and now
   decisive derivation are the same architecture: a host-owned context
   compiler that renders bounded, grounded, provenance-labeled evidence at
   provider boundaries.
3. **Variance cuts by prompt determinism** (Google agent-CoT work,
   published and internal): chain-of-thought variance across rollouts is
   cut when the decision-critical facts are stated explicitly rather than
   re-derived by the model. Our hypothesis (user-authored): with
   overwhelming, deterministic, task-decisive context, any sampled
   reasoning path reaches the correct result — P(correct | context) -> 1,
   not a delta between arms.
4. **Consistency across rollouts** (tau-bench line): benchmark-observed
   gains from deterministic instruction/evidence structure come from
   reducing task-relevant ambiguity, not from changing the model.
5. **arXiv:2408.04667 / arXiv:2502.11027** (planned cites on agent
   hallucination under incomplete context and on impossible-instruction
   boundaries): the family we deliberately did **not** build. The
   "verifier-guided agent" family (reading hidden tests, reward signals,
   or grader artifacts) is rejected outright as benchmark contamination —
   AGENTS.md's integrity boundary forbids it in every mode. Decisive
   derivation instead stays inside the three legal sources and abstains
   where the decisive convention lives only in the grader.

## 3. What we proved (locally)

- 23 unit tests on the derivation engine: determinism (identical inputs ->
  identical facts; claim_id revision-stable), detector behavior, boundedness,
  no-grader-contact, engine integration (header, authority, one-shot
  dispatch, 512-token ceiling, degrade-to-None).
- Probe run (`D:\tmp\opencode\decisive_probe.py`): full pipeline renders
  `Task-decisive context:` with both facts at call 1.
- `scripts/central_decision_completeness.py` (gate `DECISION_COMPLETENESS_GATE`):
  PASS when every derived fact's gap text appears in the delivered frame and
  re-derivation matches; FAIL is honest without a frame. Post-fix run:
  derives `required_check`, re-derivation parity PASS.
- `scripts/central_decisive_replay.py` on three archived smoke tasks:
  extract-elf -> derived (deliverable `out.json` absent; archived call-1
  persistent chars 0 -> `frame_shift_to_call_1=True`); sanitize-git-repo ->
  derived (required check `pytest -q`); schemelike -> derived (both required
  checks). Workspace reconstructed conservatively from trajectory tool reads
  (cat/od/ls/find), writes excluded so post-creation state never masquerades
  as task start.
- Integrity audit after the fix round: `source_boundary_proven: true`,
  `violations: []`. Full test suite: **7 failed, 1646 passed, 5 skipped** —
  exactly the 7 pre-existing failures (6 stale-Windows-`gt-index.exe`
  indexer: c/cpp SPECULATIVE 0.2, elm/ocaml absent; 1 unrelated finalstand
  drift), zero regressions. The earlier "10 failures reproduce on clean
  tree" claim was flawed (untracked module survived the stash); the
  corrected per-test attribution is in the fix-audit document. Census/
  readiness/pre-smoke cannot pass locally by design (AGENTS.md: only the
  source-built Linux provider-free workflow certifies them).

## 4. Boundaries and next authorization

- Paid smoke (2+ rollouts, zero-flip gate on derivable tasks) requires
  explicit user authorization, per standing rule.
- Release gates (`READY`, `SMOKE_APPROVED`) are certified only by the
  source-built Linux provider-free workflow on the exact pushed commit.
- No solve-rate or efficiency claim is made from local proof alone.