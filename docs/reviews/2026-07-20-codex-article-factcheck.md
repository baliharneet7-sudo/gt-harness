# Codex fact-check and voice review

- Reviewed source: `terminal-bench-article-for-codex-review.md`
- Canonical source checked: `docs/article/dev-to-draft.md`
- Repository state checked: `main` at `f7c0509a02f8b4866e254eb127a4520d8add614a`
- Review date: 2026-07-20 America/Phoenix
- Verdict: HOLD before publishing. The article is strong, but four factual/evidence issues need correction.

## Required before publication

### 1. Delete or replace the leaderboard-comparison paragraph (draft line 57)

The paragraph mixes benchmark versions and therefore cannot support the claimed harness-gap measurement.

- The nano-harness result is Terminal-Bench 2.0.
- Anthropic reports Opus 4.8 at 74.6% on Terminal-Bench 2.1, not 2.0.
- The official verified Terminal-Bench 2.0 page currently lists GPT-5.5 at 82.2% +/- 2.2, not 82.7%.
- I found no verified Opus 4.8 entry on that official 2.0 table.
- The 49-model/60% average appears to come from an llm-stats aggregation, not the official Terminal-Bench 2.0 table.
- Therefore, "same brain," "captures about 80%," and "a clean measurement" are not defensible.

Primary sources:

- https://www.tbench.ai/leaderboard/terminal-bench/2.0?verified=true
- https://www.anthropic.com/research/claude-opus-4-8

Suggested replacement:

> Public Terminal-Bench results are agent-model pairs, so model and harness effects are entangled. I could not find a verified Opus 4.8 entry on the official Terminal-Bench 2.0 table, which means I cannot turn 59.6% into a clean measurement of the harness gap. It is simply my self-run result under the conditions disclosed here, with the code and task-level record available for inspection.

Repository follow-up: `docs/benchmarks/tb2-scorecard.png` also labels these mixed numbers as Terminal-Bench 2.0. Remove or rebuild that graphic before making the repository public. The README alt text repeats the unsupported 60% field-average claim.

### 2. Change 86 tests to 87 (draft lines 7, 76, and 101)

The current suite collects:

- `test_agent.py`: 20
- `test_cli.py`: 6
- `test_log.py`: 1
- `test_prompts.py`: 3
- `test_providers.py`: 19
- `test_tools.py`: 38
- Total: 87

The benchmark commit `0903552` is also the last commit that changed tests, so 87 applies to the benchmarked code. The earlier 52-test count is documented and can remain. Update the README's two references to 86 as well.

### 3. Do not publish 2.7M tokens / $40 as a verified clean-run figure (draft line 88)

The clean-run root JSON has null token and cost fields. Harbor's later retry overwrote several per-trial artifacts, so the current directory is not a pristine token record for the 53/89 run.

What the surviving 88 agent logs currently total:

- Input: 1,543,783
- Output: 1,431,418
- Combined: 2,975,201
- At Opus 4.8 global list rates of $5/M input and $25/M output: about $43.50

Those rates are confirmed by Anthropic, but the surviving total includes retry-overwritten trials. Either recover the original pre-retry tally or state exactly what the surviving logs show.

Safe replacement if the original tally cannot be recovered:

> The surviving run directory, after Harbor's retry overwrote several trials, contains about 3.0M logged input and output tokens. At Opus 4.8's July 2026 global list rates, that works out to roughly $44. My actual spend was $0 because I used the ASU AIML gateway's free allocation.

Also change "about an hour" for a 10-task slice to "roughly one to two hours." The two clean Opus slice runs took 1h21m and 1h44m and imply roughly $4-$6 at current list rates.

Pricing source:

- https://www.anthropic.com/research/claude-opus-4-8

### 4. Add the review outputs or narrow the review-evidence claim (draft lines 63-76 and 101)

The repository contains `docs/reviews/2026-07-16-re-review-paste.md`, but that file contains the re-review request plus pasted code, not the reviewer's response. I did not find the original 4/10 output, the 6/10 response, or the two-nit cloud-review output in the tree.

The commit history supports the described fixes, but it does not independently prove the scores or exact review wording. Choose one:

1. Add redacted copies of the three review outputs to `docs/reviews/`, or
2. Keep the narrative as an owner-attested account and change line 101 from "the review artifacts all in the tree" to "the re-review prompt and resulting fix history in the tree."

The stronger, more transparent choice is to add the review outputs.

## Accuracy edits

### Verify-gate description (draft line 41)

The current paragraph omits two details: tool-free runs are accepted without the gate, and after tools are used the first `done` is challenged even if earlier tools succeeded.

Suggested replacement:

> "Honest" means a failing command must read as a failure, and "done" must be earned. Once a run has used tools, the first `done` is challenged: re-read the task, run the relevant checks, and prove it. A later completion is accepted only when successful tool evidence has appeared since that challenge. If the pushback or iteration budget runs out without that evidence, the result is returned as `unverified`, not dressed up as success. Tool-free tasks are allowed to finish normally.

### Nonzero-exit claim (draft lines 67 and 78)

"A failing test can never satisfy the verify gate again" is too absolute. The gate counts any successful tool call, and a compound shell command can mask an earlier failure by exiting zero.

Use:

> Nonzero shell status now raises a tool error, so a plain failing test command no longer counts as successful verification evidence.

The historical description at line 67 is accurate: before the fix, the shell did not carry the command's exit status back through its sentinel protocol.

### Causal claim about the five-task gain (draft line 84)

The two full runs are stochastic single runs. "Five extra tasks, purely from correctness fixes" overstates causal certainty even though no task-specific benchmark patches were made.

Suggested replacement:

> The hardened run passed five more tasks, a 5.7-point gain. These are stochastic single runs, so I cannot prove that every point came from a specific fix. What I can say is that the intervening changes were correctness and safety fixes, not task-specific benchmark patches, and the next full run scored higher.

### Opening generalization (draft line 25)

"Every popular agent framework" and "almost none" are broad, unsourced claims. Use a first-person observation instead:

> Most agent projects I was following led with features: plugins, orchestration graphs, UI dashboards, and memory systems. I had a harder time finding small, readable harnesses paired with reproducible full-suite benchmark results.

### Monthly-seat comparison (draft line 88)

"Most agent products" is another current, unsourced market claim. Cut it unless specific products and current prices are cited. The cost paragraph is stronger without it.

## Verified claims

These checked out against the repository or run artifacts:

- 967 nonblank lines across the five named core Python files, so `~970` is fair.
- Three tools, two provider adapters, and MIT licensing.
- Slice progression of 20%, 70%, and 80% in the named 10-task runs.
- Full-run results of 48/89 (53.9%) and 53/89 (59.6%).
- Final clean-run duration of 16h25m with two trials in parallel.
- 53 passes and 36 non-passes; the committed benchmark record documents 10 timeouts plus one exit-137/OOM as failures.
- Nonzero-status capture, complete-line sentinel matching under `set -x`, permission preservation, symlink-target editing, mixed-line-ending preservation, process reaping, and `unverified` fail-closed behavior all exist in current code and regression history.
- The `gpt2-codegolf` characterization is accurate. Its verifier checks for `/app/gpt2.c`, a sub-5000-byte size, successful compilation, one fixed invocation, and one expected output substring. A hardcoded program could satisfy it. The run of record failed because `/app/gpt2.c` did not exist, so nano-harness did not game it.

Verifier source:

- https://huggingface.co/datasets/introvoyz041/terminal-bench-2.0/blob/main/gpt2-codegolf/tests/test_outputs.py

## First-person voice

Overall, the voice works for a technical Dev.to build-in-public article: direct, self-critical, and specific. A few lines need Troy's confirmation because they invent personal emotion or authorship details rather than report repository facts:

- "The one that stung most" - keep only if that is genuinely how Troy felt; otherwise use "The most consequential finding was."
- "So I fixed everything" - if Claude or other agents wrote material portions, consider "I worked through the findings test-first" and add one sentence disclosing the AI-assisted development workflow. An honesty-themed article should not accidentally imply all 967 lines were hand-authored.
- "got roasted" - good Dev.to energy if it sounds like Troy; otherwise "received a 4/10 adversarial review" is cleaner.
- "including you" and "That's the game" - memorable, slightly combative closers. Keep them only if Troy wants that edge.

## Publishing mechanics

- `cover_image:` is currently null with an inline reminder. Replace it with the uploaded absolute image URL before publishing.
- `docs/assets/banner.png` is 2172x724 (3:1). Check the Dev.to preview because a cover crop may cut the ends.
- The two GitHub links are structurally correct and should resolve after the repository becomes public.
- The clean aggregate screenshot and benchmark breakdown are committed. Keep commit `0903552` in the article or benchmark page as the immutable code reference.
