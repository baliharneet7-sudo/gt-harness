# Same-20 validation report

## Decision

The paid 20-task gate remains blocked until the current candidate receives an
exact pushed-SHA provider-free proof. No new paid rerun is represented here.

## Latest archived cohort

Workflow `32455040841` returned all 20 task rows: 17 had verifier rewards and
three ended in provider connection errors. Current code replay passes 20/20
central deterministic receipts and 20/20 delivery audits. The historical
terminal release gate passes 16/20 rows; count has a real graph-refresh failure,
and FEAL, regex-chess, and schemelike are incomplete because provider transport
ended their trajectories.

Those archived errors are censored infrastructure rows, not solved/unsolved
outcomes. The historical cohort cannot certify the current candidate because
its runtime predates the current repairs.

## Outcome and causal boundary

The prior fully graded matched cohort recorded 13 both-solve, one GT-only
(`largest-eigenval`), four baseline-only, and two both-fail tasks. This is raw
quadrant accounting. Baseline action trajectories are absent, so no positive or
negative flip has confirmed GT causality. See
[negative-flip autopsy](04_GT_NEGATIVE_FLIP_AUTOPSY.md) and
[positive-flip autopsy](05_GT_POSITIVE_FLIP_AUTOPSY.md).

## Current implementation proof status

Local focused witnesses cover graph refresh, routing, observed-fact accounting,
typed outcomes, workflow security, and documentation completeness. The exact
final full-suite, Linux source-build, pinned ONNX, release freeze, and hosted
provider-free results belong in this report only after they execute. Until then
the honest state is `IMPLEMENTED_UNVERIFIED`.
