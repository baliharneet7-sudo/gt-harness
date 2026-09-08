# Gate-one smoke — live status

**Purpose.** One DeepSWE task through the attested GitHub Actions path, on the
merged main commit. This is the run that produces a real graded reward, unlike
the codespace smokes which have no verifier.

**Why Actions and not the codespace.** The codespace is refusing to start:
`HTTP 402 — There is a billing issue that is preventing you from starting this
codespace`. Actions bills from a different pool, so this path may still run.

---

## What is under test

| | |
|---|---|
| commit | `7f2c26d0` (main) |
| workflow | `deepswe_gt_harness_product_p0731.yaml` — "GT Harness: DeepSWE paid smoke20" |
| stage | `gate-one` — exactly one task |
| model | `deepseek/deepseek-v4-flash-0731`, route pinned to relace |
| producer | vendored certified `c3b9f16e` (see limitation below) |

## What this run does and does not exercise

**Does**: reverification firing on edits, the pre-edit graph handed to the edit
producers, the corrected invalidation reporting, deletion handling in the
engine, and the whole attested path through to a graded reward.

**Does not**: the graph amend. The workflow takes its producer from the bundle,
which pins the certified binary by SHA-256, and that build does not declare
`incremental_amend_in_place`. The capability gate therefore refuses and every
edit falls back to a full rebuild. Making it otherwise would require re-pointing
the Route-B lineage at a locally built binary, which is a false attestation.

The amend is evidenced separately by the completed arktype codespace run:
28 amends on a 184,370-node graph, caller coverage 26% → 63%.

---

## Status

**Run 34252620919** — https://github.com/harneet2512/gt-harness/actions/runs/34252620919

| time (UTC) | event |
|---|---|
| 16:42 | dispatched on `main`, stage `gate-one`, in progress |

## Result

_Not yet complete._

---

## How to read the outcome

- `official-verifier-result.json` carries `status: GRADED` and `reward` 0 or 1.
  That is the only number that means "solved".
- `gt-run.json` carries the run receipt: terminal state, provider call count,
  and token usage as input / cached / uncached / output.
- A terminal of `submitted_unverified` means the agent submitted but some
  obligation had no evidence. It is exit 0, not a failure.
