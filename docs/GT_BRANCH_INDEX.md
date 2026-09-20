# GT branch index: what lives where, what is done, what is left

Last updated **2026-09-19**. This file is the map. Local disk keeps only the
checkouts in section 1; everything else lives on GitHub. The detailed record
of the hardening work is `docs/benchmarks/gt_hardening_rsi_2026-09-18.md`,
mirrored in Linear **HAR-88**.

Remotes (all repo `gt-harness`): `origin` = harneet2512, `baliharneet7` =
baliharneet7-sudo, `fork` = hbali-stack, `hbali-live` =
hbali-stack/gt-harness-swe-live-lite.

## 1. What is still on local disk, and why

| Path | Branch | Why it stays |
|---|---|---|
| `D:\gt-harness` | `embed-bakeoff` | Primary checkout and the shared `.git` store. |
| `D:\w\t` | `codex/tb2-gt-union-921bec20`, pushed as `codex/gt-921bec20-union-smokes` | **The branch to dispatch from.** Hardening record and the StreamLake fp8 pin. |
| `D:\gt-control-main` | `main` plus uncommitted finalstand and typed-actions edits | **Active work, edited 2026-09-19, NOT on GitHub yet.** Commit it to a branch and push when done. |
| `D:\gt-product-source` (with `gt-context-producer`, `gt-context-producer-verify`) | groundtruth repo, `fix/inventory-divergence-heal` plus 20 uncommitted files | **Active producer work, edited 2026-09-19, NOT on GitHub yet.** |
| `D:\Groundtruth` | not a git checkout | Referenced by code (`gt-index.exe`, the finalstand validator). |
| `D:\gt-cloud` | `cloud/internal-harness` | Separate product; holds a local `.env`. |
| `D:\gt_baselines` | none | Frozen GT-off baselines: TB2 66/89, SWE-Live 83/300, DeepSWE 0.5332. Never delete. |
| `D:\gt_runs` | none | Original run outputs, including the baseline originals. |

Kept for now, not on GitHub, all small and non-git: `D:\release`,
`D:\gt-fh-producer`, `D:\polyloc_repos`, `D:\gt-dense-model-snowflake`,
`D:\har59-*-local-*`, `D:\benchmark-readiness\deepswe-run-34257199043`.

## 2. What is done

- **Offline hardening is complete.** Two campaigns, 19 adversarial reviews, and
  a clean-clone suite with zero failures, on `codex/gt-921bec20-union-smokes`.
- **GT source re-pinned.** `gt_engine` is tree `9d987079` (`88fc821c`).
- **Model identity settled.** The TB2 and DeepSWE baselines are V4 Flash 0731
  at fp8. DeepSeek's own API now serves V4.1, so it is not used.
- **Provider pinned.** OpenRouter routes to StreamLake only, with fp8 enforced on
  every request (`a856fd12`). Its chat template adds 4 prompt tokens; accepted.
- **Baselines collected** in `D:\gt_baselines\` with a README index.
- **Disk cleanup, 2026-09-19.** 63 worktrees and 109 junk folders removed,
  about 49 GB freed (D: free went from 59 GB to 109 GB). Local-only work was
  pushed to `archive/2026-09-19/*` first.

## 3. What is left

1. **User decision:** match DeepSWE reasoning effort `max` on DeepSWE lanes.
2. **User decision:** the SWE-Live Lite route. Its baseline is V4 Flash **0423**.
3. **Before every paid dispatch:** re-read StreamLake's OpenRouter price. It is a
   90% promotion; undiscounted costs are ten times higher.
4. **First paid run, only when authorised:** the product workflow (zero provider
   calls), then a 2-3 task TB2 subset. Check cache-hit rate, real cost per task
   and reasoning tokens per call against the baseline before scaling.
5. Commit and push the active work in `D:\gt-control-main` and
   `D:\gt-product-source`.
6. Not our code: handoff defects 4-7 (hardening record section 11).

## 3a. Is anything still only on this disk?

Run the scanner instead of searching by hand; it exits non-zero while any GT
checkout holds work GitHub does not have:

```
python -m scripts.find_unsaved_work --fetch --write docs/internal/UNSAVED_WORK.md
```

Its output is `docs/internal/UNSAVED_WORK.md`, and `docs/internal/README.md`
explains the routine and what the verdicts mean. Run it before deleting
anything.

## 3b. HAR-90 landed on main and is not in the dispatch branch

`origin/main` now pins a newer GT producer (`5681eeae`, schema
`v15.4-callsite-actuals`) from the HAR-90 parser-exact substrate work, while
the dispatch branch still pins `d2e4a1c3` / `v15.2-trust-tier`. Main has no
benchmark lanes and none of the hardening; the dispatch branch has no HAR-90
artifacts. Neither is benchmark ready alone, and a straight merge conflicts in
about 294 places. What was verified and what a rebind needs:
`docs/benchmarks/har90_vs_hardening_readiness_2026-09-20.md`.

## 4. Branches on GitHub

`merged` means contained in `origin/main`. `open` means not merged; it may be
superseded, and the last commit subject says what the branch is.

### Archived 2026-09-19 before disk cleanup (local-only work, preserved) (12)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `archive/2026-09-19/product-completion-red-evidence-workflow` | 2026-09-19 | `bb48ad08` | baliharneet7,fork,origin | open | chore: archive uncommitted work from gt-product-completion before disk cleanup |
| `archive/2026-09-19/review-inbox-b45` | 2026-09-19 | `c7d7523d` | baliharneet7,fork,origin | open | chore: archive uncommitted work from review-inbox-b45 before disk cleanup |
| `archive/2026-09-19/tb2-gt-smoke-921bec20-central-workflow` | 2026-09-19 | `e9a8c760` | fork | open | chore: archive uncommitted work from g before disk cleanup |
| `archive/2026-09-19/gt-review-inbox-wip` | 2026-09-04 | `80c5ee5b` | baliharneet7,fork | open | inbox: HAR-83 exact producer 08fe997d0 review |
| `archive/2026-09-19/har63-review` | 2026-08-31 | `df005d00` | baliharneet7,fork | open | fix: bind why-edge explanations into receipts |
| `archive/2026-09-19/har66-review2` | 2026-08-31 | `c7cb9bae` | baliharneet7,fork | open | fix: add Leiden refinement and incremental delta path |
| `archive/2026-09-19/har67-review` | 2026-08-31 | `479efc64` | baliharneet7,fork | open | fix: execute public audit replay and mutation checks |
| `archive/2026-09-19/temp-review-har12-271b` | 2026-08-31 | `271b88fc` | baliharneet7,fork | open | fix: add executable trust calibration receipts and frozen-case verification |
| `archive/2026-09-19/temp-review-har38-23a` | 2026-08-31 | `23adc9e4` | baliharneet7,fork | open | feat: add HAR-38 provider-free GT-off control receipt |
| `archive/2026-09-19/temp-review-har38-940` | 2026-08-31 | `940bdcda` | baliharneet7,fork | open | feat: add HAR-38 provider-free GT-off control receipt |
| `archive/2026-09-19/temp-review-har41-8749` | 2026-08-31 | `8749b349` | baliharneet7,fork | open | fix: enforce capability matrix revision consistency |
| `archive/2026-09-19/temp-review-har8-42b` | 2026-08-31 | `42b4c4e4` | baliharneet7,fork | open | fix: make optional vec0 witness environment-safe |

### Codex/Claude work lanes (67)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `codex/gt-921bec20-union-smokes` | 2026-09-19 | `11ed847b` | baliharneet7,fork,origin | open | docs: record StreamLake provider decision and its promotional pricing |
| `codex/phase5-harness-proof` | 2026-09-17 | `7bd86ee6` | origin | open | indexer: prove the per-file amend lane functionally, not by declaration |
| `codex/tb2-openrouter-ready` | 2026-09-17 | `f4aaf2bf` | fork | open | Fix TB2 grading from completed verifier artifacts |
| `codex/livelite-openrouter-ready` | 2026-09-16 | `3b8a7e0e` | baliharneet7 | open | Fix SWE-Live saved-patch dataset validation |
| `codex/deepswe-cohort-1bdb35f0` | 2026-09-15 | `1bdb35f0` | origin | open | docs(status): record green gate pair on the audit-21 tip |
| `codex/context-plan-integrity` | 2026-09-13 | `2cad281e` | origin | open | fix(rehearsal): audit binds the prose execution-evidence line, not canonical JSON |
| `codex/context-plan-review` | 2026-09-11 | `48e8708e` | origin | open | review packet: producer 6ce40681 (QUERIES/INJECTS + data_access_edges_v1) CI green |
| `codex/deepswe-openrouter-ready` | 2026-09-09 | `355a7fd8` | origin | merged | Pull DeepSWE tasks from the verified GHCR mirror |
| `codex/product-completion` | 2026-09-09 | `25ec7a76` | baliharneet7,fork,origin | open | fix: the planning call never returned a plan, on any task |
| `codex/har83-producer-def2-review` | 2026-09-05 | `c86d7d51` | origin | open | inbox: HAR-83 exact producer 84e19be70 review |
| `codex/har81-a20-a21` | 2026-09-02 | `a2804a6e` | origin | merged | fix(review): verify content semantics and supersession chain |
| `codex/har81-arktype-resource` | 2026-09-02 | `c6e5a47d` | origin | merged | fix: fail closed on unknown process state |
| `codex/har81-audit-discovery` | 2026-09-02 | `69cfe4d8` | origin | merged | fix(audit): normalize provider check projection |
| `codex/har81-pr43-merge-packet` | 2026-09-02 | `92d3d087` | origin | open | chore(review): seal HAR-81 resource guard landing |
| `codex/har81-readiness-reuse` | 2026-09-02 | `45d0009f` | origin | merged | verify readiness workflow conclusion independently |
| `codex/har81-staged-smoke` | 2026-09-02 | `544a873d` | origin | merged | stage paid smoke behind verified gate |
| `codex/smoke20-task-digest-portability` | 2026-09-02 | `befe2f39` | origin | merged | fix(smoke): make task config identity platform-stable |
| `codex/har76-ci` | 2026-09-01 | `701a8472` | origin | merged | ci(HAR-76): isolate legacy metadata compatibility checkout |
| `codex/har78-deep-architecture` | 2026-09-01 | `5893a3ba` | origin | merged | docs(HAR-78): document deep pipeline architecture |
| `codex/har79-ci-parallelism` | 2026-09-01 | `d599a084` | origin | merged | fix(HAR-79): route current CI packets to the inbox |
| `codex/har80-source-parity` | 2026-09-01 | `a4af3484` | origin | merged | test(HAR-80): bind route receipt digest |
| `codex/product-acceptance-repair` | 2026-09-01 | `0ad5c41c` | origin | merged | Regenerate A18 feature matrix through validating writer |
| `codex/har10-order6` | 2026-08-31 | `8e3c5b80` | origin | merged | fix: correct HAR-10 zero-labeled Wilson bounds |
| `codex/har11-suite-repair` | 2026-08-31 | `53490708` | origin | merged | fix: align HAR-11 feature-18 census expectations |
| `codex/har11-suite-repair2` | 2026-08-31 | `3f86ca90` | origin | open | fix: make HAR-5 receipt diff-check truthful |
| `codex/har12-order7` | 2026-08-31 | `884a3e82` | origin | merged | fix: bind normalized stratum inputs in case digest |
| `codex/har14-process` | 2026-08-31 | `576da055` | origin | merged | feat: persist witnessed processes for planning |
| `codex/har29-readme` | 2026-08-31 | `4d3a834c` | origin | merged | docs: label in-assembly capabilities and close F15 status (F17) |
| `codex/har30-verdict-gate` | 2026-08-31 | `edf311d4` | origin | open | fix: align shipped manifest with verdict coverage refusals |
| `codex/har35-central-runtime` | 2026-08-31 | `bad12be8` | origin | merged | fix: repair HAR-35 rebase conflict in execution state |
| `codex/har36-repin` | 2026-08-31 | `75006575` | origin | merged | fix: align HAR-11 feature-18 census expectations |
| `codex/har36-source-qa` | 2026-08-31 | `18f35cda` | origin | merged | fix: bind HAR-36 archive proofs to reviewed source blobs |
| `codex/har38-controls` | 2026-08-31 | `d2f1839c` | origin | merged | feat: add HAR-38 provider-free GT-off control receipt |
| `codex/har41-capability-matrix` | 2026-08-31 | `92056de1` | origin | merged | fix: enforce capability matrix revision consistency |
| `codex/har48-failure-ids` | 2026-08-31 | `81e40b44` | origin | merged | fix: bootstrap direct construction hook imports |
| `codex/har5-baseline` | 2026-08-31 | `04de92cc` | origin | merged | fix: make HAR-5 receipt diff-check truthful |
| `codex/har62-calibration` | 2026-08-31 | `ad022ba4` | origin | merged | HAR-62 wire calibration collector and receipt issuer |
| `codex/har63-why-edge` | 2026-08-31 | `cc52917d` | origin | merged | HAR-63 harvest and certify resolution substrate |
| `codex/har64-eligibility` | 2026-08-31 | `bd099b88` | origin | merged | HAR-64 ship eligibility receipt issuer |
| `codex/har65-intent-rescore` | 2026-08-31 | `990a8281` | origin | merged | feat: add intent-conditioned exact retrieval rescore |
| `codex/har66-leiden` | 2026-08-31 | `fb6ccf2e` | origin | merged | HAR-66 make delta-Q updates genuinely incremental |
| `codex/har67-public-reaudit` | 2026-08-31 | `58032bda` | origin | merged | HAR-67 document harness-root re-audit alias |
| `codex/har68-repin` | 2026-08-31 | `3178a467` | origin | merged | chore(HAR-68): re-pin producer to gt-trial framework head |
| `codex/har69-clean` | 2026-08-31 | `65194707` | origin | merged | feat(HAR-69): add content-addressed index reuse key |
| `codex/har69-index-reuse-prep` | 2026-08-31 | `65194707` | origin | merged | feat(HAR-69): add content-addressed index reuse key |
| `codex/har7-communities` | 2026-08-31 | `e823f1f6` | origin | merged | fix: name community algorithm as local moving |
| `codex/har70-framework-resolution` | 2026-08-31 | `ff578719` | origin | merged | feat(HAR-70): bind framework validation and producer repin |
| `codex/har73-feature-matrix` | 2026-08-31 | `326d0045` | origin | merged | feat(HAR-73): add feature proof matrix with digest-bound evidence cells |
| `codex/har74-context-packet-design` | 2026-08-31 | `af389286` | origin | open | Revert "feat(HAR-69): add content-addressed index reuse key" |
| `codex/har74-wiring` | 2026-08-31 | `9a31f416` | origin | merged | feat(HAR-74): seal served context packets through eligibility |
| `codex/har77-archdone` | 2026-08-31 | `aa6577a0` | origin | merged | docs(HAR-77): refresh architecture currency after HAR-70 |
| `codex/har8-retrieval` | 2026-08-31 | `c4a7ac71` | origin | merged | fix: make optional vec0 witness environment-safe |
| `codex/har9-closeout` | 2026-08-31 | `e0a3bf90` | origin | merged | feat: stage provisional HAR-9 assembly inputs |
| `codex/har9-f21-canonical-receipts` | 2026-08-31 | `039121bc` | origin | merged | chore: reissue canonical F21 receipts |
| `codex/control-record-idempotency-fd019-parity` | 2026-08-30 | `caa6cd4a` | origin | merged | fix: bind parity receipt to exact parent |
| `codex/control-record-idempotency-main` | 2026-08-30 | `6568f3d8` | origin | merged | fix: fail closed on malformed control envelopes |
| `codex/har11-order4` | 2026-08-30 | `666d3660` | origin | merged | feat: implement HAR-11 feature-18 catalog lifecycle |
| `codex/har58-authority-validator` | 2026-08-30 | `a3dcfc14` | origin | merged | test: lock prepared replay cache boundary |
| `codex/har61-closeout-evidence` | 2026-08-30 | `55bc619f` | origin | open | fix: commit authoritative closeout/graph.db for digest verification |
| `codex/har61-harness-provenance` | 2026-08-30 | `fc551a55` | origin | merged | feat: add typed resolution provenance consumer |
| `codex/har6a-candidate-integrity-repair` | 2026-08-30 | `6b518c33` | origin | open | fix(gt): fail closed on invalid resolution candidates |
| `codex/har6a-non-vendor-producer-integration` | 2026-08-30 | `41269778` | origin | open | fix: bind producer source and portability |
| `codex/control-record-idempotency` | 2026-08-29 | `0fbadcba` | origin | open | feat(gt): add conservative resolution sidecar |
| `codex/gt-harness-overhaul` | 2026-08-29 | `b0c3b56b` | origin | open | HAR-28 revoke stale benchmark authorization |
| `codex/gt-harness-overhaul-clean` | 2026-08-29 | `12b50b3c` | origin | open | revert: remove rejected vendored index binary selector |
| `codex/fs023-main-merge` | 2026-08-01 | `c9c1b72b` | origin | merged | Merge origin/main into gt-integration |
| `codex/miniswe-single-witness` | 2026-08-01 | `90260030` | origin | open | Add closed Mini-SWE matched witness workflow |

### Fix lanes (19)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `fix/deepswe-gt-off-smoke-v2` | 2026-08-27 | `dbf8ee49` | fork | open | fix: identify DeepSWE as OpenRouter agent harness |
| `fix/deepswe-gtoff-merge-clean` | 2026-08-27 | `a160e227` | origin | open | fix: default DeepSWE OpenRouter base URL |
| `fix/live-lite-task-language` | 2026-08-24 | `b0818abf` | baliharneet7,origin | open | Rotate Docker Hub accounts for Live Lite image cache |
| `fix/deepswe-gt-off-smoke` | 2026-08-22 | `213de44e` | fork | open | fix(deepswe): skip GT canary for off-arm smoke |
| `fix/deepswe-gtoff-merge` | 2026-08-22 | `53fd567c` | fork | open | fix(deepswe): remove nonofficial task wall cap |
| `fix/live-lite-task-language-v10` | 2026-08-22 | `4d505b62` | baliharneet7 | open | fix live lite ox alpha cost tracking |
| `fix/live-lite-task-language-v11` | 2026-08-22 | `18004605` | baliharneet7 | open | fix live lite trajectory filename bridge |
| `fix/live-lite-task-language-v12` | 2026-08-22 | `02417e45` | baliharneet7 | open | fix live lite baseline metrics collection |
| `fix/live-lite-task-language-v13` | 2026-08-22 | `39d69d3b` | baliharneet7 | open | enforce live lite agent budget in container |
| `fix/live-lite-task-language-v14` | 2026-08-22 | `80a7920d` | baliharneet7 | open | restore baseline prediction patch helper |
| `fix/live-lite-task-language-v15` | 2026-08-22 | `1af267e2` | baliharneet7 | open | allow honest unmeasured baseline metrics |
| `fix/live-lite-task-language-v2` | 2026-08-22 | `dedcb968` | baliharneet7 | open | fix(live-lite): allow explicit provider key for smoke |
| `fix/live-lite-task-language-v3` | 2026-08-22 | `b6e79426` | baliharneet7 | open | fix(live-lite): use headless baseline runner without GT seam |
| `fix/live-lite-task-language-v4` | 2026-08-22 | `c237362e` | baliharneet7 | open | fix(live-lite): skip GT hashes in baseline identity audit |
| `fix/live-lite-task-language-v5` | 2026-08-22 | `d598fb68` | baliharneet7 | open | fix(live-lite): bind baseline identity flag in second audit |
| `fix/live-lite-task-language-v6` | 2026-08-22 | `6191609b` | baliharneet7 | open | fix(live-lite): propagate baseline identity mode to task audit |
| `fix/live-lite-task-language-v7` | 2026-08-22 | `d4c3be3b` | baliharneet7 | open | fix live lite baseline skip gt-only seam |
| `fix/live-lite-task-language-v8` | 2026-08-22 | `8e23fc2a` | baliharneet7 | open | fix live lite baseline model handoff |
| `fix/live-lite-task-language-v9` | 2026-08-22 | `abbfb840` | baliharneet7 | open | fix live lite configurable openai compatible routing |

### final_hardening streams (HAR-83) (6)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `final_hardening/item11-taxonomy-engine` | 2026-09-03 | `7b8d8183` | origin | merged | docs(arch_pipeline): record item 7 communities at 43514ced1 |
| `final_hardening/item2-engine` | 2026-09-03 | `6909e3de` | origin | open | docs(final_hardening): record item 2 harness measurements |
| `final_hardening/item3-contract` | 2026-09-03 | `0c50bd93` | origin | merged | docs: name the effort final_hardening |
| `final_hardening/item4-retrieval` | 2026-09-03 | `0c50bd93` | origin | merged | docs: name the effort final_hardening |
| `final_hardening/item5-embeddings` | 2026-09-03 | `96473d2a` | origin | open | docs: final item 5 report with the full-suite numbers |
| `final_hardening/item6-engine` | 2026-09-03 | `24df0956` | origin | open | docs: record the report commit in its own commit table |

### Top-level branches (28)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `embed-bakeoff` | 2026-09-17 | `b7fb1215` | origin | open | Fix TB2 agent import from task workspace |
| `baseline-swe-live-lite-v4flash0731` | 2026-09-16 | `00a9b27d` | baliharneet7,fork,hbali-live,origin | open | Fix SWE-Live reverify dataset validation |
| `gt-review-inbox-d2e4a1c3` | 2026-09-16 | `256d7127` | origin | open | review packet: producer d2e4a1c3 (FTS5 native rebuild + verify) CI green |
| `gt-review-inbox-4e346402` | 2026-09-15 | `eec832ce` | origin | open | review packet: producer 4e346402 rebound to fresh build 34991635668 (b47f5bf9) |
| `gt-review-inbox-1e893f63` | 2026-09-14 | `baf73a42` | origin | open | review packet: producer 1e893f63 (inventory-divergence heal) producer build green |
| `gt-review-inbox-4f19c80a` | 2026-09-14 | `4cb9ec66` | origin | open | review packet: correct wheel identity to LF git-archive build 16012029 |
| `main` | 2026-09-14 | `3199bfbf` | fork,origin | merged | ci: register certified producer build workflow for dispatch |
| `gt-review-inbox-3f5ff8e` | 2026-09-13 | `373e0464` | origin | open | review packet: producer 3f5ff8e (LSP inventory eviction + format fix) CI green |
| `gt-review-inbox-e85b9d75` | 2026-09-12 | `6b3d281b` | origin | open | review packet: producer e85b9d75 (callsite-driven LSP enumeration) CI green |
| `gt-review-inbox-7db2f460` | 2026-09-11 | `e8a40965` | origin | open | review packet: producer 7db2f460 (re-export chains + runtime fixes) CI green |
| `research` | 2026-09-11 | `f88c3ab3` | origin | open | autoresearch: provider-free verify loop scaffold + OpenRouter contract tests |
| `smoke-acceptance-e8881a38` | 2026-09-11 | `e8881a38` | origin | open | fix(localization): enforce fire-once-per-episode at delivery admission |
| `gt-review-inbox` | 2026-09-05 | `8a5a5b87` | origin | open | inbox: HAR-83 independent unified-source artifact review |
| `gt-review-inbox-rebuild` | 2026-08-31 | `cd198b2d` | origin | open | gt.review_inbox.v1 initial packets |
| `ox-alpha-tb2-diagnostic` | 2026-08-29 | `f7ef9d8c` | origin | open | fix: record auto-push command and stderr |
| `harness` | 2026-08-25 | `937a6260` | baliharneet7,fork,origin | open | fix: declare Mini-SWE-Agent 2.4.6 package dependency |
| `alpha-ox-20task-20260821` | 2026-08-21 | `da170f0d` | hbali-live | open | DeepSWE full: swap eval_livecap_mb input for openrouter_api_key (stay at 25-input cap) |
| `arb-dispatch` | 2026-08-10 | `35cd5a3b` | origin | open | Dispatch ARB against an explicit GT ref |
| `arb-dispatch-fix` | 2026-08-10 | `7c48d5da` | origin | open | Install Hugging Face CLI for ARB workflow |
| `arb-final-workflow` | 2026-08-10 | `51f0612a` | origin | open | Pin no-HF ARB workflow to explicit GT ref |
| `arb-index-fix` | 2026-08-10 | `ea59fd9f` | origin | open | Configure GT index binary for ARB shards |
| `arb-no-hf` | 2026-08-10 | `32250ca0` | origin | open | Use pinned GitHub ARB assets without HF API |
| `arb-publish` | 2026-08-10 | `5aedd7ec` | origin | open | Add GitHub-hosted ARB retrieval evaluation |
| `arb-ref-fix` | 2026-08-10 | `3de96abe` | origin | merged | Use pinned GitHub ARB assets without HF API |
| `inline-engine` | 2026-08-10 | `f7b43b19` | origin | open | Move benchmark execution to GitHub Actions |
| `gt-integration` | 2026-08-02 | `23180fb0` | fork,origin | merged | Merge remote-tracking branch 'origin/main' into gt-integration |
| `fs023-workflow-deps` | 2026-08-01 | `66910bc2` | origin | merged | test(finalstand): isolate mocked artifact receipts |
| `miniswe-gtoff-20260731` | 2026-07-31 | `f1f2cf5f` | fork,origin | open | workflow(miniswe): per-task docker image cache (restore-before-harbor / save-after) for GT |

### Other (16)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `tb2/host-route-offline-repro` | 2026-09-16 | `dff90fd8` | origin | open | test(tb2): offline reproductions for the host-route blockers and task-class trigger sets |
| `tmp/main-producer-workflow` | 2026-09-14 | `3199bfbf` | origin | merged | ci: register certified producer build workflow for dispatch |
| `cloud/internal-harness` | 2026-09-10 | `65ab040b` | origin | open | feat(HAR-84): /gha — GitHub Actions as the compute substrate |
| `cloud/tui-city` | 2026-09-10 | `cef3a412` | origin | open | feat(HAR-84): real isometric town — towers, streets, commons |
| `linear/har-81-diagnostics` | 2026-09-08 | `db1ef026` | origin | open | docs: explain GroundTruth evolution and results |
| `inbox/har87-green-ci` | 2026-09-06 | `a18803ad` | baliharneet7,fork,origin | open | inbox: HAR-87 green CI review packet at groundtruth 193b9d93b |
| `har81/canonical-task-identity` | 2026-09-05 | `62b1254c` | origin | merged | fix: retain unique history and reference repeated tool results |
| `linear/har-81-diagnostics-rebased` | 2026-09-02 | `6f30b66a` | origin | merged | fix(HAR-81): refresh graph lazily at query boundary |
| `cursor/har6-residual-consumer` | 2026-08-30 | `592867eb` | origin | merged | feat: accept producer vta and candidate_only provenance identities |
| `rescue/stash-1` | 2026-08-30 | `caa609c9` | origin | open | On codex/har58-authority-validator: HAR-59 REV-080 delegated repair held; registry marks R |
| `rescue/stash-2` | 2026-08-30 | `4d92e97e` | origin | open | On codex/har58-authority-validator: wip: independent e2 validator hardening after HAR-57 V |
| `benchmark/deepseek-v4-flash-smoke20` | 2026-08-28 | `072d5beb` | origin | open | fix: normalize Pier task names in DeepSWE attestation |
| `final/gt-harness-benchmark-update` | 2026-08-28 | `b6ecb913` | origin | open | Fix task-local owner ranking and certify product docs |
| `workflow-register/deepswe-product-deepseek-fix` | 2026-08-28 | `ad12fcc4` | origin | merged | ci: register DeepSWE GT Harness product workflow (#15) |
| `workflow-register/deepswe-product-deepseek-fix-v2` | 2026-08-28 | `3f3e1bdc` | origin | merged | guard: add Codex benchmark dispatch hook |
| `prerelease/gt-harness-v0.9` | 2026-08-23 | `1481c292` | baliharneet7,origin | open | bind smoke credentials and assertions to mini-swe |

### Captured GitHub Actions logs (evidence only) (42)

| Branch | Last commit | Tip | Remotes | Status | Last commit subject |
|---|---|---|---|---|---|
| `gha-live-logs/csstree-shorthand-expansion-compression` | 2026-08-22 | `b5be49bc` | hbali-live | open | live #4 00:00:02 |
| `gha-live-logs/dateutil-rfc5545-timezone-interop` | 2026-08-22 | `bd5a48c7` | hbali-live | open | live #4 00:28:36 |
| `gha-live-logs/drizzle-orm-window-function-builders` | 2026-08-22 | `ca24a2d1` | hbali-live | open | live #4 00:31:05 |
| `gha-live-logs/dynamodb-toolbox-conditional-attribute-requirements` | 2026-08-22 | `850b2209` | hbali-live | open | live #4 00:31:42 |
| `gha-live-logs/dynamodb-toolbox-lazy-recursive-schemas` | 2026-08-22 | `7c470e0a` | hbali-live | open | live #4 00:33:03 |
| `gha-live-logs/effect-sse-httpapi-streaming` | 2026-08-22 | `04b02c18` | hbali-live | open | live #4 00:33:55 |
| `gha-live-logs/eicrud-keyset-pagination-cursor` | 2026-08-22 | `7061d1dc` | hbali-live | open | live #4 00:35:24 |
| `gha-live-logs/etree-xml-diff-patch` | 2026-08-22 | `b201243b` | hbali-live | open | live #3 00:34:55 |
| `gha-live-logs/expr-try-catch-errors` | 2026-08-22 | `f32885c9` | hbali-live | open | live #4 00:35:36 |
| `gha-live-logs/fastapi-deprecation-response-headers` | 2026-08-22 | `d0d01563` | hbali-live | open | live #4 00:36:50 |
| `gha-live-logs/fastapi-implicit-head-options` | 2026-08-22 | `1fd6cab4` | hbali-live | open | live #4 00:39:44 |
| `gha-live-logs/fd-deterministic-multi-key-sorting` | 2026-08-22 | `9f4d5211` | hbali-live | open | live #4 00:42:05 |
| `gha-live-logs/geo-shapeindex-serialization` | 2026-08-22 | `81184250` | hbali-live | open | live #4 00:41:47 |
| `gha-live-logs/go-critic-doc-link-checker` | 2026-08-22 | `338f7765` | hbali-live | open | live #4 00:41:55 |
| `gha-live-logs/go-genai-streamed-function-args` | 2026-08-22 | `88c73908` | hbali-live | open | live #4 00:42:55 |
| `gha-live-logs/go-git-worktree-merge-conflicts` | 2026-08-22 | `246f7b7d` | hbali-live | open | live #4 00:45:55 |
| `gha-live-logs/goreleaser-retry-publish-auditing` | 2026-08-22 | `b8029327` | hbali-live | open | live #4 00:46:21 |
| `gha-live-logs/gql-incremental-graphql-delivery` | 2026-08-22 | `a6c43fde` | hbali-live | open | live #4 00:50:17 |
| `gha-live-logs/happy-dom-abort-pending-body-reads` | 2026-08-22 | `8690066c` | hbali-live | open | live #4 00:59:32 |
| `gha-live-logs/happy-dom-deterministic-intersectionobserver` | 2026-08-22 | `645a08da` | hbali-live | open | live #4 00:59:41 |
| `gha-live-logs/helm-array-merge-strategies` | 2026-08-22 | `66b96988` | hbali-live | open | live #4 01:04:39 |
| `gha-live-logs/helm-unified-manifest-stream` | 2026-08-22 | `8ade3fcb` | hbali-live | open | live #4 01:06:12 |
| `gha-live-logs/httpx-deterministic-cookie-store` | 2026-08-22 | `d02f31c0` | hbali-live | open | live #4 01:06:40 |
| `gha-live-logs/abs-module-cache-flags` | 2026-08-21 | `0354e36e` | hbali-live | open | live #4 23:59:41 |
| `gha-live-logs/abs-stepped-slices` | 2026-08-21 | `4a7e12e4` | hbali-live | open | live #3 23:59:29 |
| `gha-live-logs/actionlint-action-pinning-lint` | 2026-08-21 | `2ef5ef9d` | hbali-live | open | live #4 23:59:45 |
| `gha-live-logs/adaptix-name-mapping-aliases` | 2026-08-21 | `6f07aa0c` | hbali-live | open | live #4 23:59:45 |
| `gha-live-logs/aiomonitor-task-snapshots-diff` | 2026-08-21 | `1975b6ae` | hbali-live | open | live #4 23:59:41 |
| `gha-live-logs/anko-default-function-arguments` | 2026-08-21 | `5065b841` | hbali-live | open | live #3 23:59:24 |
| `gha-live-logs/anko-typed-variable-bindings` | 2026-08-21 | `bceaade4` | hbali-live | open | live #4 23:59:49 |
| `gha-live-logs/arcane-drift-detection-baselines` | 2026-08-21 | `2d8ab3e3` | hbali-live | open | live #4 23:59:40 |
| `gha-live-logs/arktype-json-schema-refs-dependencies` | 2026-08-21 | `47624605` | hbali-live | open | live #4 23:59:56 |
| `gha-live-logs/awilix-async-container-initialization` | 2026-08-21 | `9708490d` | hbali-live | open | live #4 23:59:42 |
| `gha-live-logs/bandit-incremental-cache-control` | 2026-08-21 | `009f2c67` | hbali-live | open | live #4 23:59:50 |
| `gha-live-logs/bandit-interprocedural-taint-checks` | 2026-08-21 | `f62266f6` | hbali-live | open | live #4 23:59:48 |
| `gha-live-logs/bandit-structured-nosec-directives` | 2026-08-21 | `6082f7c6` | hbali-live | open | live #4 23:59:43 |
| `gha-live-logs/boa-hierarchical-evaluation-cancellation` | 2026-08-21 | `b9f8c6c6` | hbali-live | open | live #4 23:59:39 |
| `gha-live-logs/cattrs-partial-structuring-recovery` | 2026-08-21 | `f557fe7b` | hbali-live | open | live #4 23:59:41 |
| `gha-live-logs/clack-async-autocomplete-options` | 2026-08-21 | `cda18a68` | hbali-live | open | live #4 23:59:49 |
| `gha-live-logs/claude-code-by-agents-recursive-delegation` | 2026-08-21 | `46572c61` | hbali-live | open | live #4 23:59:39 |
| `gha-live-logs/cliffy-config-file-parsing` | 2026-08-21 | `ff8055fa` | hbali-live | open | live #4 23:59:45 |
| `gha-live-logs/dasel-html-document-format` | 2026-08-21 | `382e72b6` | hbali-live | open | live #4 23:59:39 |
