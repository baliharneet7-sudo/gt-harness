# GT Central Runtime Implementation

**Status:** provider-free implementation complete; paid GT-on experiments not yet run  
**Date:** 2026-08-03  
**Historical comparator:** frozen GT-off, 66/89 solved

## Decision

The inline installed engine is no longer the active paid-evaluation path. GT is
implemented as a host-owned Harbor `BaseAgent`: it owns the model loop and every
action transition, while its code, state, configuration, provider credentials,
and receipts stay outside the task container.

This is an isolation change, not a reduction in integration. Every model action
still crosses the central runtime before and after `BaseEnvironment.exec`.

## Why Round 11 was inefficient

- The selected ten tasks stayed at 9/10 while calls rose 420 to 650, actions
  rose 483 to 669, and tokens rose 29.22M to 74.00M.
- Submission suppression could preserve a failed check indefinitely because a
  later pass did not resolve the blocker and engine edit detection depended on
  Git plus `.py` paths.
- The engine repeatedly counted an already-dirty Python file as a new edit and
  missed non-Git and non-Python edits.
- The Round 11 workflow removed six variables, but the installed runner
  recreated a much larger `GT_*` environment inside the model process.
- The `groundtruth` tool, task-obligation echoes, rejection messages, readable
  package, and state artifacts encouraged the model to debug the evaluator.
- The readiness audit exercised a curated Git/Python fixture, not the model's
  actual process, package, tool, and filesystem surface.
- Feature firing and later anchor overlap were treated as efficacy even though
  neither is a randomized counterfactual.

## Implemented architecture

### Host-owned agent

`eval.gt_central_agent:MiniSweCentralAgent` is a Harbor `BaseAgent`, not a
`BaseInstalledAgent`. `setup()` intentionally installs and uploads nothing.
Provider calls execute on the host. Model-selected commands execute in the task
through Harbor with an empty environment mapping.

The model-facing interface is stock Mini-SWE:

- stock system and instance templates;
- stock `LitellmModel`;
- one Bash tool;
- no typed GT tool;
- no GT prompt tags or facts;
- no task-container GT source, state, package, binary, or provider key.

The runtime emits both a Mini-SWE-compatible trajectory and ATIF-v1.7 on the
host. Private candidate and decision receipts are written separately and are
not included in model context.

### Workspace transitions

The central sensor is non-Git and language-independent. It records path, type,
size, mtime, ctime, symlink target, and hashes for files whose metadata changed.
Ctime detects same-size rewrites even when mtime is restored. Each real action
produces at most one revision transition.

The sensor fails open. More than 50,000 entries, more than 100 changed files,
a scan over two seconds, a malformed manifest, or a hashing failure disables
state-dependent hard decisions for that task.

### Evidence and submission

Failed checks are identified by normalized command and revision. A passing
rerun removes the matching failure immediately, including at the same revision.
An edit makes prior evidence stale. Only a check explicitly present in the task
instruction or a deterministic changed-file syntax failure is grounded enough
to affect submission.

A grounded fresh failure may hold one submit attempt. The next submit at that
same state passes unconditionally. Unrelated failures, stale failures, and
degraded sensing never block.

### First interventions

- Changed-file syntax feedback for Python, JavaScript, shell, Ruby, and COBOL.
- Bounded structured submission readiness.
- Feedback is emitted only on failure, at most once per action, and capped at
  320 characters.
- The shadow arm computes and records the same candidates without modifying
  model-visible bytes.

## GT-on evaluation implementation

The paid workflow now selects:

- `MiniSweCentralShadowAgent` for GT-on core/shadow;
- `MiniSweCentralAgent` for GT-on treatment;
- `lint`, `submit_readiness`, or `integrated` feature mode.

The workflow pins Mini-SWE 2.2.8 on the host. It does not install the agent or
GT into the task image.

`gt_engine.experiment` implements deterministic arm assignment, deterministic
eligible-panel selection, five-repeat task-cluster bootstrap analysis, and the
predeclared Pareto gate:

- mean solve count at least 72/89;
- one-sided 95% lower solve-delta bound above zero;
- mean tokens no more than 206,159,394;
- mean actions no more than 3,734.9;
- one-sided 95% upper token/action ratios no more than 0.85;
- no run with more than four errored tasks;
- zero runtime failures and permanently blocked submissions.

## Verification

The focused provider-free battery covers the host boundary, workspace
transitions, lint feedback, pass-clears-failure semantics, bounded submission,
shadow/treatment workflow, ATIF output, deterministic assignment, and release
gate. The dispatch-only `central_provider_free.yml` repeats those checks with
zero provider calls.

Local receipts:

- 24/24 focused central/experiment tests passed under Mini-SWE 2.3.0;
- the same 24/24 passed in a fresh isolated Mini-SWE 2.2.8 environment;
- the complete repository suite collected 782 tests: 779 passed and three
  expected Windows/platform skips;
- structural readiness reported `READY` and changed-file Ruff checks passed;
- Harbor 0.20 custom-agent dispatch uses its required `--agent-import-path`
  option, protected by both a workflow assertion and the readiness audit;
- direct agent construction without a runner-injected session ID and a Windows
  CP1252 audit console are covered by fail-safe portability handling;
- a deliberate `>=` to `>` hold-budget mutation made the bounded-submit test
  fail, and restoring the condition returned it to green.

The older inline-engine workflow and tests remain as an explicit
legacy/forensic path; they are not the active paid-evaluation agent.

The provider-free smoke gate was re-executed after implementation: 24/24
focused tests passed under the isolated Mini-SWE 2.2.8 environment, the
structural audit reported `READY`, and Ruff passed. A live canary remains
pending because the local Docker Linux daemon is stopped and no provider
credential is present locally; no provider request was attempted.

The first GitHub ten-task GT-on treatment smoke then completed as run
`30856353817`. All ten verifier results and all ten host receipt bundles were
returned; eight tasks solved and two timed out at Harbor's 900-second agent
limit (`gpt2-codegolf`, `write-compressor`). All ten sensors remained healthy,
no private GT terms appeared in model trajectories, and no repeated submit
hold was recorded. Aggregate usage was 448 model calls, 459 actions, and about
26.1M tokens. This is a runtime/wiring success but a smoke non-regression
failure against the frozen 9/10 reference. Shadow and 89-task runs remain
blocked pending timeout diagnosis.

### Smoke delta against frozen GT-off

| metric | frozen GT-off | GT-on treatment | delta | interpretation |
|---|---:|---:|---:|---|
| solved | 9/10 | 8/10 | -1 task, -10 percentage points | regression |
| timeout/error tasks | 1 | 2 | +1 | regression |
| model calls | 420 | 448 | +28 (+6.7%) | not more efficient |
| actions | 483 | 459 | -24 (-5.0%) | fewer actions, but two tasks did not finish |
| reported tokens | 29.22M | 26.11M | -3.11M (-10.6%) | censored by timeouts; not evidence of savings |

Task-level change was eight unchanged solves, one unchanged `gpt2-codegolf`
failure, and one new `write-compressor` regression. Therefore this smoke does
not show that GT helps. It shows that the host boundary works in Harbor, while
the treatment still needs timeout diagnosis and repeated matched trials.

## Remaining execution gates

1. Run the provider-free workflow at an immutable commit.
2. Run one live GT-on canary task to verify Harbor import, model loop, task
   command execution, receipts, and submission end to end.
3. Run the canonical ten-task GT-on smoke from
   `config/tb2_deepseek_smoke10.json`; do not start the 89-task matrix yet.
4. Require every smoke job to return a verifier result and host trajectory,
   central receipt, and ATIF receipt; require no import/setup/runtime error,
   no private GT surface in the model shell, no permanently blocked submit,
   and no repeated hold at one workspace revision.
5. Review smoke solve parity against the frozen 9/10 reference and inspect
   calls, actions, tokens, sensor health, and intervention receipts. Smoke
   parity is a wiring/non-regression gate, not a superiority claim.
6. Only after the smoke gate passes, replay historical trajectories and run
   GT-on shadow versus single-feature treatment experiments.
7. Integrate only candidates that improve solve, tokens, and actions.
8. Run five full 89-task GT-on repetitions and apply the frozen Pareto gate.

No superiority or efficiency claim is made until those paid GT-on stages pass.
