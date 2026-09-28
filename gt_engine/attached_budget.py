"""Per-task delivery budget: say each thing once, spend bytes where they pay.

Every attached block is appended to an observation that stays in the
conversation and is re-sent on every later turn, so a byte delivered early
is paid many times. On the round-5 losses (run 36359464192) GT-on used
5-63% more input tokens than the GT-off baseline on 5 of 7 tasks while
delivering 19-40 KB per task, much of it repeated (the same symbol's
callers, the same module line, the same "next:" hint).

``DeliveryBudget`` is the one place those decisions are made:

* ``seen(key)``: a fact already shown in this task is not shown again;
* ``hint_allowed()``: the "next:" tool pointer is offered a few times, not
  on every block;
* ``compact``: past ``FULL_DETAIL_BYTES`` a block keeps its first line and
  counts, replacing lower-value detail instead of appending it (HAR-94's
  "replace, don't expand").
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

FULL_DETAIL_BYTES = int(os.environ.get("GT_ATTACHED_FULL_DETAIL_BYTES", "12000"))
HINTS_SHOWN = 3


@dataclass
class DeliveryBudget:
    spent: int = 0
    hints: int = 0
    _seen: set[str] = field(default_factory=set)
    suppressed: int = 0

    def seen(self, key: str) -> bool:
        """True if ``key`` was already delivered; records it otherwise."""
        if key in self._seen:
            self.suppressed += 1
            return True
        self._seen.add(key)
        return False

    def hint_allowed(self) -> bool:
        if self.hints >= HINTS_SHOWN:
            return False
        self.hints += 1
        return True

    @property
    def compact(self) -> bool:
        return self.spent >= FULL_DETAIL_BYTES

    def charge(self, text: str) -> None:
        self.spent += len(text.encode("utf-8"))


def compact_lines(lines: list[str], keep: int = 2) -> list[str]:
    """First ``keep`` lines plus a count of what was left out."""
    if len(lines) <= keep:
        return lines
    return [*lines[:keep], f"  (+{len(lines) - keep} more line(s); GT detail budget reached)"]


__all__ = ["DeliveryBudget", "FULL_DETAIL_BYTES", "compact_lines"]
