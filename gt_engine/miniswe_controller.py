"""Deterministic lifecycle controller for the Mini-SWE integration seam."""
from __future__ import annotations

import hashlib
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class LifecycleError(RuntimeError):
    pass


class PredicateStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    RED = "RED"
    GREEN = "GREEN"


@dataclass(frozen=True)
class Predicate:
    predicate_id: str
    description: str


@dataclass(frozen=True)
class Receipt:
    predicate_id: str
    command: str
    exit_code: int
    output_hash: str
    epoch: int
    status: PredicateStatus


class GroundtruthController:
    """Own lifecycle state while leaving action selection to Mini-SWE."""

    _TRANSITIONS = {
        "ORIENT": {"IMPLEMENT", "STUCK"},
        "IMPLEMENT": {"VERIFY", "STUCK"},
        "VERIFY": {"IMPLEMENT", "SUBMIT", "STUCK"},
        "SUBMIT": {"FINISHED", "IMPLEMENT", "STUCK"},
        "FINISHED": set(),
        "STUCK": set(),
    }

    def __init__(self, predicates: Iterable[Predicate], *, repeat_budget: int = 2):
        self.predicates = {p.predicate_id: p for p in predicates}
        self._status = {p.predicate_id: PredicateStatus.UNKNOWN for p in predicates}
        self._receipts: dict[str, Receipt] = {}
        self._phase = "ORIENT"
        self.workspace_epoch = 0
        self.repeat_budget = repeat_budget
        self._repeats: dict[str, int] = {}

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def unmet_predicates(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self._status.items() if v is not PredicateStatus.GREEN))

    def _transition(self, target: str) -> None:
        if target not in self._TRANSITIONS[self._phase]:
            raise LifecycleError(f"illegal transition {self._phase}->{target}")
        self._phase = target

    def start_task(self) -> None:
        if self._phase != "ORIENT":
            raise LifecycleError(f"task already started in {self._phase}")
        self._transition("IMPLEMENT")

    def begin_implement(self) -> None:
        if self._phase != "IMPLEMENT":
            self._transition("IMPLEMENT")

    def begin_verify(self) -> None:
        self._transition("VERIFY")

    def begin_submit(self) -> None:
        self._transition("SUBMIT")

    def note_edit(self, paths: Iterable[str]) -> None:
        if self._phase != "IMPLEMENT":
            raise LifecycleError(f"edit is illegal in {self._phase}")
        if list(paths):
            self.workspace_epoch += 1
            for key in self._status:
                self._status[key] = PredicateStatus.UNKNOWN
                self._receipts.pop(key, None)

    def record_receipt(self, predicate_id: str, command: str, exit_code: int,
                       output: str, *, epoch: int,
                       status: str | PredicateStatus | None = None) -> Receipt:
        if predicate_id not in self.predicates:
            raise LifecycleError(f"unknown predicate {predicate_id}")
        if epoch != self.workspace_epoch:
            raise LifecycleError("receipt epoch is stale")
        if status is None:
            parsed = (PredicateStatus.UNKNOWN if "unknown" in output.lower()
                      else PredicateStatus.GREEN if exit_code == 0
                      else PredicateStatus.RED)
        else:
            parsed = PredicateStatus(status)
        receipt = Receipt(
            predicate_id, command, exit_code,
            hashlib.sha256(output.encode("utf-8")).hexdigest(), epoch, parsed,
        )
        self._receipts[predicate_id] = receipt
        self._status[predicate_id] = parsed
        return receipt

    def predicate_status(self, predicate_id: str) -> PredicateStatus:
        return self._status[predicate_id]

    def submit_decision(self) -> bool:
        if self._phase != "SUBMIT":
            raise LifecycleError(
                f"submit decision requires VERIFY then SUBMIT, got {self._phase}"
            )
        accepted = not self.unmet_predicates
        self._transition("FINISHED" if accepted else "IMPLEMENT")
        return accepted

    def before_action(self, tool_kind: str, command: str) -> str:
        if self._phase in {"FINISHED", "STUCK"}:
            raise LifecycleError(f"tool action after {self._phase}")
        key = f"{self._phase}|{tool_kind}|{shlex.join(shlex.split(command))}"
        count = self._repeats.get(key, 0)
        if count > self.repeat_budget:
            self._phase = "STUCK"
            raise LifecycleError("repeat action budget exhausted")
        self._repeats[key] = count + 1
        return key

    def after_observation(self, output: str, *, diff_hash: str = "") -> None:
        if self._phase in {"FINISHED", "STUCK"}:
            raise LifecycleError(f"observation after {self._phase}")
        # The observation is deliberately not interpreted as GREEN. Predicates
        # can only change status through an explicit semantic receipt.
        _ = (output, diff_hash)

    def provider_suffix(self) -> str:
        unmet = ", ".join(self.unmet_predicates[:2]) or "none"
        return f"phase={self._phase}; unmet={unmet}; epoch={self.workspace_epoch}"
