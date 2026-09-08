"""The completion gate: refuse a submission that has not shown its work.

Twelve of twenty tasks in the measured run ended ``submitted_unverified`` --
the agent submitted while obligations had no evidence at all. That single fact
is what failed the attestation. It is not a defect in the gate: the benchmark
runs ``--gt-mode advisory``, so ``GTSession.can_enforce`` is False and the
existing enforcing gate is simply unreachable.

This module supplies the decision for a plan-scoped gate that works in advisory
mode, with three properties that keep it honest:

* It refuses ONCE. The controller's own submit path already yields on the second
  attempt, and this matches it. The gate is a reminder, never a cage.
* It escapes on budget. A gate that turns a near-miss into a timeout converts a
  partial score into a zero, and four of the measured losses were one or two
  tests short. Time and steps are checked BEFORE any refusal.
* It never blocks on its own ignorance. An unmet row blocks; an unknown
  baseline, a failed probe or a missing plan does not.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Refusing with less than this left converts a near-miss into a timeout, which
# scores the same as a wrong answer. The agent needs room to act on the refusal.
MIN_REMAINING_SECONDS = 600.0
MIN_REMAINING_STEPS = 20
MAX_REFUSALS = 1
MAX_LISTED_ROWS = 12


@dataclass
class GateDecision:
    accepted: bool
    reason: str
    unmet_rows: tuple[str, ...] = ()
    regressions: tuple[str, ...] = ()
    remaining_seconds: float = 0.0
    remaining_steps: int = 0
    refusals: int = 0
    directive: str = ""
    escaped: str = ""
    baseline_status: str = ""
    details: dict = field(default_factory=dict)

    def as_row(self) -> dict:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "unmet_rows": list(self.unmet_rows),
            "regressions": list(self.regressions),
            "remaining_seconds": round(self.remaining_seconds, 1),
            "remaining_steps": self.remaining_steps,
            "refusals": self.refusals,
            "escaped": self.escaped,
            "baseline_status": self.baseline_status,
        }


def budget_allows_refusal(remaining_seconds: float, remaining_steps: int) -> tuple[bool, str]:
    """Is there room for the agent to act on a refusal and submit again?"""
    if remaining_seconds < MIN_REMAINING_SECONDS:
        return False, "time"
    if remaining_steps < MIN_REMAINING_STEPS:
        return False, "steps"
    return True, ""


def decide(
    *,
    plan,
    unmet_rows: tuple[str, ...],
    regressions: tuple[str, ...],
    remaining_seconds: float,
    remaining_steps: int,
    refusals: int,
    baseline_status: str = "",
) -> GateDecision:
    """The whole gate policy, as a pure function of the facts.

    Kept free of session and adapter objects so the policy can be read and
    tested on its own; the caller supplies the numbers and applies the result.
    """
    common = {
        "remaining_seconds": remaining_seconds,
        "remaining_steps": remaining_steps,
        "refusals": refusals,
        "baseline_status": baseline_status,
    }
    if plan is None or not getattr(plan, "rows", ()):  # nothing to gate on
        return GateDecision(accepted=True, reason="no_plan", **common)
    if refusals >= MAX_REFUSALS:
        return GateDecision(
            accepted=True, reason="already_refused_once",
            unmet_rows=unmet_rows, regressions=regressions, **common,
        )
    blocking = tuple(unmet_rows) + tuple(regressions)
    if not blocking:
        return GateDecision(accepted=True, reason="complete", **common)
    allowed, escape = budget_allows_refusal(remaining_seconds, remaining_steps)
    if not allowed:
        return GateDecision(
            accepted=True, reason="budget_escape", escaped=escape,
            unmet_rows=unmet_rows, regressions=regressions, **common,
        )
    return GateDecision(
        accepted=False,
        reason="unmet_plan_rows" if unmet_rows else "baseline_regression",
        unmet_rows=unmet_rows,
        regressions=regressions,
        directive=render_directive(plan, unmet_rows, regressions),
        **common,
    )


def render_directive(
    plan, unmet_rows: tuple[str, ...], regressions: tuple[str, ...]
) -> str:
    """What the agent is told when the gate refuses.

    Names the rows and the command that would prove each, because a refusal
    that says only "obligations unmet" is not actionable. Says plainly that a
    second submit is accepted, so the gate can never be mistaken for a trap.
    """
    lines = [
        "GT PLAN GATE: submission was not executed. The plan built before the "
        "first edit still has requirements with no evidence. You may run any "
        "command, edit any file, or disagree; submitting again will be "
        "accepted either way.",
    ]
    if unmet_rows:
        lines.append("Requirements with no evidence yet:")
        for row_id in unmet_rows[:MAX_LISTED_ROWS]:
            row = plan.row(row_id) if hasattr(plan, "row") else None
            text = row.text if row is not None else row_id
            lines.append(f"- {row_id}: {text}")
            if row is not None and row.verification_command:
                lines.append(f"    prove with: {row.verification_command}")
        extra = len(unmet_rows) - MAX_LISTED_ROWS
        if extra > 0:
            lines.append(f"- ... and {extra} more")
    if regressions:
        lines.append(
            "Tests that passed before your edits and fail now - these were "
            "green when you arrived:"
        )
        for name in regressions[:MAX_LISTED_ROWS]:
            lines.append(f"- {name}")
    return "\n".join(lines)
