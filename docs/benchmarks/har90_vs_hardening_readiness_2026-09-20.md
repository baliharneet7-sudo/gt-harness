# HAR-90 substrate vs the hardened benchmark branch: what is benchmark ready

Checked 2026-09-20, offline, zero spend. Everything below was verified here,
not taken from the handoff text.

## The headline

**Two branches each hold half of a benchmark-ready harness, and neither is
ready alone.**

| | `origin/main` (HAR-90) | `codex/gt-921bec20-union-smokes` (hardening) |
|---|---|---|
| GT producer pinned | `5681eeae`, schema `v15.4-callsite-actuals` | `d2e4a1c3`, schema `v15.2-trust-tier` |
| Wheel | `0a4eaf2e…` (verified) | `56a65a20…` |
| Paid benchmark lanes (TB2, DeepSWE, SWE-Live central) | **absent** | present |
| Receipt-consistency verifier, annotation escaper, TB2 report | **absent** | present |
| Provider route pin (StreamLake fp8, funds gate) | **absent** | present |
| Producer build workflow (`producer_build.yml`) | present | **absent** |
| Product acceptance | 14/14 verified here | 14/14 (on its own pin) |

Dispatching from the hardening branch today benchmarks the **old** GT.
Dispatching from main is impossible: the benchmark lanes do not exist there.

## Verified working

- **The HAR-90 artifact chain is real.** The vendored wheel hashes to
  `0a4eaf2e73581955ac043fb5bab7d1eaee7739b63459972d59194ac21677cd99`, exactly
  as the handoff claims, and `vendor/GROUNDTRUTH_WHEEL_SOURCE.txt` binds it to
  source `5681eeae` / tree `06abc381`.
- **The producer build exists.** GitHub run `35520971900` in
  `harneet2512/groundtruth`, "Build producer (linux amd64)", success, head
  `5681eeae`. (The handoff does not say which repo; it is not in gt-harness.)
- **Main's acceptance gate passes**: 14/14 in a clean checkout with the new
  wheel installed, including `VERIFIED_ROUTE_B_SOURCE_BOUND`.
- **Main's seal and lineage tests pass**: 47 passed, 6 skipped.
- **Main's suite size**: 1,805 tests collected. (The "4717 passed" figure in
  the handoff is the producer repo's suite, not this one.)
- **The producer source is pushed**: `5681eeae` is on
  `origin/wheel-patch-lsp-inventory`, so the substrate is not local-only.
- **The hardening branch survives the new producer.** With the new wheel
  installed and the bundle's `groundtruth` section rebound, its engine,
  receipt-verifier and preflight suites run green: **274 passed, 4 failed**.

## Verified not working

- **The 4 failures are the incomplete rebind, not code rot.** They are all
  provenance checks: `vendor/gt-index-linux-amd64.build-info.json` still holds
  the old digest `ca278fff…` where the new producer needs `cb383b8e…`; the
  bundle is then `source_closure_differs_from_head`, and
  `groundtruth_source_to_artifact_provenance_unverified` is raised.
- **A straight merge is not viable.** `git merge-tree` reports about 294
  conflicts, most of them the workflow archive: main deleted lanes that the
  hardening branch moved to `.github/workflows-archive/`.
- **`docs/operations/BENCHMARK_READINESS_STATUS.md` on main is stale.** It was
  last touched 2026-09-09 and still describes the `4df7ab9c` release, wheel
  `4c4ba9ac…`, producer `8763262b…` - two producer generations ago.
- **The GT source import manifest exists only on the hardening branch.**
  `config/tb2_gt_import_manifest.json` is not on main, so main has no
  object-level pin of the GT source it benchmarks.
- **Nothing here is proven against a real graph.** Every `gt-index`-dependent
  test skipped locally with "gt-index binary unavailable"; the binary is
  installed in CI only.

## What is left to be benchmark ready

1. **Decide which GT is under test.** The old pinned substrate (ready now) or
   the HAR-90 parser-exact substrate (better product, needs the rebind below).
   Everything else follows from this choice.
2. **If HAR-90: rebind the hardening branch to the new producer.** Copy from
   main the wheel, `GROUNDTRUTH_WHEEL_SOURCE.txt`, the build-info and
   builder-identity receipts, and the `vendor/gt-index-src` snapshot; take the
   `groundtruth` section of `config/deepswe_product_bundle_v1.json`; recompute
   the manifest seal; commit, because the closure check compares against HEAD.
   Cherry-pick `producer_build.yml` and its closed-set admission. Then
   acceptance should be 14/14 rather than 10/14.
3. **Re-pin the source manifest.** `config/tb2_gt_import_manifest.json` must be
   re-derived after any rebind; it has one verifier and no regenerator.
4. **Re-run the offline gate** on the rebound branch: full suite in a
   `--no-local` clone, workflow lint, validators, collect-only.
5. **Then the paid sequence** (needs authorisation): product workflow first, no
   provider calls; then a 2-3 task TB2 subset; check cache-hit rate, cost per
   task and reasoning tokens against the frozen baseline before scaling.
6. **Still open and unchanged**: StreamLake's 90% price promotion must be
   re-read before each dispatch; DeepSWE reasoning effort `max` is undecided;
   SWE-Live Lite needs the 0423 route.

## Residuals the handoff names, and they are honest

`interprocedural_name_matched` (signature-proven, not type-proven),
`approximate_use_coverage`, `approximate_actual_extraction`, `owner_unknown`.
Each is a flag on the evidence rather than a silent approximation, which is
the behaviour this harness is built to require. Open questions carried
forward: `param` coverage parity, NULL `receiver_*` columns,
`callsite_stable_id` on legacy CALLS edges.
