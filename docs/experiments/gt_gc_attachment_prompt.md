# Experiment: re-attach GT to mini-swe-agent using the GC attachment pattern

**Branch:** `experiment/gt-gc-attachment`
**Created:** 2026-09-21
**Status:** specification — not yet implemented
**Reference implementation:** GC (external comparator; same scaffold, same benchmark family)

---

## 1. The brief, in one sentence

**Change how GT reaches the agent. Change nothing about what GT computes.**

Every GT capability stays exactly as it is — the graph, the dense index, the
plan gate, contracts, predicates, provenance, the certified producer
`0becde10`, the whole engine. The only thing this experiment alters is the
**delivery mechanism**: from blind push-injection at every action boundary, to
**agent-callable tools plus query-anchored enrichment**.

## 2. Why — the evidence

Across 98 measured tasks GT has never beaten its GT-off baseline:

| measurement | GT-on | baseline |
|---|---|---|
| TB2, all 88 | 56 | 65 |
| TB2, subset where GT actually ran | 17 | 17 |
| DeepSWE 10 (rate-limited, attestation-refused) | 3 | 4 |

The ceiling we have demonstrated is a tie. Two observations point away from
the graph and toward the delivery:

**(a) The healthiest graphs lost.** On DeepSWE, the three cleanest graphs each
lost a task the stock scaffold solved, and the worst-health task won:

| task | files parsed | abstention | outcome |
|---|---|---|---|
| `fd-deterministic-multi-key-sorting` | 77 | 1% | lost (control solved) |
| `awilix-async-container-initialization` | 113 | 1% | lost (control solved) |
| `csstree-shorthand-expansion-compression` | 292 | 5% | lost (control solved) |
| `aiomonitor-task-snapshots-diff` | 43 | **23%** | **won** |

**(b) Losing runs carried more injected context.**

| | n | mean pushed | mean deliveries | mean provider failures |
|---|---|---|---|---|
| won | 2 | 70 KB | 97 | 2.0 |
| lost | 7 | 102 KB | 146 | 5.7 |

This is **confounded** with rate limiting (more deliveries → more calls → more
throttling) and n is tiny, so it is a lead, not a result. It is the only lead
we have that explains both benchmarks at once.

**Hypothesis: GT's problem is not the graph, it is that the graph is
force-fed.** The agent cannot ask for it, cannot decline it, and pays context
window for it every turn.

**What GC does differently.** GC's enrichment is *demand-anchored*: it fires
when the agent runs a search, and it enriches the symbol the agent itself
named. Ours is *supply-driven*: we decide relevance and push regardless. GC
also exposes its capabilities as tools the agent may call, and measures how
often the agent actually calls them.

## 3. Scope

### 3.1 What changes

Only the seam between the GT engine and the agent loop.

### 3.2 What must not change

- The producer binary and its certification (`0becde10`, Route-B lineage,
  attestation digest)
- The graph, dense index, plan gate, contracts, predicates, provenance
- Receipt and journal schemas — **except for added fields** (§6)
- The frozen baselines, and the standing rule that GT-off is never re-run
- Any capability listed in `docs/benchmarks/gt_capability_surface.md`

> **Guardrail.** If a capability cannot be reached through a tool call or
> query-anchored enrichment, **record that as a finding**. It is not a licence
> to reinstate the push for that capability. A hybrid that quietly keeps the
> old path for "the important ones" tests nothing.

## 4. Implementation

### 4.1 Component A — GT tools as standalone executables

**Goal:** the agent can invoke any GT capability as an ordinary shell command.

**Not MCP.** mini-swe-agent executes every command through `subprocess.run`
in a fresh subshell: no `.bashrc`, no inherited environment, no session state.
Each tool must be a self-contained executable in `/usr/local/bin/`.

Source the behaviour from the existing handlers in
`src/groundtruth/mcp/tools.py` — do not reimplement them:

| script | handler |
|---|---|
| `gt-find-relevant` | `handle_find_relevant` |
| `gt-brief` | `handle_brief` |
| `gt-validate` | `handle_validate` |
| `gt-trace` | `handle_trace` |
| `gt-status` | `handle_status` |
| `gt-dead-code` | `handle_dead_code` |
| `gt-unused-packages` | `handle_unused_packages` |
| `gt-hotspots` | `handle_hotspots` |
| `gt-orient` | `handle_orient` |
| `gt-checkpoint` | `handle_checkpoint` |
| `gt-symbols` | `handle_symbols` |
| `gt-context` | `handle_context` |
| `gt-explain` | `handle_explain` |
| `gt-impact` | `handle_impact` |

**Output contract — this is not cosmetic.** Current GT output is
machine-shaped:

```
[GT_CONTEXT_UNIT] {"action_index":25,"historical":false,"source_revision":"f75c2da0...","supersedes":["08d7b79a..."],"unit_id":"bc1f93b5..."}
[GT_EVIDENCE:cochange_partner]
util/util.go: co-change prior revision=f75c2da0... partner=evaluator/functions.go count=11 support=11 confidence=0.73333333 commits_file=15 commits_partner=98 window=57ca93aa..cb1b3b67 provenance=
```

Roughly half those bytes are hashes and revision identifiers the model cannot
act on, charged to the context window on every delivery. Tool output must be:

- **model-shaped prose or compact tables**, not JSON and not hash-laden
- **bounded** — a hard per-call byte cap, configurable, with truncation stated
- **chained** — end with a next-step hint (`query → context → impact → fix`)
- provenance kept in the **journal**, not in the model's context

**Exit codes:** `0` answer produced, `1` no answer (graph unavailable, symbol
unknown) with a one-line reason on stdout, `2` usage error. Never a traceback.

### 4.2 Component B — warm daemon

**Goal:** a tool call costs ~100ms, not a cold engine start.

A persistent local HTTP server inside the task container holding the graph and
dense index in memory:

```
agent → bash: gt-context Foo
      → curl http://127.0.0.1:<port>/tool/context?symbol=Foo   (warm path)
      → cold in-process fallback if the daemon is not up
```

Requirements:

- Bind `127.0.0.1` by default; allow `0.0.0.0` for cross-container use
- Emit a READY line on stdout: `GT_TOOL_SERVER_READY:127.0.0.1:<port>`
- **Parse the port as the last colon-segment** (`split(':').pop()`) — the
  bracketed IPv6 form `[::1]:4848` breaks naive `split(':')[1]`
- Idle timeout, configurable, default off
- `/health` endpoint
- The daemon must never be required: every tool works cold, only slower

### 4.3 Component C — query-anchored enrichment (replaces the push)

**Goal:** GT contributes where the agent has shown intent.

When the agent runs `grep` or `rg`, post-process the observation: call the GT
engine on **the pattern the agent searched for**, and append annotations for
matched symbols — callers, callees, execution flows, and whatever else GT
already computes.

**This replaces the existing per-action push.** These sites in
`gt_engine/miniswe_integration.py` must no longer fire unprompted:

```
gateway.view.caller_contract_view
gateway.search.ranked_localization
gateway.search.search_context
gateway.edit.caller_contract
```

Rules:

- Enrichment only on search-shaped commands (`grep`, `rg`, and document which
  others qualify)
- Anchored to the agent's own pattern — never a symbol GT chose independently
- Bounded: cap annotations per observation, cap bytes, state truncation
- Silent when GT has nothing: **no annotation is better than a null one**
- Deterministic given (pattern, revision), so runs are reproducible

### 4.4 Component D — prompt templates

The agent cannot use tools it has not been told about. mini-swe-agent takes a
`system_template` and an `instance_template`; add a GT pair:

- **system:** tool reference — one line per tool, argument shape, when it helps
- **instance:** a debugging workflow showing tool chaining, and the fact that
  search output may carry `[GT]` annotations

Keep both **short**. Every token here is charged on every call, and a bloated
system prompt is the same disease as a bloated injection.

### 4.5 Component E — configuration

One switch selecting the delivery mode, defaulting to current behaviour so
nothing changes until the experiment runs:

| mode | delivery |
|---|---|
| `push` | current — blind injection at every action boundary (**default**) |
| `attached` | tools + query-anchored enrichment |

The engine, producer and capability set are identical in both.

## 5. Interfaces to respect

| file | role | change |
|---|---|---|
| `src/groundtruth/mcp/tools.py` | the 14 handlers | **reuse, do not fork** |
| `gt_engine/miniswe_integration.py` | current injection seam | gate the four push sites behind `mode == "push"` |
| `eval/miniswe_agent.py` | Harbor/Pier agent adapter | install tool scripts; hook observation post-processing |
| `eval/pier_gt_harness_adapter.py` | Pier boundary | pass the mode through |
| `scripts/miniswe_gt_run.py` | runner, builds the agent | accept and record the mode |
| `gt_engine/dense_runtime.py` | ONNX encoder | daemon should hold one session, not per-call |

## 6. Instrumentation — the measurement we have never had

We count `producer_invocation` and abstentions. Those measure what **GT** did.
We have never measured what the **agent** did with it. Add to the run receipt:

| field | meaning |
|---|---|
| `gt_tool_calls` | how many GT tools the agent chose to call |
| `gt_tool_calls_by_name` | per-tool breakdown |
| `augment_hits` | search observations that received annotations |
| `augment_hit_rate` | % of search commands that got useful enrichment |
| `gt_bytes_delivered` | total bytes GT put into the model's context |
| `gt_context_referenced` | did the agent's next command or message use the delivered content |

`gt_context_referenced` is the important one and the hardest. A defensible
first version: did any symbol, path or identifier unique to the delivery
appear in the agent's next command or message. Record the method used so the
number is interpretable; a crude measure that is documented beats none.

These fields are **additive**. Do not alter existing schema fields.

## 7. Test plan

Offline, no provider spend:

1. **Tool scripts** — each runs under `subprocess.run` with an empty
   environment and no shell init; asserts on exit codes and byte caps.
2. **Daemon** — READY parsing including `[::1]`; `/health`; cold fallback when
   the daemon is absent; one ONNX session, not one per call.
3. **Enrichment** — fires on `grep`/`rg`, not on unrelated commands; anchors to
   the agent's pattern; silent when GT has nothing; respects caps; deterministic
   for a fixed (pattern, revision).
4. **Mode gate** — in `attached`, the four push sites emit nothing; in `push`,
   behaviour is byte-identical to today. Pin this; it is what keeps the control
   arm honest.
5. **Capability coverage** — every entry in
   `docs/benchmarks/gt_capability_surface.md` is reachable in `attached`, or is
   listed as an explicit, recorded gap.
6. **Receipts** — new fields present and typed; existing fields unchanged.

## 8. Evaluation protocol

**Two arms**, as instructed — not three:

| arm | delivery |
|---|---|
| **A** | `push` — current GT |
| **B** | `attached` — tools + query-anchored enrichment |

Both keep every GT capability.

- **Cohort:** DeepSWE matched 10-task control. Frozen GT-off comparator is
  **4/10**, sha256
  `707d7eb7c36d1ea147b6b337eb855022acd74d6ac33ce7c39134f3590a6fac63`.
- **Concurrency ≤3, or serial.** Run 35630893781 was refused by our own
  attestation over 44 `provider_failed_calls` from rate limiting at 9-way
  parallelism, and the tasks with the most failures were the ones that lost.
- **Temperature:** GC evaluates at 0; we run 1.0. Temperature 0 would cut the
  variance that flipped `write-compressor`, `winning-avg-corewars` and
  `regex-chess` between our own runs — but it **unmatches the frozen
  baseline**. Either keep 1.0 and accept the noise, or re-derive a matched
  control. **Do not change it quietly and compare against the old baseline.**
- **Report per task:** reward, control's reward, graph health, `gt_tool_calls`,
  `augment_hit_rate`, `gt_bytes_delivered`, `provider_failed_calls`.
- The attestation must **pass**. A refused run is not a result.

## 9. Risks

| risk | mitigation |
|---|---|
| The agent ignores the tools entirely | `gt_tool_calls` makes it visible immediately; a zero is itself the finding |
| Prompt templates bloat the context | Cap and measure; bloated prompt is the same disease as bloated injection |
| Enrichment silently reinstates the push | Test 4 pins the four push sites silent in `attached` |
| A capability is unreachable without push | Record it; do not special-case it back |
| n=10 is underpowered | True. This measures direction, not effect size. Say so in any write-up |
| Rate limiting contaminates again | ≤3 concurrency, and check `provider_failed_calls` before reading any score |

## 10. Acceptance criteria

1. Both modes run end-to-end on the 10-task control with the attestation passing.
2. In `attached`, the four push sites emit nothing — proven by test, not inspection.
3. Every capability is reachable, or its gap is recorded.
4. Receipts carry the §6 fields for both arms.
5. A per-task table comparing A, B and the frozen control, with graph health and
   usage metrics beside every score.

## 11. The result that would settle it

If arm B beats arm A while computing the same things, the defect was never the
graph — it was that we forced it on the agent. That is a finding worth the
whole campaign, and it is reachable for roughly $3 of provider spend.

If arm B does **not** beat arm A, the delivery hypothesis is dead and the next
question is whether the graph's content helps at all — a different and harder
experiment, but one we would then be entitled to ask.

## 12. Campaign record

`docs/benchmarks/gt_hardening_rsi_2026-09-18.md` §18–19 hold the TB2 and
DeepSWE results this experiment responds to.
