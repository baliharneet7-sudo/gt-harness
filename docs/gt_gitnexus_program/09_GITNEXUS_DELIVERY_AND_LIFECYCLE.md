# GitNexus delivery and index-lifecycle audit

## Audit identity

- **Official repository:** [abhigyanpatwari/GitNexus](https://github.com/abhigyanpatwari/GitNexus)
- **Pinned revision:** [`fc885a4bf3edddf9214df633d8d1c0767ef58af9`](https://github.com/abhigyanpatwari/GitNexus/commit/fc885a4bf3edddf9214df633d8d1c0767ef58af9)
- **Audit date:** 2026-08-18

Evidence labels:

- **SOURCE-PROVEN:** directly supported by pinned source.
- **INFERENCE:** plausible consequence not isolated experimentally.
- **UNKNOWN:** public evidence is insufficient.

## Executive verdict

GitNexus has two different delivery architectures:

1. explicit MCP/CLI tools that require a model-selected intelligence action;
2. automatic hooks/adapters that attach graph context to an ordinary search or read action.

The automatic path is the important efficiency lesson. It can put callers, callees, and process information beside an action the model already chose, avoiding a separate decision to invoke a graph tool.

GitNexus does not provide a model for GT's current delivery-integrity failures. Its automatic delivery has no claim IDs, provider-view hash, changed-message index, first-eligible timing proof, evidence-state fingerprint, or revision-current certificate. Some failure and contention paths are deliberately silent.

The index builder itself contains useful lifecycle machinery—single-writer locking, content hashes, mismatch-triggered rebuilds, dirty markers, sidecar recovery, atomic publication, and metadata ordering. The live product and public benchmark lifecycle are weaker: ordinary source edits do not automatically refresh the index before the next provider request, and the public evaluation adapter indexes only at task start.

Confidence: **high**.

## 1. Delivery-channel map

| Channel | Trigger | Provider-visible result | Extra model/tool decision? | Source |
|---|---|---|---:|---|
| MCP tools | model selects `query`, `context`, `impact`, etc. | structured relational response | Yes | [`mcp/tools.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/tools.ts) |
| Claude Code `PreToolUse` | `Grep`, `Glob`, search-bearing `Bash` | `additionalContext` before tool execution | No separate graph-tool decision | [`hooks.json`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-claude-plugin/hooks/hooks.json), [`gitnexus-hook.js`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-claude-plugin/hooks/gitnexus-hook.js) |
| Claude Code `PostToolUse` | successful git commit/merge/rebase/cherry-pick/pull | stale-index warning and analyze command | No automatic refresh | same hook source |
| Cursor `postToolUse` | `Shell`, `Read`, `Grep` | `additional_context` beside completed result | No separate graph-tool decision | [`hooks.json`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-cursor-integration/hooks/hooks.json), [`gitnexus-hook.cjs`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus-cursor-integration/hooks/gitnexus-hook.cjs) |
| Public eval `native_augment` | grep-like model action | graph block appended to same observation | No separate model decision; host command executes | [`eval/agents/gitnexus_agent.py`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/eval/agents/gitnexus_agent.py) |

## 2. Explicit MCP delivery

The MCP surface exposes repository discovery, search, custom Cypher, symbol context, change detection, checks, rename, impact, PDG explanation/query, route/tool maps, API shape/impact, group operations, and trace.

Primary declarations: [`mcp/tools.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/tools.ts).

Primary implementations: [`mcp/local/local-backend.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/mcp/local/local-backend.ts).

Advantages:

- rich, precomposed structured answers;
- explicit symbol disambiguation;
- caller/callee/process/impact composition;
- optional lower-bound and partial warnings;
- flexible ad hoc questions.

Efficiency cost:

- the model must know the tool exists;
- the model must choose to call it;
- the call consumes an action and usually another provider reasoning boundary;
- the model may still grep/read afterward.

**INFERENCE:** explicit MCP is most valuable for novel graph questions that cannot be safely inferred from a normal action. It is a weaker default for routine localization where the host already knows what the model searched or read.

## 3. Automatic augmentation engine

[`augment(pattern, cwd)`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/augmentation/engine.ts) implements the compact automatic response.

Source-proven flow:

```text
search pattern
  -> BM25/FTS only, no embedding call
  -> top matching files
  -> symbols in those files
  -> parallel callers, callees, process membership, and cohesion lookups
  -> cohesion ranking
  -> compact [GitNexus] block
```

The output can include:

- source symbol and location;
- `Called by` names;
- `Calls` names;
- `Flows` process labels.

Design strengths:

- no provider or embedding call for the augmentation lookup;
- graph enrichments run in parallel;
- the result is relational rather than another file dump;
- it can accompany an already-selected search.

Integrity weaknesses:

- any top-level error returns an empty string;
- several subqueries degrade to empty maps;
- no provider-visible confidence or epistemic status;
- no process-truncation or relation-window status;
- no graph/source revision in the block;
- no evidence claim identity;
- no proof that the provider received the exact block.

Operationally this is graceful degradation. Analytically it is insufficient for a treatment release gate.

## 4. Claude Code hook

The Claude plugin configures:

- `PreToolUse` for `Grep|Glob|Bash` with a ten-second hook timeout;
- `PostToolUse` for `Bash` with a ten-second hook timeout.

### 4.1 PreToolUse behavior

`handlePreToolUse()`:

1. resolves the repository, including linked-worktree fallback;
2. extracts a pattern from Grep, Glob, or `rg`/`grep` Bash input;
3. acquires a bounded per-repository hook slot;
4. runs `gitnexus augment -- <pattern>` when the database is available;
5. emits JSON `hookSpecificOutput.additionalContext` when nonempty.

If every hook slot is held, the normal path is silent unless `GITNEXUS_DEBUG` is enabled.

If another GitNexus process owns the LadybugDB write lock, the hook may emit a throttled hint asking the model to use the MCP `query` tool. That fallback can reintroduce an extra model/tool roundtrip.

### 4.2 PostToolUse behavior

`handlePostToolUse()` runs only after successful Bash commands matching:

- `git commit`;
- `git merge`;
- `git rebase`;
- `git cherry-pick`;
- `git pull`.

It compares `git rev-parse HEAD` with the index metadata's last commit. If they differ, it tells the agent to run an analyze command.

It deliberately does not reindex synchronously because the source notes that a long blocking analyze risks timeout and database corruption.

### 4.3 Lifecycle implication

The hook detects commit-level staleness. It does not make the index revision-current after every ordinary edit.

This is materially weaker than GT's intended rule:

```text
source edit
  -> graph unavailable
  -> refresh/rebuild completes
  -> only then may the next provider frame use graph evidence
```

## 5. Cursor hook

The Cursor integration runs after `Shell`, `Read`, and `Grep`.

It derives a pattern from:

- Grep aliases;
- the basename of a read path;
- the argument to `rg`/`grep` in a shell command.

It then emits `additional_context` when augmentation succeeds.

Important limits:

- shell parsing is token-based and intentionally does not reconstruct general quoted multi-word patterns;
- it probes several undocumented Cursor field aliases;
- hook-slot saturation is silent by default;
- the integration source notes that its augment child is not yet protected by the same database-lock probe as the Claude adapter.

This is useful product integration but not a certified delivery path.

## 6. Public evaluation adapter

[`GitNexusAgent`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/eval/agents/gitnexus_agent.py) exposes three modes:

- `baseline`;
- `native`;
- `native_augment`.

In `native_augment`, `execute_actions()`:

1. executes the model-selected actions;
2. identifies grep/rg/ag-style commands;
3. executes `gitnexus-augment` as a host action;
4. appends the returned `[GitNexus]` block to the original observation;
5. records aggregate augmentation calls, time, hits, and errors.

This is source evidence for the delivery hypothesis:

> repository intelligence can be attached to an existing observation instead of requiring another model-selected graph action.

It does not prove that Akon's private DeepSWE benchmark used this mode.

### Prompt confound

The evaluation agent loads mode-specific system and instance templates. Therefore the public treatment can change both:

- tool/augmentation behavior; and
- what the model is told about those capabilities.

Any benchmark using this adapter must publish prompt parity and the chosen mode before attributing uplift to graph mechanics alone.

## 7. Index-build lifecycle

The index builder is substantially stronger than the live hook lifecycle.

Primary implementation: [`runFullAnalysis()` and `runFullAnalysisInner()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/run-analyze.ts).

### 7.1 Single-writer lock

[`storage/index-lock.ts`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/storage/index-lock.ts) supplies index-directory-scoped exclusive locking. `runFullAnalysis()` resolves the actual write target, acquires the lock, and can re-resolve/reacquire when the target moves while waiting.

### 7.2 Full versus incremental identity

The builder uses:

- current repository commit and working-tree state;
- per-file content hashes;
- persisted file hashes;
- schema fingerprint;
- analysis capability identity;
- analyzer runner identity;
- PDG settings and caps;
- CJK segmentation configuration;
- embedding dimensions;
- graph-write health metadata.

Material mismatches force a full rebuild rather than silently reusing incompatible graph state.

### 7.3 Incremental update

For a compatible index, it computes changed, added, deleted, and unchanged files. It expands the write set through importer and semantic dependencies so changes can update cross-file edges rather than only rows belonging directly to the edited file.

### 7.4 Dirty marker and recovery

Before mutating an incremental index, metadata records `incrementalInProgress`. If a later run sees that marker, it forces full recovery and quarantines sidecars that could replay partial state.

[`getIndexIncompleteReasons()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/index-freshness.ts) exposes machine-readable incompleteness including incremental-in-progress and graph-write collapse.

### 7.5 Atomic publication

Full rebuilds use a staging database and atomic publication where platform support permits. Optional atomic incremental mode copies and mutates a staging index when sidecars are clean. Metadata is finalized only after successful graph publication.

### 7.6 FTS and embedding recovery

The builder handles:

- FTS repair and failure classification;
- vector-dimension mismatch through rebuild;
- content-hash embedding reuse;
- embedding checkpoints;
- semantic search fallback when vector extensions are unavailable.

These are useful implementation patterns for GT's repository-session and cache recovery.

## 8. Staleness model

[`checkStaleness()` and `checkStalenessAsync()`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/gitnexus/src/core/git-staleness.ts) compare the indexed commit with repository HEAD and report commits behind.

The same module can identify sibling-clone/worktree mismatches and warn that results may be stale.

What it proves:

- GitNexus can detect commit drift and several repository-identity mismatches.

What it does not prove:

- every uncommitted source edit has been indexed;
- the provider response corresponds to the current workspace bytes;
- the graph was refreshed before the next model decision.

Commit identity is necessary but insufficient for a live repair agent.

## 9. Public evaluation environment lifecycle

[`GitNexusDockerEnvironment`](https://github.com/abhigyanpatwari/GitNexus/blob/fc885a4bf3edddf9214df633d8d1c0767ef58af9/eval/environments/gitnexus_docker.py) performs:

```text
container start
  -> install/locate Node and GitNexus
  -> restore or build index once
  -> start warm eval server
  -> install shell tools
  -> run agent trajectory against that index
```

### 9.1 Fail-open setup

If `_setup_gitnexus()` throws, the environment logs a warning and continues with `_gitnexus_ready=False`.

This is reasonable for preserving baseline agent operation. It is invalid as silent treatment success. A benchmark merge must mark the row substrate-invalid.

### 9.2 Static trajectory index

The public environment indexes at task start. No source-edit-triggered reindex is wired into the trajectory.

Therefore later augmentation can describe the pre-edit graph after the model has changed source.

### 9.3 Cache identity defect

`_make_cache_key()` hashes only:

```text
repository name : base commit
```

It omits:

- GitNexus source/package version;
- analyzer and language-provider identity;
- graph schema fingerprint;
- PDG configuration;
- embedding model/dimensions;
- feature configuration.

That cache can restore an index incompatible with the current runtime.

The production index builder has stronger mismatch checks, but the evaluation cache key itself is too weak and can copy an old index into a new environment before those assumptions are validated.

### 9.4 Embedding default

`skip_embeddings=True` by default. The public evaluator therefore does not prove that vector retrieval contributed to any result unless configuration explicitly overrides it.

## 10. Delivery-certification comparison

| Requirement | GitNexus hook/public eval | Intended GT contract |
|---|---:|---:|
| Stable evidence claim ID | No | Yes |
| Exact source/graph revision on payload | No | Yes |
| Exact provider-view hash | No | Yes |
| Exact request hash | No | Yes |
| Changed provider-message index | No | Yes |
| First-eligible/non-predictive timing | No | Yes |
| Prepared versus actually dispatched distinction | No | Yes |
| State fingerprint | No | Yes |
| Semantic support/certification persisted | No/partial | Yes |
| Duplicate-claim accounting | No | Yes |
| Complete candidate disposition accounting | No | Yes |
| Operational fail-open | Yes | Yes |
| Analytical/release fail-closed | No in public eval | Yes |

Conclusion: GitNexus demonstrates a useful placement pattern, not an acceptable GT release audit.

## 11. Mapping to current GT failures

The starting release state names repository-intelligence failures on
`qemu-alpine-ssh`, `torch-pipeline-parallelism`, and
`torch-tensor-parallelism`; dense-retrieval unavailability on
`qemu-alpine-ssh`; six provider-delivery failures; eleven persistent-state
lifecycle failures; common-solved efficiency regressions; and four definite
negative solve flips. The source comparison below does not reclassify any of
those rows without their receipts.

### 11.1 Repository intelligence unavailable

Useful adaptations:

- exact analyzer/schema/config identity;
- dirty/in-progress marker;
- sidecar quarantine;
- single-writer lock;
- atomic build publication;
- capability mismatch forcing rebuild.

Rejected adaptation:

- continuing without intelligence and counting the row as valid treatment.

### 11.2 Dense retrieval unavailable

GitNexus treats embeddings as optional and can continue with BM25. That is not a fix for a GT treatment that declared pinned dense retrieval required.

GT action:

- repair provisioning and runtime availability;
- receipt the expected/actual mode;
- fail the treatment gate when required dense is unavailable;
- keep the base agent operational.

### 11.3 Six provider-delivery audit failures

GitNexus lacks the certification needed to diagnose these. Copying its hook would hide the problem.

GT action:

- retain the contribution compiler and authoritative delivery audit;
- ensure each selected contribution is inserted, hashed, dispatched, and confirmed at the first eligible request;
- adapt only the automatic same-observation placement.

### 11.4 Eleven persistent-state lifecycle failures

GitNexus does not maintain GT-style task execution state across provider/preflight/postflight/rebase boundaries.

GT action:

- preserve graph-first persistent state;
- repair postflight commit and graph rebase;
- invalidate source-dependent state immediately on edit;
- never serve a stale graph frame while refresh is incomplete.

### 11.5 Efficiency regression

The promising GitNexus lesson is:

```text
ordinary model search/read
  -> host-side graph composition
  -> same observation gets callers/callees/process
  -> fewer later searches and reads
```

GT must measure whether the context actually replaces exploration. A delivery that adds tokens and leaves all later searches unchanged is not an efficiency gain.

## 12. Ranked lifecycle adaptations

1. **Complete cache identity** — include checkout, indexer build, schema, languages, configuration, PDG, and embedding identity.
2. **Dirty marker plus recovery-before-read** — stale partial state can never be certified current.
3. **Atomic graph publication and metadata ordering** — publish graph and revision as one lifecycle event.
4. **Action-local provider placement** — attach composed GT evidence to an existing observation with no extra model call.
5. **Content-addressed embedding reuse** — reuse only under exact model/text-template/dimension identity.
6. **Repository/worktree binding** — explicit repo identity before queries, including linked worktrees.
7. **Availability receipt for every retrieval lane** — optional absence is explicit; required absence fails the release gate.

## 13. Explicit rejections

1. Static task-start graph after model edits.
2. Cache identity based only on repository and commit.
3. Silent treatment setup failure.
4. Silent hook-slot or augmentation failure as successful delivery.
5. Commit-only freshness as evidence-byte freshness.
6. MCP-query fallback as the default when automatic host delivery is available.
7. Delivery counts without exact provider-view proof.
8. Optional embeddings silently standing in for a required dense treatment.

## 14. Lifecycle verdict

### Source-proven

GitNexus has mature general-purpose index-build and recovery machinery and several useful automatic integration points.

### Inference

The same-observation delivery path can improve efficiency if its compact relational answer replaces subsequent exploration.

### Unknown

Public evidence does not show the exact delivery mode, hook configuration, stale-index behavior, or retrieval-lane availability used in Akon's benchmark.

### GT decision

Adopt GitNexus's index-recovery patterns and delivery placement. Preserve GT's stronger graph-per-edit lifecycle, persistent execution state, evidence authority, provider hashing, and analytical fail-closed gate.
