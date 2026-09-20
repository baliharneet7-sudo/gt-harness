# GT capability surface: the 21 identities a paid run must witness

Source of truth: `attestation/feature-matrix.json`, schema `gt.feature_matrix.v2`,
`identity_count: 21`. The list below is not a description of intent. It is the
set the matrix enumerates, and every paid lane issues and verifies that matrix
before its evidence is accepted.

A row is **WITNESSED** only when both a positive and a negative execution are
recorded for it: the feature firing, and the feature correctly not firing. An
assertion in a docstring witnesses nothing.

## The 21

`CAP` is something the agent can invoke. `FACT` is evidence GT produces about
the repository.

| # | Identity | Kind | What it covers |
|---|---|---|---|
| 1 | `GT_CERT_DELIVERY` | CAP | Certified delivery of a context unit to the agent |
| 2 | `GT_CHANGE_SURFACE` | CAP | The surface a change is allowed to touch |
| 3 | `GT_EDIT_CHECK` | CAP | Checking a proposed edit before it is taken |
| 4 | `GT_HYPOTHESIS` | CAP | Hypothesis the agent asks GT to test |
| 5 | `GT_LOC_RESLOT` | CAP | Re-slotting localization when the first answer misses |
| 6 | `GT_PATCH_DELTA` | CAP | The delta between the agent's patch and the repository |
| 7 | `GT_SS_SUBMIT_RED` | CAP | Submit-time red check before a patch is claimed |
| 8 | `caller_contract` | FACT | The contract a callsite must satisfy |
| 9 | `cochange_prior` | FACT | Files that historically change together |
| 10 | `covering_red` | FACT | The failing test that covers the edited code |
| 11 | `def_partition` | FACT | Partition of definitions across the change |
| 12 | `localization` | FACT | Where in the repository the task lives |
| 13 | `newfile_precedent` | FACT | Precedent for a file the change creates |
| 14 | `obligations` | FACT | Obligations a change carries with it |
| 15 | `persistent_plan` | CAP | The plan that survives across agent steps |
| 16 | `plan_gate` | CAP | The gate a plan passes before work proceeds |
| 17 | `recovery` | FACT | Recovery after a failed or abandoned step |
| 18 | `select_catalog` | CAP | Catalog the agent selects context from |
| 19 | `signature_delta` | FACT | Change to a signature and who it breaks |
| 20 | `submit_refusal` | FACT | A submission GT refuses, and why |
| 21 | `syntax_result` | FACT | Syntactic result of an edit |

## A different axis: the five runtime rows

Per-task diagnostics report five capability rows, and they answer a narrower
question - did GT come up in this container at all:

`capability_negotiation`, `dense_retrieval`, `gt_engine_enabled`,
`lsp_promotion`, `receipt_writer`.

All five reported WORKING on both tasks of the SWE-bench-Live check (run
35536231471), with 837 and 4,608 attribution rows and LSP promotion publishing
378 edges. Those five being WORKING is a precondition for the 21 above meaning
anything: a task whose graph never built cannot witness a single one of them.

## Why the 2026-09-20 smokes did not measure this

Both 20-task smokes ran a producer that could not build a graph, for two
independent reasons found by those runs:

- **TB2**: the container's cgroup reported 2 GiB with 2.146 GiB "in use", which
  was page cache, so the index refused for want of headroom. Fixed by
  discounting reclaimable cache (`ae214745`).
- **DeepSWE**: `emitLabeled` popped an already-drained label list and panicked
  on any file with a labeled loop, killing the build. Fixed in producer
  `032014ef`.

The SWE-bench-Live check passed because its two tasks are Python, which has no
labeled statements, in containers large enough that cache never closed the
headroom. A narrow sample can be green while the product is broken, which is
the argument for the wider smoke.
