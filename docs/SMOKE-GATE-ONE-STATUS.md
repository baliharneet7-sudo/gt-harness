# Gate-one smoke — live status

## Attempt 2 (current) — run 34255966736

https://github.com/harneet2512/gt-harness/actions/runs/34255966736 — commit `dba7ac3e`

Attempt 1 failed at the producer provenance gate. The vendored source has been
reverted to the state the certified binary was built from; the fingerprint now
computes to `4f612d4c...`, matching what build-info declares. Details of that
failure are kept below.

| time (UTC) | event |
|---|---|
| 17:15 | dispatched on `main` at `dba7ac3e`, stage `gate-one` |
| 17:27 | acceptance concurrency group clear; dispatching gate-one |
| 17:27 | dispatched run 34257199043 — https://github.com/harneet2512/gt-harness/actions/runs/34257199043 |
| 17:27 | running: plan |
| 17:29 | running: readiness / provider-free-product; done: plan=success, readiness_binding=skipped |
| 17:35 | running: task (1, arktype-json-schema-refs-; done: readiness / provider-fre=success, readiness_binding=skipped, image_digest_gate=success, provider_gate=success |
| 17:48 | plan=success | readiness / provider-free-prod=success | readiness_binding=skipped | image_digest_gate=success | provider_gate=success | task (1, arktype-json-schema-r:Run DeepSWE through the released gt-harness run boun |
| 19:08 | plan=success | readiness / provider-free-prod=success | readiness_binding=skipped | image_digest_gate=success | provider_gate=success | task (1, arktype-json-schema-r=failure | attest:Download all task artifacts |
| 19:09 | running: attest; done: readiness_binding=skipped, image_digest_gate=success, provider_gate=success, task (1, arktype-json-sc=failure |
| 19:11 | done: image_digest_gate=success, provider_gate=success, task (1, arktype-json-sc=failure, attest=failure |
| 19:11 | RUN COMPLETE — conclusion=failure |
| 19:11 | plan=success | readiness / provider-free-prod=success | readiness_binding=skipped | image_digest_gate=success | provider_gate=success | task (1, arktype-json-schema-r=failure | attest=failure |
| 19:11 | ALL JOBS COMPLETE |

---


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
| 16:42 | running: readiness / provider-free-product; done: plan=success, readiness_binding=skipped |
| 16:48 | running: attest; done: image_digest_gate=success, provider_gate=success, task (1, arktype-json-sche=failure |
| 16:50 | done: provider_gate=success, task (1, arktype-json-sche=failure, attest=failure |
| 17:15 | running: attest; done: image_digest_gate=skipped, provider_gate=skipped, task=skipped |
| 17:17 | done: image_digest_gate=skipped, provider_gate=skipped, task=skipped |

## Result

**FAILED at the producer provenance gate — before any paid work ran.**

```
vendored producer source does not hash to what the binary declares
source_fingerprint declared : 4f612d4cdf487a22469765fd23f3500429c10ffea0677860785324c3e2e81551
source_fingerprint computed : 99a2a2390cc3c0e0191e548ab451595cd6e51c6cd47139756e22d7425cead9d4
```

Step: *Build the checked-in static graph indexer*, in the `task` job, at 16:51 UTC.
Nothing was spent on the provider: `plan`, `readiness`, `image_digest_gate` and
`provider_gate` all passed, and the run stopped at the first step of the task
job.

### Why

The Route-B contract requires the vendored `vendor/gt-index-src` tree to hash to
the `source_fingerprint` the certified binary declares. This session made four
commits to that source (co-change retention, symbol re-minting, deletion
support, the capability declaration), so the tree no longer corresponds to
`c3b9f16e`. The gate refused, correctly.

This drift predates tonight -- commits `043e14c6` and `25a37a5f` had already
modified the vendored source after `dfe32533` ("the vendored producer source now
hashes to what the binary declares") -- but tonight's commits widened it past
the check.

Note: `scripts/verify_producer_binding --enforce` passes locally and does NOT
catch this. The fingerprint comparison lives in the workflow step, not in that
script, which is why the local pre-flight was clean.

### Options

1. Revert `vendor/gt-index-src` on main, keep the producer work on a branch.
   The attested path works again and measures the engine-side fixes -- which is
   all this run could exercise anyway, since the amend is gated off by the
   certified binary not declaring `incremental_amend_in_place`.
2. Owner re-certifies a producer built from current source (the standing
   Route-B lineage blocker).
3. Accept that no attested run can happen while the drift stands.

---

## How to read the outcome

- `official-verifier-result.json` carries `status: GRADED` and `reward` 0 or 1.
  That is the only number that means "solved".
- `gt-run.json` carries the run receipt: terminal state, provider call count,
  and token usage as input / cached / uncached / output.
- A terminal of `submitted_unverified` means the agent submitted but some
  obligation had no evidence. It is exit 0, not a failure.
