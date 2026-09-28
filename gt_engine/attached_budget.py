"""Per-task delivery budget: say each thing once, spend bytes where they pay.

Every attached block is appended to an observation that stays in the
conversation and is re-sent on every later turn, so a byte delivered early
is paid many times. On the round-5 losses (run 36359464192) GT-on used
5-63% more input tokens than the GT-off baseline on 5 of 7 tasks while
delivering 19-40 KB per task, much of it repeated (the same symbol's
callers, the same module line, the same "next:" hint).

``DeliveryBudget`` is the one place those decisions are made:

* a fact already shown in this task is not shown again;
* ``hint_allowed()``: the "next:" tool pointer is offered a few times, not
  on every block;
* ``compact``: past ``FULL_DETAIL_BYTES`` a block keeps its first line and
  counts, replacing lower-value detail instead of appending it (HAR-94's
  "replace, don't expand").

"Shown" means present in the text the agent received. A block is built as a
``Draft``: facts are *staged* with the exact text that carries them, and the
draft is committed against the final delivered text. A fact dropped by a
display cap, by ``compact_lines`` or by ``cap_text`` truncation is therefore
never recorded, and a later "shown earlier" can never point at something the
agent did not see. A draft that is not delivered (silent block, error) is
simply discarded.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field

FULL_DETAIL_BYTES = int(os.environ.get("GT_ATTACHED_FULL_DETAIL_BYTES", "12000"))
HINTS_SHOWN = 3


@dataclass
class DeliveryBudget:
    spent: int = 0
    hints: int = 0
    suppressed: int = 0
    _seen: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def draft(self) -> "Draft":
        return Draft(self)

    def was_shown(self, key: str) -> bool:
        with self._lock:
            return key in self._seen

    def hint_allowed(self) -> bool:
        with self._lock:
            if self.hints >= HINTS_SHOWN:
                return False
            self.hints += 1
            return True

    @property
    def compact(self) -> bool:
        return self.spent >= FULL_DETAIL_BYTES


class Draft:
    """The facts one block would carry, recorded only once delivered."""

    def __init__(self, budget: DeliveryBudget):
        self.budget = budget
        self._staged: dict[str, str] = {}
        self.suppressed = 0

    def is_new(self, key: str) -> bool:
        """False if ``key`` was delivered earlier in the task, or is already
        staged in this block; each such repeat counts as suppressed."""
        if key in self._staged or self.budget.was_shown(key):
            self.suppressed += 1
            return False
        return True

    def stage(self, key: str, carrier: str) -> None:
        """``carrier`` is the exact text that will show ``key`` to the agent."""
        if carrier:
            self._staged.setdefault(key, carrier)

    def commit(self, delivered: str) -> None:
        """Record every staged fact whose carrier survived into ``delivered``,
        and charge the delivered bytes."""
        with self.budget._lock:
            for key, carrier in self._staged.items():
                if carrier in delivered:
                    self.budget._seen.add(key)
            self.budget.suppressed += self.suppressed
            self.budget.spent += len(delivered.encode("utf-8"))
        self._staged.clear()
        self.suppressed = 0


def compact_lines(lines: list[str], keep: int = 2, always: "re.Pattern[str] | None" = None) -> list[str]:
    """The first ``keep`` lines, every line matching ``always``, and a count
    of what was left out."""
    kept = [line for index, line in enumerate(lines)
            if index < keep or (always is not None and always.search(line))]
    dropped = len(lines) - len(kept)
    if not dropped:
        return lines
    return [*kept, f"  (+{dropped} more line(s); GT detail budget reached)"]


__all__ = ["DeliveryBudget", "Draft", "FULL_DETAIL_BYTES", "compact_lines"]
