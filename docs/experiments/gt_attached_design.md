# How GT attaches to mini-swe-agent — design rationale

Status: implemented on `integ/gt-attached` (HAR-93 × HAR-90 design phases 1–3). Progress: `gt_attached_progress.md`.

This is not a copy of GitNexus. GitNexus's eval adapter (`eval/agents/gitnexus_agent.py`, `abhigyanpatwari/GitNexus@0261982d`) is evidence about *where* repository intelligence should meet the agent loop. GT keeps its own engine, certification and freshness. The attachment is how every GT feature reaches mini-swe without making the agent worse on tasks it would have solved anyway.

## 1. Why GT regressed and GitNexus did not

Every documented GT loss mechanism is a place where GT **owned the agent's control flow or context**, rather than a wrong graph fact:

| GT regression (measured) | Mechanism | GitNexus equivalent |
|---|---|---|
| Plan gate refused every submission, 0/4 vs 5/5 (`640cfb42`) | GT blocked a native action | never blocks |
| Churn and startup aborts killed runs; −5 TB2 tasks lost before grading | GT ended the run | a setup failure leaves the stock agent running |
| Graph rebuilt 194×/task, OOM on 2 GB containers | per-action engine work, whether or not the agent used it | index once; per-action cost only on searches |
| Losing runs carried +46% injected bytes (102 KB vs 70 KB) | host-chosen context pushed onto every request and persisted in history | context only beside a search the agent chose |
| Facts appended to the *next* request's last message | detached from the observation that triggered them | appended to the *same* observation |
| Tier dropped from automatic caller text | confident-looking wrong edges | no tiers either — GT should do better here |

The public numbers are consistent with this. Akon's "bare" arm (37.0%, gpt-5.6-terra medium) matches the DeepSWE leaderboard's stock mini-swe figure (0.3496), so GitNexus's 68.4% is measured against a real baseline. And it used *fewer* steps (44.9 vs 50.3). The gain is efficiency that turns into solves: graph facts arrive next to a search and replace follow-up greps and reads.

## 2. Principles (what we took, and why)

1. **Additive only — the baseline trajectory is always reachable.** GT never blocks, aborts or rewrites an action. Attached mode bypasses the submit gate and churn abort (both journaled as shadow signals). A graph failure marks the row treatment-invalid and the agent continues as stock mini-swe. *Worst case = baseline plus a few bytes.*
2. **Pay per intent — for context and for compute.** Bytes appear only when the agent searches (≤2 KB, anchored to the identifiers *it* typed) or calls a `gt-*` tool (≤6 KB). The prompt lists only the core tools (<2 KB); `gt-help` reveals the rest on demand. Graph refresh and amend happen only when a tool or augmentation reads the graph, never on every action.
3. **Same-observation placement.** The `[GT]` block is appended to the grep output that caused it, so the model reads callers, callees and flows beside the matches it asked for.
4. **Epistemic honesty in the text the model reads.** Trust tier is shown when a fact is not CERTIFIED, flows marked "lower bound, unwitnessed" say so, and every answer ends "name-level: verify by reading the code". A no-answer names its reason. No hashes, no directives.
5. **Measure use, not just delivery.** Every run reports tool calls by name, augmentation hit rate, bytes delivered and `gt_context_referenced`: did the delivery's distinct paths or symbols appear in the next 3 actions.

## 3. Where GT deliberately differs from GitNexus

| GitNexus | GT attached | Why |
|---|---|---|
| Index built once at task start; stale after edits | EngineState freshness: an edit marks the graph stale and the next query amends first (lazy) | After a refactor, stale callers are worse than none |
| Setup failure silently continues as "treatment" | Agent continues, but the row is marked `treatment_valid=false` | Fail-open for the agent, fail-closed for measurement |
| Cache keyed by repo + commit | Certified producer/wheel digests, revision-bound answers | Reproducibility |
| BM25-only augmentation (`skip_embeddings`) | Augmentation uses certified `symbol_context`; `gt-query` uses hybrid lexical + dense RRF | Keep GT's retrieval advantage available on demand |
| Tools answer from a separate eval server + CLI fallback | Server runs *inside* the runner process and shares the live engine | One freshness authority; no second index that could disagree |
| Mode changes both prompt and workflow instructions | Stock template + one short tool section | A smaller prompt confound in the A/B |

## 4. How each of the 21 features reaches the agent

Source of truth: `gt_engine/attached_delivery.FEATURE_SURFACES`. Pinned by `tests/canonical/test_attached_feature_coverage.py`, which runs every surface against a real producer graph.

| Feature | Attached surface |
|---|---|
| F1 parsing, F21 freshness | substrate of every answer; F21 lazy amend is tested edit → query |
| F2 definitions | `gt-def`, `gt-context`, augmentation |
| F3 references | `gt-refs` |
| F4 callers/callees | `gt-callers`, `gt-context`, `gt-impact`, augmentation |
| F5 call resolution, F6 callable values | `gt-calls` (each call in a function → target / ambiguous / external) |
| F7 receiver/inheritance | `gt-shape` |
| F8 framework/DI/middleware, F18 routes | `gt-routes`, `gt-api` |
| F9 processes | `gt-flows`, augmentation |
| F10 communities | `gt-module` |
| F11 hybrid retrieval | `gt-query` |
| F12 symbol context | `gt-context`, augmentation |
| F13 patch impact / co-change | `gt-changes` (impact of the agent's own edits), `gt-impact`, `gt-cochange` |
| F14–F17 CFG / reaching defs / control dep / slice | `gt-slice` |
| F19 taint | `gt-taint` |
| F20 test feedback / recovery | `gt-verify`, `gt-tests`, `gt-check`, `gt-failures` |

## 5. Known gaps (surfaced, not hidden)

- **F6 (harness bug, worked around for the agent):** the certified producer (1e83ea68) records call candidates as `HAS_CALLSITE` -> `CANDIDATE_TARGET`/`SELECTED_TARGET` edges (40 on the polyglot fixture), but the `resolution_candidates` table is empty, and the host facade `analysis.callable_values` inner-joins that table - it can never answer on a real graph. `gt-calls` reads the edges: each call in a function with its selected target or viable candidate set, cross-language candidates flagged (TS `greet` -> Java `OrderService.greet`; producer 9cf513af scopes those by language family). The facade itself should move onto the edges.
- **F20:** `gt-tests pyapp/helpers.py` finds no covering test, although `gt-impact apply_tax` shows `test_total` calling it. The covering-test selector's reachability is narrower than the caller graph — worth fixing before relying on it.
- **Python analysis depth:** there is no persisted Python CFG, so the analysis facades abstain on Python, but `gt-slice` works through the runtime `ast` CFG. Module-level and class-body calls produce no edges.
- **`gt_bytes_would_push`:** not measurable in SHADOW, because the push producers do not run there. Adding them back would add per-action cost; the A/B compares arms directly instead.
- **Untested at scale:** nothing here has run on a real DeepSWE repository yet. The next step is W3.2: a provider-free smoke on 6 repos.

## 6. Efficiency on real repositories (measured)

First real-repo smoke (adaptix@a691069, 489 files, 283 MB graph, local gt-index build):

| call | before | cause | after |
|---|---|---|---|
| `gt-context` / `gt-flows` / `gt-calls` / every grep augmentation | **50–72 s** | wheel `processes._stable_id_to_nodes` joins `resolution_symbols` with `ON CAST(rs.native_id AS INTEGER) = n.id`; the cast defeats every index, so SQLite nested-scans ~99k nodes × resolution symbols on every `symbol_context` call (40 s self-time) | `gt_engine/wheel_perf.py`: same mapping via two linear scans + dict join — **0.94 s vs 40.12 s, output dict-identical (98,769 entries)**; pinned equal on the real producer graph by `tests/canonical/test_wheel_perf.py` |
| every typed query | +~450 ms | `build_action_request` content-hashes the whole working tree per call | snapshot computed once per agent action (`miniswe_typed_actions.snapshot_scope`), the same granularity at which the engine observes edits |

The shim is installed **only** in the attached arm, so the push arm — the A/B control — runs the unmodified wheel. The defect is in the certified wheel and should be fixed there. The same cast-join pattern also appears in `groundtruth/mcp/endpoints/_graph_db.py:145` and `groundtruth/resolve.py:498,597`.

Consequence for past runs: wherever GT's push lanes called `symbol_context`/process detection on a real repository, this cost fell on the agent's wall clock. That is a candidate contributor to the TB2/DeepSWE timeouts and is worth checking in past journals.
| repeat `symbol_context` / flows on the same graph | ~2 s each | process detection recomputed per call over an immutable published graph | memoized per graph file identity (path, size, mtime); an amend publishes a new file, so the cache can never serve a stale graph; cached == uncached pinned on the real graph |

**Typed byte-bound defect (surfaced by adaptix):** for a heavily called symbol (`loader`, 98 callers), `callers` at depth ≥ 2 exceeds `QUERY_RESULT_MAX_BYTES`, and the bound *drops the whole answer* (`answer: null`, `query_result_unbounded_payload`) instead of truncating its rows. So the symbols where callers matter most read as "no callers". `gt-callers` and `gt-impact` now fall back to depth 1 and say so (`depth_reduced_to_1`). The bound itself (`gt_engine/typed_output_bounds.py`) should truncate rows, not null the answer; that affects the typed tool on the push arm too.
