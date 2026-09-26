# GT attached-delivery campaign — progress record

Branch `integ/gt-attached` (from `canonical/gt-har90` @ b005a74e). Plan: `C:\Users\Lenovo\.claude\plans\i-want-you-to-witty-frost.md`.
Links: HAR-93 (delivery experiment), HAR-90 (canonical + MINISWE_INTEGRATION_DESIGN phases 1–3).

Legend: [ ] todo · [~] in progress · [x] done · [!] blocked / needs the user

## W2 — attached delivery (GitNexus `native_augment` pattern on canonical GT)
- [x] `gt_delivery_mode=push|attached` — declared CliFlag, consumed by `treatment_flags` (attached ⇒ SHADOW session; refuses with GT-off or a conflicting `--gt-mode`)
- [x] tools: 22 `gt-*` commands (core 8 in the prompt, rest via `gt-help`); every one of the 21 features mapped (`FEATURE_SURFACES`) and exercised on a real producer graph (`tests/canonical/test_attached_feature_coverage.py`). Initially 12 over the certified facades (`gt_engine/tool_server.py`), model-shaped renderer (`gt_engine/tool_render.py`), tier shown, no hashes, 6 KB cap, exit 0/1/2
- [x] warm server in the runner process (shares EngineState ⇒ per-edit freshness; refresh-before-query); stdlib wrappers with the URL baked in (credential-isolated env safe). No cold CLI fallback: the server lives exactly as long as the agent
- [x] grep/rg/ag/git-grep augmentation on the SAME observation (`gt_engine/grep_augment.py`), anchored to the agent's own identifiers, 2 KB cap, silent on no answer, deterministic
- [x] attached gate: session SHADOW (no pushed units, steers, catalog), `typed_actions` off (bash is the one tool surface), persistent plan off, submit gate + churn abort bypassed and journaled
- [x] prompt: stock mini-swe template + one short tool-reference section (`attached_system_section`)
- [x] report fields: `gt_delivery` (tool calls/by name, augment calls/hits/rate/bytes, `gt_bytes_delivered`, `gt_context_referenced` + method), `effective_step_limit`, `requested_step_limit`; push arm reports its delivered bytes too
- [x] dropped `gt_bytes_would_push`: push producers do not run in SHADOW, and running them only to count bytes would add per-action cost; the A/B compares arms directly
- [x] pay-per-intent compute: no per-action graph refresh / transaction-boundary amend in attached mode; the first tool/augment read amends (tested edit -> query)
- [x] graph failure in attached mode -> `attached_treatment_invalid`, agent keeps running (no startup abort)
- [x] `gt-calls`: per-call resolution from CANDIDATE_TARGET/SELECTED_TARGET edges (F5/F6/F7), cross-language candidates flagged
- [x] tests: `tests/test_gt_attached_unit.py` (40) + `tests/canonical/test_attached_delivery.py` (5, real gt-index graph)

## W1 — benchmark path (model-agnostic)
- [x] model/route/effort are launch inputs: hardcoded model tables removed from runner + preflight; one structural validator `gt_harness/provider_routing.py`; gateway runs still fail closed without a stated route
- [x] `GT_REASONING_EFFORT` (validated) replaces the muse-only special case; `temperature` is a declared launch knob
- [x] `scripts/resolve_baseline.py` — per-(model, effort) comparator from the public leaderboard trials; reproduces deepseek-v4-flash/max pass@1 0.5332 exactly
- [x] `config/deepswe_task_catalog_v1.json` — all 113 tasks, images pinned by registry digest, 20 bundle rows cross-checked byte-for-byte; task set == leaderboard's 113
- [x] `deepswe_gt_delivery_ab.yml` — interleaved push/attached × n_runs, catalog cohort, rendered route, aggregate with step-limit proof (in progress)
- [!] TB2 central `GT_SOURCE_SHA 921bec20` is an import-provenance pin (`config/tb2_gt_import_manifest.json`, asserted by 2 tests), not a stray label — re-deriving the import manifest needs a decision; deferred (TB2 secondary)
- [x] GitHub accepts up to 25 `workflow_dispatch` inputs since 2025-12-04 (changelog) — the A/B workflow's 14 are fine

## W3 — hardening
- [!] re-certify producer 9cf513af (Route-B CI run) — needs the user
- [x] stale canonical docs: `TYPED_SURFACE.md` (subprocess.run, revision identity, route_map middleware) + registry limitation string; [ ] re-render `HAR90_CANONICAL_SECTION.md`
- [~] real-repo provider-free smoke (`scripts/smoke_attached_real_repos.py`; adaptix, aiomonitor, awilix, abs, fd, csstree)
- [x] `gt-query` path (`hybrid_rank` facade) already fuses available sources with RRF (dense absence = omission, not all-or-nothing); the all-or-nothing defect is only in the push localization lane
- [x] efficiency: wheel `processes._stable_id_to_nodes` quadratic CAST join (40 s/call on adaptix) → output-identical shim 0.94 s, attached arm only; per-action working-tree snapshot cache

## W4/W5 — evidence & graduation (no paid run without the user)
- [ ] pre-registration doc
- [ ] provider-free acceptance on a clean checkout
- [ ] canary 1 task/arm → 10×2×4 → 113×4

## Findings recorded during implementation
- Certified wheel defect: `ON CAST(native_id AS INTEGER)` joins defeat indexes (processes.py:218, mcp/_graph_db.py:145, resolve.py:498/597) — `symbol_context` cost 50-72 s on a 489-file repo. Likely contributor to past push-arm timeouts; worth auditing old journals.
- Canonical bundle closure omitted two shipped modules (`taint_dataflow.py`, `shape_check_guard.py`) — fixed.
- F6: candidates exist as graph edges; `analysis.callable_values` reads an empty table (harness bug).
- `gt-tests` (covering selector) misses a caller-reachable test that `gt-impact` shows.
- Every past DeepSeek comparison was effort-mismatched: the only leaderboard deepseek-v4-flash row ran at `max`; our harness sent none.
- Akon's GitNexus "bare" arm (37.0%, gpt-5.6-terra med) matches the public leaderboard (0.3496) — its 68.4% is against a real stock level.
- Canonical `submitted_unverified` exits 0; the embed-bakeoff "exit 5 with a patch" is specific to its `gt_central_agent`.
- The 20-task product bundle cannot run a matched control or the full 113 — hence the catalog.

## Log
- 2026-09-26: committed a609ee28 (W2 core, routing, resolver, catalog, A/B workflow); extended catalog + lazy freshness + gt-calls; real-repo smoke running.
- 2026-09-26: worktree `D:\gt-attached` created; audit + plan approved; W2 core, W1 routing/resolver/catalog landed locally.
