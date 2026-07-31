"""Mini-SWE integration boundary with external state and provider receipts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .miniswe_controller import GroundtruthController, Predicate


@dataclass(frozen=True)
class ProviderDelivery:
    request_id: str
    iteration: int
    payload_sha256: str
    phase: str
    suffix: str


class ExternalStateStore:
    """Append-only state sink outside the Mini-SWE task workspace."""

    def __init__(self, root: str | Path, task_id: str):
        self.root = Path(root) / task_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"

    def append(self, event: str, **payload: Any) -> None:
        row = {"event": event, **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


class MiniSweAdapter(GroundtruthController):
    """Controller plus external state/provider-bound request witness.

    The adapter does not alter Mini-SWE's messages.  A caller supplies the final
    normalized payload, receives a request-bound receipt, then performs the actual
    provider call through Mini-SWE's native model object.
    """

    def __init__(self, *, task_id: str, state_dir: str | Path,
                 predicates: Iterable[Predicate], repeat_budget: int = 2):
        super().__init__(predicates, repeat_budget=repeat_budget)
        self.task_id = task_id
        self.store = ExternalStateStore(state_dir, task_id)
        self.iteration = 0
        self.deliveries: list[ProviderDelivery] = []
        self._last_payload_hash = ""

    def _record_state(self) -> None:
        self.store.append(
            "state",
            phase=self.phase,
            epoch=self.workspace_epoch,
            unmet=list(self.unmet_predicates),
            iteration=self.iteration,
        )

    def start_task(self) -> None:
        super().start_task()
        self._record_state()

    def begin_implement(self) -> None:
        super().begin_implement()
        self._record_state()

    def begin_verify(self) -> None:
        super().begin_verify()
        self._record_state()

    def begin_submit(self) -> None:
        super().begin_submit()
        self._record_state()

    def note_edit(self, paths: Iterable[str]) -> None:
        super().note_edit(paths)
        self._record_state()

    def bind_provider_payload(self, payload: Mapping[str, Any]) -> ProviderDelivery:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ValueError("provider payload requires messages")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        self.iteration += 1
        request_id = f"{self.task_id}-{self.iteration}-{digest[:16]}"
        suffix = self.provider_suffix()
        delivery = ProviderDelivery(request_id, self.iteration, digest, self.phase, suffix)
        self.deliveries.append(delivery)
        self._last_payload_hash = digest
        self.store.append(
            "provider_delivery",
            request_id=request_id,
            iteration=self.iteration,
            payload_sha256=digest,
            phase=self.phase,
            suffix=suffix,
        )
        return delivery

    def submit_decision(self) -> bool:
        accepted = super().submit_decision()
        self.store.append("submit_decision", accepted=accepted, phase=self.phase,
                          iteration=self.iteration)
        return accepted

    def final_state(self) -> dict[str, Any]:
        state = {"phase": self.phase, "epoch": self.workspace_epoch,
                 "unmet_predicates": list(self.unmet_predicates),
                 "iterations": self.iteration}
        self.store.append("final_state", **state)
        return state
