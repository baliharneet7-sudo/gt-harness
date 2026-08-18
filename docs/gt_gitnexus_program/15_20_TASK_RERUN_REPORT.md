# 15 — Same-20 validation report

## Decision

**The 20-task promotion gate is still blocked.** This report does not invent a
rerun that has not happened. The latest completed matched treatment is workflow
`32163376177` at commit `e423c87`; the candidate commit is based on `18f95fb`
and contains the repairs described below. Local and Codespaces provider-free
checks pass, but the candidate has not yet received authoritative exact-pushed-
SHA proof or produced live outcomes on the frozen `repair20-v1` denominator.

Confidence in this status: **high**.

## Latest completed matched outcome

Source: the downloaded merged summary at
`D:\tmp\run32163376177-merged\SUMMARY.md` and the per-task receipts under
`D:\tmp\run32163376177`.

| Result | Count | Tasks |
|---|---:|---|
| Both solve | 13 | cobol, FEAL, fix-code, headless, LLM batching, MCMC, portfolio, prove-plus-comm, qemu, regex-chess, schemelike, winning-corewars, write-compressor |
| GT only | 1 | largest-eigenval |
| Frozen baseline only | 4 | extract-elf, sanitize-git-repo, torch-tensor-parallelism, video-processing |
| Both fail | 2 | count-dataset-tokens, torch-pipeline-parallelism |

Treatment arithmetic: **14/20 solved, 20/20 graded, zero errors**. Frozen
baseline arithmetic: **17/20 solved**. The promotion verdict is therefore
**FAIL**, independent of fingerprint metadata.

Causal status: **unidentified**. The frozen outcomes establish quadrants, not
causation. The available artifacts do not justify calling the largest-eigenval
gain GT-caused or any of the four losses definitely GT-caused. See
[04_GT_NEGATIVE_FLIP_AUTOPSY.md](04_GT_NEGATIVE_FLIP_AUTOPSY.md) and
[05_GT_POSITIVE_FLIP_AUTOPSY.md](05_GT_POSITIVE_FLIP_AUTOPSY.md).

## Latest completed integrity and efficiency results

The run's merged gate reported two repository-intelligence failures, two
provider-delivery failures, and thirteen per-task release failures. The causal
receipt audit shows that the two repository-intelligence labels were downstream
frontier/accounting failures: graph and dense substrate were healthy on all 20.
Persistent-state lifecycle executed on all 20, but accounting and delivery
certification were not clean.

On common-solved tasks, GT used six fewer provider calls and 5,001,412 fewer
total tokens, but 304,712 more uncached input tokens and $0.16644 more normalized
cost. Across the full profile it used 112 more calls, 621,801 more uncached
input tokens, and $0.07137 more normalized cost. This is not an efficiency pass.

Confidence: **high** for the receipt and aggregate arithmetic; **unknown** for
model-level causality.

## Repairs now implemented in the candidate

1. Root-wide searches are no longer mislabeled as direct grader-artifact reads;
   explicit forbidden selectors remain blocked, and provider-visible wording is
   neutral.
2. Successfully parsed declaration-free source, including command-only shell,
   receives an identity-only `File` node. Malformed and comment-only files still
   abstain, and `File` nodes cannot become definitions or caller obligations.
3. Repository semantic evidence is filtered to the current action path/symbol;
   certified reverse relations remain eligible only when their target endpoint
   matches that action.
4. Graph database and manifest publication is hash-, root-, source-, and binary-
   certified under a cross-process publication lock with pair rollback.
5. A bounded, non-blocking `CoupledChangeObligation` composes a changed endpoint,
   certified dependent, certified test relation, and declared check without
   asserting that every related file must be edited.
6. The authoritative delivery audit recognizes the coupled claim surface.
7. The trajectory audit now correctly recognizes `execution_observation` as one
   of the three legal evidence-source classes required by `AGENTS.md`.

These are Type 1 integrity repairs, Type 2 mechanism strengthening, and one
Type 3 solve amplifier. They are not outcome claims.

## Provider-free validation performed

### Local source-built validation

- Complete Go module: **PASS**.
- Full central provider-free Python matrix using a newly built
  `sqlite_fts5` indexer and the pinned Snowflake ONNX asset: **PASS**; one
  POSIX-shell-only test skipped on Windows.
- Repository substrate fixture: **PASS** (`REPOSITORY_SUBSTRATE_PROVEN`).
- Language depth audit: **PASS**.
- Local structural readiness subcheck: **PASS** (18/18 configured mechanisms).
  This is non-authoritative and is not the workflow-level `READY` /
  `SMOKE_APPROVED` proof reserved for an exact pushed Linux commit.
- Evidence-source integrity: **PASS** (`EVIDENCE_SOURCE_ALLOWLIST_PROVEN`,
  `NO_GRADER_ACCESS_PROVEN`).
- Exact pre-smoke gate: **pending the exact pushed candidate SHA**. Every local
  non-push-dependent pre-smoke subgate passed.

### Codespaces/Linux validation

- Complete Go module: **PASS**.
- Source build with the production `sqlite_fts5` tag: **PASS**.
- Focused repository-intelligence, repository-context, convergence, delivery,
  and release-gate suite: **PASS**.
- An initial build without `sqlite_fts5` correctly failed the FTS schema gate;
  the production-tag build then passed. This proves the gate fails closed on an
  incorrectly built indexer.
- Full pinned-ONNX workflow parity was not claimed: the dormant Codespace had no
  GitHub CLI credential, and no login was performed. The pinned asset was fully
  exercised in the local source-built matrix instead.

## Offline replay of all 20 latest receipts

After correcting the legal-origin audit taxonomy, current code certifies:

- 20/20 task receipts discovered;
- 243/243 visible deliveries timely;
- 672 visible claims;
- zero late deliveries;
- zero predictive deliveries;
- zero duplicate deliveries;
- deterministic trajectory integrity **CERTIFIED**;
- model causality **UNIDENTIFIABLE**, as required without replayable
  counterfactual state.

The current per-task release checker still rejects 12 old receipts: ten carry
historical contribution task-usage mismatches, and extract/sanitize/tensor carry
historical terminal-effect/accountability/foreign-key mismatches. A current
checker cannot retroactively add fields or repair accounting in an archived
receipt. These rows are evidence that a live exact-candidate run is still needed,
not a reason to weaken the gate.

## Required next evidence

1. Review and commit only the intended code, tests, and program artifacts.
2. Run the exact pushed SHA through the authoritative Linux provider-free
   workflow. It must print the full 17+1 census, `READY`, and `SMOKE_APPROVED`.
3. Only then dispatch the treatment-only frozen same-20 workflow. Do not create
   a new GT-off arm; use the frozen control for descriptive solve accounting.
4. Require 20/20 graph/retrieval applicability decisions, valid delivery
   receipts, current postflight state, contribution conservation, terminal
   effect conservation, and exact fingerprints.
5. Report integrity, solve, efficiency, and intervention results separately.

Until those steps pass, the release state is **IMPLEMENTED_UNVERIFIED**, not
ready and not promoted.
