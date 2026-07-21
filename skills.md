# nano-harness — Skills Playbook

Skills to use during this project, when to invoke them, and why.

## Active right now (brainstorm phase)
- **superpowers:brainstorming** — currently running. Producing the design doc. Do NOT skip ahead to writing-plans or implementation skills until the design is approved.

## Next, in order
1. **superpowers:writing-plans** — invoke after the design doc is written and approved. Converts the spec into a numbered implementation plan with checkpoints.
2. **superpowers:executing-plans** — runs the implementation plan in a fresh session with review gates between steps.
3. **superpowers:test-driven-development** — for any non-trivial code in the harness. Especially the loop, tool execution, and benchmark eval glue.
4. **superpowers:systematic-debugging** — when (not if) the harness misbehaves on benchmark tasks. Iron Law: no fixes without root cause. Helpful for diagnosing why a model failed a task — was it the prompt, the loop, the tool result, the context window?
5. **superpowers:verification-before-completion** — before claiming a benchmark score. Every published number must be reproducible from a logged eval run.
6. **superpowers:requesting-code-review** — before any major release / blog post.

## Strategic / review skills (use periodically)
- **plan-ceo-review** — when the scope feels off. Ask "is this ambitious enough?" or "is this too ambitious?"
- **plan-eng-review** — before executing the plan. Catch architecture issues before code.
- **plan-devex-review** — relevant only if/when nano-harness gains a CLI surface for others to use. Likely later.
- **codex** — second opinion mode. Useful for adversarial review of the harness loop and prompt design. The "200 IQ autistic developer" check.

## Domain-specific skills
- **claude-api** — required if Claude is one of the supported models (likely yes). Makes sure prompt caching is wired up — non-trivial cost win on benchmark runs.
- **huggingface-skills:huggingface-best** — when picking which open-source models to include for the multi-model leaderboard table (if that path is chosen).
- **huggingface-skills:huggingface-local-models** — for running local models (Llama, Qwen, DeepSeek) via llama.cpp during benchmark runs.
- **huggingface-skills:huggingface-llm-trainer** — only relevant if we ever fine-tune a model for the harness (deferred / probably never).
- **huggingface-skills:huggingface-community-evals** — for running evals locally with inspect-ai or lighteval. May overlap with our own eval harness — investigate before duplicating.

## Skills to deliberately NOT use
- **frontend-design** — no UI in scope.
- **figma:** anything — no design system needed for a CLI/library.
- **build-with-wordpress:** — irrelevant.
- **superpowers:dispatching-parallel-agents** — overkill for solo work on a small codebase.
- **autoplan** — too heavy for a project this focused. We can answer review questions ourselves.

## Workflow rituals
- Before any code: design doc approved + writing-plans run.
- During execution: TDD where it matters (loop, tools, eval), pragmatic where it doesn't (one-off scripts).
- After every benchmark run: log full transcript, commit results, no cherry-picking.
- Before publishing a number: verification-before-completion + a re-run from a cold cache.
