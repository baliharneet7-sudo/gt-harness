# Experiment: attach GT to mini-swe-agent the way GitNexus attaches

**Branch:** `experiment/gt-gitnexus-attachment`
**Created:** 2026-09-21
**Status:** specification — not yet implemented

---

## The one-sentence brief

**Change how GT reaches the agent. Change nothing about what GT computes.**

Every GT capability stays exactly as it is — the graph, the dense index, the
plan gate, contracts, predicates, provenance, the certified producer
`0becde10`, the whole engine. The only thing this experiment alters is the
*delivery mechanism*: from blind push-injection at every action boundary, to
GitNexus's attachment pattern of **agent-callable tools plus query-anchored
enrichment**.

## Why

Measured today, across 98 tasks, GT has never beaten its GT-off baseline:

| measurement | GT-on | baseline |
|---|---|---|
| TB2, all 88 | 56 | 65 |
| TB2, subset where GT actually ran | 17 | 17 |
| DeepSWE 10 (rate-limited, attestation-refused) | 3 | 4 |

On DeepSWE the three **healthiest** graphs all lost tasks the stock scaffold
solved (`awilix` 113 files parsed / 1% abstention, `csstree` 292 / 5%,
`fd-deterministic` 77 / 1%), while the task with the worst graph health won.
Losing runs received ~46% more injected context than winning ones (102 KB vs
70 KB; 146 deliveries vs 97) — confounded with rate limiting, so suggestive
rather than proven, but pointing one way.

The hypothesis this experiment tests: **GT's problem is not the graph, it is
that the graph is force-fed.** The agent cannot ask for it, cannot decline it,
and pays context window for it on every turn.

GitNexus — same scaffold, mini-swe-agent, same benchmark family — attaches
differently:

> "When the agent runs `grep` or `rg`, the observation is post-processed: the
> agent class calls `gitnexus-augment` on the search pattern and appends
> `[GitNexus]` annotations showing callers, callees, and execution flows for
> matched symbols."

Their enrichment is **demand-anchored**: it fires only where the agent has
already shown intent, about the symbol the agent itself named. Ours is
**supply-driven**: we decide what is relevant and push it regardless.

## What to build

### 1. GT tools as standalone executables

Expose the existing `src/groundtruth/mcp/tools.py` handlers as standalone
scripts in `/usr/local/bin/` inside the task container — **not** as MCP.
mini-swe-agent runs every command through `subprocess.run` in a fresh
subshell, so a script that needs `.bashrc` sourcing or inherited environment
will not work. Each script must be self-contained.

All fourteen handlers keep their current semantics:

```
gt-find-relevant   gt-brief      gt-validate   gt-trace     gt-status
gt-dead-code       gt-unused-packages          gt-hotspots  gt-orient
gt-checkpoint      gt-symbols    gt-context    gt-explain   gt-impact
```

Output must be **LLM-friendly text, not raw JSON** — GitNexus calls this out
explicitly as a token saving, and our `[GT_CONTEXT_UNIT]` / `[GT_EVIDENCE]`
block format is machine-shaped rather than model-shaped. Include next-step
hints that guide tool chaining the way theirs does
(`query → context → impact → fix`).

### 2. A warm daemon

A persistent local HTTP server inside the container holding the graph and
dense index in memory, so a tool call costs ~100ms rather than a cold engine
start. Mirror their shape:

```
agent → bash: gt-context Foo
      → curl http://127.0.0.1:<port>/tool/context   (warm path)
      → cold fallback if the daemon is not up
```

Emit a READY line on stdout and parse the port as the **last** colon-segment
so IPv6 (`[::1]:4848`) does not break it — a documented trap in their runbook.

### 3. Query-anchored enrichment, replacing blind injection

When the agent runs `grep` or `rg`, post-process the observation: call the GT
engine on **the pattern the agent searched for** and append annotations for
the matched symbols — callers, callees, execution flows, and whatever else GT
already computes that the current gateway would have delivered.

**Critical:** this replaces the existing per-action push. The current
injection sites in `gt_engine/miniswe_integration.py`
(`gateway.view.caller_contract_view`, `gateway.search.ranked_localization`,
`gateway.search.search_context`, `gateway.edit.caller_contract`) must no
longer fire unprompted. GT contributes when the agent searches, and when the
agent calls a tool. Not otherwise.

### 4. Prompt templates that teach the tools

mini-swe-agent takes a `system_template` and an `instance_template`. The
agent cannot use tools it has not been told about. Add a GT pair documenting
the tool reference and a debugging workflow, mirroring their
`system_native_augment.jinja` / `instance_native_augment.jinja`.

### 5. Usage instrumentation — the metric we have never had

We currently count `producer_invocation` and abstentions, which measure what
**GT** did. We have no measurement of what the **agent** did with it. Add:

| metric | meaning |
|---|---|
| `gt_tool_calls` | how many GT tools the agent chose to call |
| `augment_hits` | how many grep/find observations got enriched |
| `augment_hit_rate` | % of search commands that got useful enrichment |
| `gt_context_referenced` | did the agent's next command or reasoning use the delivered content |

Without the last one we cannot answer the only question that matters.

## What must not change

- The producer binary and its certification (`0becde10`, lineage, attestation)
- The graph, dense index, plan gate, contracts, predicates, provenance
- The receipt and journal schemas, except for **added** usage fields
- The frozen baselines, and the rule that GT-off is never re-run
- Any capability in `docs/benchmarks/gt_capability_surface.md`

If a capability cannot be reached through a tool call or query-anchored
enrichment, that is a finding to record — not a reason to reinstate the push.

## How it gets evaluated

Two arms, not three — the user's explicit instruction:

| arm | delivery |
|---|---|
| **A** | current GT (blind push at every action boundary) |
| **B** | GT attached GitNexus-style (tools + query-anchored enrichment) |

Both keep every GT capability. Compare on the **DeepSWE matched 10-task
control** (frozen GT-off: 4/10, sha256
`707d7eb7c36d1ea147b6b337eb855022acd74d6ac33ce7c39134f3590a6fac63`).

**Run serially or at ≤3 concurrency.** Run 35630893781 was refused by our own
attestation over 44 `provider_failed_calls` caused by rate limiting at 9-way
parallelism, and the tasks with the most failures were the ones that lost.

Consider `temperature: 0` for evaluation. GitNexus uses it; we use 1.0, and it
is why `write-compressor`, `winning-avg-corewars` and `regex-chess` each
flipped between our own runs. If temperature changes, the frozen baseline is
no longer matched — so either re-derive a matched control or keep 1.0 and
accept the noise. **Do not quietly change it and compare against the old
baseline.**

## Reference points

- GitNexus eval harness: `https://github.com/abhigyanpatwari/GitNexus/tree/main/eval`
- Their modes: `baseline` / `native` / `native_augment`, mini-swe-agent, SWE-bench Lite
- Their metrics: Patch Rate, Resolve Rate, Total Cost, Avg Cost/Instance, API Calls,
  GN Tool Calls, Augment Hits, Augment Hit Rate
- Our tool handlers: `src/groundtruth/mcp/tools.py`
- Our current injection seam: `gt_engine/miniswe_integration.py`
- Our agent adapter: `eval/miniswe_agent.py`, `eval/pier_gt_harness_adapter.py`
- Our runner: `scripts/miniswe_gt_run.py`
- Campaign record: `docs/benchmarks/gt_hardening_rsi_2026-09-18.md` §18–19

## The result that would settle it

If arm B beats arm A while computing the same things, the defect was never the
graph — it was that we forced it on the agent. That is a finding worth the
whole campaign, and it is reachable for roughly $3 of provider spend.
