# GroundTruth complete implementation record

Date: 2026-08-21  
Repository: `harneet2512/gt-harness`  
Branch: `baseline-swe-live-lite-v4flash0731`

## Status

`PARTIALLY VERIFIED` for implementation mechanics (no-spend): Linux provider-free
mechanical completeness passed for candidate SHA `77db941152d0d33929348590c7ce9528b3be64d6`
in workflow [32526386608](https://github.com/harneet2512/gt-harness/actions/runs/32526386608)
with `provider_calls: 0`, `READY`, `SMOKE_APPROVED`, and `GT_MECHANICAL_COMPLETENESS=PASS`.
The canonical release identity is still in
[`active_release.json`](../eval/release/active_release.json), which currently points to
runtime SHA `bcc1543d6d050cb54820baeccc15c3c8f2e230cc`.
This is a mechanical-completeness closure step, not an outcome/solve claim.

## Product contract

GroundTruth is the host-owned `MiniSweCentralAgent`. It uses only the task
instruction, repository source in the task workspace, and already-observed
execution results. It never reads grader-only artifacts, changes the verifier,
or changes the benchmark denominator.

The product census is exactly 17 historical FACT/CAP mechanisms plus persistent
execution state. Natural trigger counts are reported separately from configured
mechanisms and persistent lifecycle use.

## Implemented system

- bounded workspace sensing and source-only mirroring;
- language resolution for suffix, basename, shebang, and content signatures;
- source-built Go graph index with identity-only file nodes for declaration-free
  sources and semantic exclusion of those nodes;
- graph/manifest atomic publication, certification, locking, and recovery;
- synchronous bounded graph refresh at the postflight boundary, with no
  abandonable worker thread and no stale next-transition escalation;
- source-to-non-source and deletion transitions resolved from the prior mirror
  even when the workspace sensor intentionally omits oversized source text;
- source revision advances only for real source/code deliverables, including
  extensionless content-signature sources, never for arbitrary output files;
- exact, lexical, BM25, pinned local dense, and certified structural retrieval;
- graph-first persistent execution state with deterministic zero-provider
  selection, current-revision compile/preflight/postflight/rebase receipts;
- repository definitions, signatures, certified calls, reverse impact, tests,
  routes, re-exports, inheritance, overrides, process views, coupled obligations,
  and resolved conventions where evidence is exact;
- graph-independent task semantics and observed-execution facts;
- shared contribution budget and provider-value certificates requiring exact
  authority, materiality, novelty, anchors, decision point, and the ordinary
  exploration operation the evidence is expected to replace;
- same-observation provider delivery with request/provider hashes, message
  indices, first-eligible timing, and claim provenance;
- typed convergence, validation, completion, replay, intervention-chain, and
  terminal execution certificates;
- typed mutually exclusive trial outcomes: solved, graded-unsolved, censored,
  non-censor error, and missing verifier;
- immutable promotion route derived from the frozen baseline identity, joined
  at merge to the live one-call canary and every task receipt's configured
  endpoint/response identity;
- secret-only credentials, no secret-valued workflow inputs, and no scheduled
  benchmark monitor;
- machine-audited documentation, legal-source, release, and product-completeness
  gates.

## Archived 20-task evidence

Workflow `32455040841` returned 20 task rows. Current replay accepts all 20
deterministic central receipts and all 20 provider-delivery receipts. The
historical run itself remains invalid release evidence on four rows: one real
graph-refresh failure (`count-dataset-tokens`) and three provider connection
censors (FEAL, regex-chess, schemelike). Historical receipts cannot prove the
current candidate executed.

The archived cohort has one raw GT-only solve (`largest-eigenval`) and ordinary
baseline-only outcomes, but no baseline trajectories. Therefore no positive or
negative flip is assigned confirmed GT causality.

## Final proof still required

1. decide whether the release manifest should move to runtime SHA
   `77db941152d0d33929348590c7ce9528b3be64d6` (the latest proven candidate) or
   re-run provider-free on the manifest runtime SHA `bcc1543d6d050cb54820baeccc15c3c8f2e230cc`;
2. run the full Python suite against that exact frozen identity;
3. ensure current Go source is built and tested with `sqlite_fts5` on Linux;
4. ensure provider-free proof is aligned to the exact frozen manifest runtime SHA;
5. replay all 20 current receipts through delivery, integrity, and release audits and
   keep all schema/runtime mismatch labels explicit;
6. align the remaining no-spend outputs with that exact frozen candidate;
7. push the exact frozen SHA;
8. one matched-paid 20-task GT-on smoke remains the final benchmark authorization step.

Only then may one paid matched 20-task GT-on smoke run.
