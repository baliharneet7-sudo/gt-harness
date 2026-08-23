# SWE-bench Live Lite output contract

The denominator is the selected Live Lite manifest (300 tasks for the full
run, or the explicit 20-task smoke). Each trial artifact must contain the
official evaluator outcome `reward.txt` (`1` solved, `0` unsolved), the task
trajectory, evaluator report/log, and task identity. GT-on artifacts additionally
retain the GT completion/receipt, deep metrics, performance metrics, behavioral
impact, feature/runtime ledger, and provenance files required by the release
gate. GT-off is not required to manufacture GT-only receipts.

Per-task metrics retained for audit are resolved outcome, agent steps/actions,
provider calls, input/output/total tokens, provider cost (or explicit missing
cost), wall time, evaluator/infra timeout classification, and model/provider
identity. The independent `PARTIAL` artifact counts only explicit reward files
and reports returned/graded/ungraded/solved/unsolved rows even if the large
diagnostic summarize job or merge gate fails.

The partial artifact is reporting-only: it cannot alter task selection,
official evaluator behavior, denominator, step limit (150), or evaluator
timeout (1800 seconds).
