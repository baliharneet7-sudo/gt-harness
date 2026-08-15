# GT Benchmark-Integrity Audit SOP

Status: authoritative for the host-owned central runtime (`MiniSweCentralAgent`).
This is a **compliance demonstration**, not an accounting change: it proves GT
reads only the three legal evidence sources and never grader-only artifacts, and
it never alters the benchmark denominator, verifier, or how any task is scored.

## 1. The three legal evidence sources

GroundTruth's grounded context may come only from what is genuinely available
during the benchmark:

1. **The task instruction** as provided to the agent (task text / prompt).
2. **The repository source** actually present in the task workspace.
3. **The agent's own observed execution results** (its command outputs).

Everything GT delivers to the model must trace to one of these.

## 2. The forbidden set (grader-only artifacts)

GT must **never** read, infer, or depend on anything not present during the
benchmark:

- hidden verifier tests (`tests/`, `test_outputs.py`, `test.sh`);
- the reference solution (`solution/`, `REF`, `ref.js`, `reference.json`);
- host verifier outputs (`reward.txt`, `ctrf.json`, `verifier/report.json`);
- any held-out or post-hoc grader file.

These run after the agent finishes, in a separate phase, and are absent from the
task container. Reading them is benchmark contamination and is forbidden in
every mode (`off`, `audit`, and the certified arms).

## 3. What the audit proves

Run the audit at the exact treatment commit before any paid run:

```bash
python scripts/central_integrity_audit.py            # static source boundary
python scripts/central_integrity_audit.py <run-root> # + per-receipt provenance
```

It prints two proof lines, both required:

- `EVIDENCE_SOURCE_ALLOWLIST_PROVEN` — the active runtime modules
  (`gt_engine/**`, `eval/gt_central_agent.py`) never open/read/glob a
  grader-only artifact path, and `compile_completion_plan` builds predicates
  only from task-instruction text and workspace-rooted paths.
- `NO_GRADER_ACCESS_PROVEN` — every model-visible delivery's recorded evidence
  carries a legal origin and no delivered claim/anchor references a grader-only
  path.

The same grader-marker and legal-origin rules are enforced per-receipt inside
`scripts/central_trajectory_audit.py` (`delivery_grader_path`,
`delivery_grader_fact_path`, `delivery_illegal_evidence_origin`), so archived
trajectories are re-audited on every run.

## 4. Case study A — `extract-elf`: a coverage gap, not an integrity break

- GT delivered **0 visible characters** on this task (all evidence
  `controller_only` / `represented_message`).
- The model needed to know "key by section `vaddr`, not `0x400000`". The
  instruction example (`{"4194304": ...}` = `0x400000`) actively misleads; the
  correct convention lives only in the hidden `REF` grader.
- **Result:** GT abstained. The outcome stayed temperature-dependent. This is a
  legitimate **coverage gap** — the determinizing evidence is grader-only, so GT
  neither caused nor could fix the miss. It is not counted as a GT regression.

## 5. Case study B — `video-processing`: a legitimate abstention

- GT delivered 215 visible chars total (two "stall" progress frames), nothing
  about output format.
- The instruction shows `jump_takeoff_frame_number = [integer]` (brackets); the
  verifier expects a bare `int`. Only the hidden `test_outputs.py` resolves
  which reading is correct.
- **Result:** GT abstained correctly. The int-vs-list choice is a grader-only
  convention; the outcome is temperature-dependent by necessity.

## 6. Boundary discipline

- Both case-study tasks **remain in the full solve-rate denominator** — 13/15 vs
  10-11/15 stays the honest, unmodified number. Integrity exclusion never means
  removing a task from the score.
- A task whose decisive convention is grader-only is simply **outside GT's
  determinism guarantee**; GT abstains rather than fabricate or peek.
- The follow-up (separate, read-only) is whether GT can surface *observed
  execution facts that contradict the model's stated assumption* (e.g., "this
  ELF is `DYN`/PIE, not non-PIE") from source (3) alone — which would have
  grounded `extract-elf` without touching the grader. That is a feature gap to
  research, not a change to this boundary.

## 7. When to run

- Required in the `central_provider_free.yml` suite at the exact pushed commit.
- Run against every paid run root before interpreting solve/efficiency claims.
- Never weakened by a stale local binary; the source-built Linux gate is
  authoritative.
