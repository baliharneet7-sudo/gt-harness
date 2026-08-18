# How to Freeze and Evaluate Strengthened GroundTruth

Evaluation is the final step. Finish implementation, review, local verification, historical replay
predictions, and exact-commit provider-free proof first. The outcome comparison uses the existing
baseline and previous small 20-task GT runs; GitNexus is not an evaluation arm.

## 1. Create caller-owned inputs

Create a task manifest, execution contract, and treatment descriptor. No task count, step limit,
trial count, model, treatment ID, or competitor is embedded in the builder.

Execution contract schema:

```json
{
  "task_count": 20,
  "task_order_sha256": "<sha256>",
  "provider_identity": "<provider/model route>",
  "temperature": 0.0,
  "sampling_parameters": {},
  "tool_envelope_sha256": "<sha256>",
  "hook_envelope_sha256": "<sha256>",
  "embedding_configuration_sha256": "<sha256>",
  "hardware_assumptions_sha256": "<sha256>",
  "retry_policy_sha256": "<sha256>",
  "timeout_policy_sha256": "<sha256>",
  "token_accounting_sha256": "<sha256>"
}
```

The numbers are examples only. They must describe the chosen run.

Treatment descriptor schema:

```json
[
  {
    "adapter_kind": "bare",
    "treatment_id": "baseline",
    "source_sha": "<40-character harness SHA>"
  },
  {
    "adapter_kind": "groundtruth",
    "treatment_id": "strengthened-gt",
    "source_sha": "<same 40-character harness SHA>",
    "profile_id": "central_relational_v2",
    "preemptive_retrieval": true,
    "relational_context": true,
    "dense_fallback_only": true,
    "semantic_evidence": true
  }
]
```

Use only the arms actually intended for the run. There are no implicit arms.
`dense_fallback_only` remains a compatibility/order flag; the strengthened retriever still
evaluates exact, lexical, BM25, structural, and dense channels on every applicable state.

## 2. Build the immutable manifest

```powershell
python -m scripts.build_benchmark_manifest `
  --benchmark-id <benchmark-id> `
  --task-manifest <tasks.jsonl> `
  --model-id <provider/model> `
  --scaffold-sha <40-character-sha> `
  --treatments <treatments.json> `
  --execution-contract <execution-contract.json> `
  --max-steps <selected-step-budget> `
  --trials-per-task <selected-trial-count> `
  --output <benchmark-manifest.json>
```

The builder hashes caller-owned files and writes atomically. It refuses to overwrite an input.

For the checked-in TB2 workflow this construction is automatic and happens before
the provider-owned agent loop. The task set comes from the selected frozen baseline
profile, the step budget comes from that baseline's model identity, the model ID
comes from the authenticated canary, and the source SHA is the exact checked-out
commit. The workflow does not keep a second literal step limit or a hand-maintained
feature argument list.

The workflow then renders `eval/treatments/tb2_central_relational_v2.json` with
`scripts/render_treatment_agent_args.py`. The generated runtime contract is hashed,
passed to the agent, archived, and checked by the release gate. A legacy default
profile is a hard failure rather than a fallback.

Every task row must carry the same verified benchmark-manifest hash. The timeout
contract contains the caller-derived budget map for the complete selected task
set, so task-specific Harbor deadlines do not produce task-specific benchmark
identities. Merge fails the whole treatment if any row is missing, has a different
hash, or if any descriptor-controlled runtime argument differs from the effective
agent value.

## 3. Prove implementation integrity

Run focused and full local tests and static checks. Then freeze one exact commit and run the
source-built Linux provider-free workflow with the current indexer and pinned local ONNX asset.
This proves integration integrity only and must make zero provider calls.

## 4. Freeze predictions

Before viewing new outcomes, record which historical losses should recover, which both-fail tasks
might flip, which baseline passes are endangered, expected evidence claims, and abstention cases.
Hash the prediction file.

## 5. Enforce observed runtime parity

Capture each execution field at its owning runner component and build a typed observation. Do not
construct this object by copying `manifest.execution_contract`:

The runner should first write one JSON object from each owning component, then compose those
documents with the checked-in CLI. The CLI fixes field ownership; it does not accept a caller's
free-form origin labels:

```powershell
python -m scripts.build_runtime_observation `
  --dispatch-manifest dispatch-manifest.json `
  --provider-request provider-request.json `
  --serialized-runtime-envelope serialized-runtime-envelope.json `
  --loaded-asset-receipt loaded-asset-receipt.json `
  --runner-environment runner-environment.json `
  --runtime-policy runtime-policy.json `
  --metering-adapter metering-adapter.json `
  --output runtime-observation.json
```

The seven source documents must contain independently observed values for their assigned fields.
The resulting file has value hashes and fixed source labels. The agent can receive it through
`runtime_observation_path` or the host-only `GT_RUNTIME_OBSERVATION_PATH` environment variable.
Do not construct it by copying `manifest.execution_contract`.

Write that object to a host-owned JSON file and pass its path as
`runtime_observation_path`; pass `benchmark_identity` separately. The agent independently
overwrites provider identity and temperature from its live provider/agent envelope. If any
runner-owned field or source hash is missing, it emits
`gt.agent_runtime_observation.partial.v1`, which is deliberately parity-invalid.

Audit every receipt:

```python
result = audit_runtime_receipt(manifest, receipt)
if not result.valid:
    raise RuntimeError(", ".join(result.failures))
```

The receipt must include both the declaration and `observed_runtime_contract`. A copied declaration
without observed runtime facts is invalid. Model, step budget, treatment, actual agent flags,
temperature, provider/tool/hook/embedding/hardware/retry/timeout/token-accounting envelopes must
all match.

## 6. Final outcome comparison

Keep the reliable baseline setup unchanged. Compare baseline, the previous small-run GT result, and
the strengthened candidate on the same 20-task denominator. Report resolve—not patch rate—plus
positive/negative flips, executor steps, provider calls including bootstrap, tokens, cost, files
opened/edited, checks, evidence deliveries/tokens, index/query latency, abstentions, and invalid or
provider-censored rows.

Do not add a GitNexus arm. Do not alter the denominator. Do not claim uplift from provider-free or
unit-test evidence.
