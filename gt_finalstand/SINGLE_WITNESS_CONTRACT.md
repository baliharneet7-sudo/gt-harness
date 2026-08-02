# FS-024 Single Matched Witness Contract

The project owner replaced the preregistered six-arm experiment with one
provider-bound GroundTruth run compared against a frozen GT-off trajectory
already present in local Downloads. No six-arm provider experiment will run.

## Selected pair

- Benchmark: `terminal-bench@2.0`
- Task: `fix-code-vulnerability`
- Dataset commit: `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`
- Task checksum: `13c4e35adbd7e55707f273aabd8f4108672f0fb790c96af543fbcbdcc977b119`
- Baseline run: GitHub Actions `30665246698`
- Baseline trial: `70179645-7ff8-4142-9354-a0613b6c04d0`
- Baseline harness: `eval.miniswe_agent:MiniSweAgent`, Mini-SWE `2.2.8`
- Candidate harness: `eval.miniswe_agent:MiniSweGtAgent`, Mini-SWE `2.2.8`
- Model: `deepseek-v4-flash`, resolved as `openai/deepseek-v4-flash`
- Required provider fingerprint: `fp_a18b46594c_prod0820_fp8_kvcache_20260402`
- Temperature: `1.0`; step limit: `100`; cost limit: `$3`; command timeout:
  `30` seconds; agent timeout multiplier: `1.0`; attempts: `1`; concurrency: `1`

The treatment is GroundTruth advisory activation. The workflow must fail before
the benchmark trial if the model fingerprint differs. After execution, the
candidate result must match the task checksum, task-prompt hash, dataset commit,
Mini-SWE version, model identity, temperature, budgets, and trajectory format
recorded in `receipts/fs024_single_witness_baseline.json`.

The system-prompt hash is recorded but is not a controlled-equality field:
GroundTruth's deterministic advisory suffix is the treatment and therefore must
change the candidate system prompt. The underlying task/user prompt must remain
byte-identical.

## Completion rule

FS-024 completes when exactly one authorized candidate trial:

1. runs in GitHub Actions rather than on the local workstation;
2. produces an independently verified reward;
3. produces a GT delivery/receipt trail and a complete Mini-SWE trajectory;
4. matches every frozen baseline identity except treatment, provider request
   IDs, timestamps, and other execution-specific identities;
5. is analyzed by `scripts/phase2_single_witness.py`; and
6. freezes the workflow run, artifact, input hashes, and descriptive deltas.

The result is a one-task engineering witness. It can demonstrate execution,
non-regression on that task, and concrete exploration/token deltas. It cannot
estimate population solve-rate impact, support confidence intervals, or justify
a general causal claim.

## Promotion and project closure

FS-025 uses the witness only as a regression gate. If candidate reward is below
baseline reward, the rollout default remains off. If reward is equal or higher,
the implemented interface may remain available behind its existing activation
boundary, but the single task does not justify making a universal efficacy
claim.

FS-026 closes after the run artifact, analysis, conservative promotion decision,
and rollback receipt are frozen and validated. Closure means the requested
engineering project ended with an honest bounded result; it does not mean that
one stochastic observation became a benchmark-wide estimate.
