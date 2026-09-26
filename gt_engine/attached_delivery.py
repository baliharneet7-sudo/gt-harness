"""The ``attached`` GT delivery mode (HAR-93, GitNexus ``native_augment`` pattern).

``push`` (default) is the canonical delivery: host-selected evidence appended
to requests, the persistent plan, the submit gate, steers. ``attached`` keeps
every GT computation but changes how it reaches the agent:

* ``gt-*`` shell tools the agent chooses to call (``tool_server``);
* a ``[GT]`` block appended to the agent's own grep/rg/ag observation
  (``grep_augment``);
* nothing pushed, nothing blocked: the push pipeline runs in SHADOW, and the
  plan call, submit gate and churn abort are bypassed.

Per-edit freshness is kept: both surfaces read the graph through EngineState.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

DELIVERY_MODE_ENV = "GT_DELIVERY_MODE"
PUSH = "push"
ATTACHED = "attached"
DELIVERY_MODES = (PUSH, ATTACHED)

# Actions after a delivery in which reuse of its content counts as uptake.
UPTAKE_WINDOW_ACTIONS = 3
UPTAKE_METHOD = (
    "delivery-distinct path or identifier (absent from the triggering command) "
    f"appears in one of the next {UPTAKE_WINDOW_ACTIONS} agent actions"
)

_PATH_TOKEN = re.compile(r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+\.[A-Za-z0-9]{1,6}")
_NAME_TOKEN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]{3,})\s\(")


def delivery_mode(value: str | None = None) -> str:
    raw = (value if value is not None else os.environ.get(DELIVERY_MODE_ENV, "")).strip().lower()
    if raw in ("", PUSH):
        return PUSH
    if raw == ATTACHED:
        return ATTACHED
    raise ValueError(f"gt_delivery_mode_invalid:{raw}")


def is_attached() -> bool:
    return delivery_mode() == ATTACHED


def distinct_tokens(delivered: str, trigger: str) -> frozenset[str]:
    """Paths and symbol names the delivery introduced (not in its trigger)."""
    tokens = set(_PATH_TOKEN.findall(delivered)) | set(_NAME_TOKEN.findall(delivered))
    return frozenset(token for token in tokens if token not in trigger)


@dataclass
class _PendingDelivery:
    tokens: frozenset[str]
    remaining: int
    referenced: bool = False


@dataclass
class UptakeTracker:
    deliveries: int = 0
    referenced: int = 0
    _open: list[_PendingDelivery] = field(default_factory=list)

    def observe(self, command: str) -> None:
        still_open: list[_PendingDelivery] = []
        for pending in self._open:
            if any(token in command for token in pending.tokens):
                pending.referenced = True
                self.referenced += 1
                continue
            pending.remaining -= 1
            if pending.remaining > 0:
                still_open.append(pending)
        self._open = still_open

    def register(self, delivered: str, trigger: str) -> None:
        self.deliveries += 1
        tokens = distinct_tokens(delivered, trigger)
        if tokens:
            self._open.append(_PendingDelivery(tokens, UPTAKE_WINDOW_ACTIONS))

    def as_dict(self) -> dict[str, Any]:
        rate = round(self.referenced / self.deliveries, 4) if self.deliveries else 0.0
        return {
            "gt_context_deliveries": self.deliveries,
            "gt_context_referenced": self.referenced,
            "gt_context_referenced_rate": rate,
            "gt_context_referenced_method": UPTAKE_METHOD,
        }


class AttachedDelivery:
    """Owns the tool server, the grep augmenter and uptake accounting."""

    def __init__(self, session: "GTSession"):
        from gt_engine.grep_augment import GrepAugmenter
        from gt_engine.tool_server import ToolDispatcher

        self.session = session
        self.dispatcher = ToolDispatcher(session)
        self.augmenter = GrepAugmenter(session)
        self.uptake = UptakeTracker()
        self.server = None
        self.bin_dir: Path | None = None
        self._tool_texts_seen = 0

    def start(self, bin_dir: str | os.PathLike[str], env_config: dict[str, str] | None) -> None:
        from gt_engine.tool_server import ToolServer, install_wrappers

        self.server = ToolServer(self.dispatcher).start()
        self.bin_dir = Path(bin_dir)
        install_wrappers(self.bin_dir, self.server.url)
        if env_config is not None:
            base_path = env_config.get("PATH") or os.environ.get("PATH", "")
            env_config["PATH"] = f"{self.bin_dir}{os.pathsep}{base_path}" if base_path else str(self.bin_dir)
        store = getattr(getattr(self.session, "_engine", None), "store", None)
        if store is not None:
            store.append("gt_attached_started", url=self.server.url, bin_dir=str(self.bin_dir))

    def stop(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None

    def observe_turn(self, commands: Iterable[str | None], outputs: list[dict]) -> list[dict]:
        """Account uptake and append ``[GT]`` blocks to search observations.

        ``commands[i]`` is the shell command of action ``i`` (None for a
        non-shell action); ``outputs`` is index-aligned. Returns new outputs.
        """
        augmented = list(outputs)
        for index, command in enumerate(commands):
            if command is None or index >= len(augmented):
                continue
            self.uptake.observe(command)
            tool_texts = self.dispatcher.metrics.delivered_texts
            for text in tool_texts[self._tool_texts_seen:]:
                self.uptake.register(text, command)
            self._tool_texts_seen = len(tool_texts)
            block = self.augmenter.augment(command)
            if not block:
                continue
            self.uptake.register(block, command)
            result = dict(augmented[index])
            original = str(result.get("output") or "")
            result["output"] = f"{original}\n\n{block}" if original else block
            augmented[index] = result
        return augmented

    def metrics(self) -> dict[str, Any]:
        tools = self.dispatcher.metrics.as_dict()
        augment = self.augmenter.metrics.as_dict(self.augmenter.search_commands)
        return {
            "gt_delivery_mode": ATTACHED,
            **tools,
            **augment,
            "gt_search_commands": self.augmenter.search_commands,
            "gt_bytes_delivered": tools["gt_tool_bytes_delivered"] + augment["augment_bytes_delivered"],
            **self.uptake.as_dict(),
        }


# How each of the 21 audited GT features reaches the agent in attached mode.
# "substrate" features have no surface of their own: every graph answer is
# built from them. A test pins that every named surface exists and answers.
FEATURE_SURFACES: dict[str, tuple[str, ...]] = {
    "F1 parsing": ("substrate",),
    "F2 definitions": ("gt-def", "gt-context", "augment"),
    "F3 references": ("gt-refs",),
    "F4 callers/callees": ("gt-callers", "gt-context", "gt-impact", "augment"),
    "F5 direct call resolution": ("gt-calls",),
    "F6 callable values": ("gt-calls",),
    "F7 receiver/inheritance/overload": ("gt-shape",),
    "F8 framework/DI/middleware": ("gt-routes",),
    "F9 processes": ("gt-flows", "augment"),
    "F10 communities": ("gt-module",),
    "F11 hybrid retrieval": ("gt-query",),
    "F12 symbol context": ("gt-context", "augment"),
    "F13 patch impact / co-change": ("gt-changes", "gt-impact", "gt-cochange"),
    "F14 CFG": ("gt-slice",),
    "F15 reaching definitions": ("gt-slice",),
    "F16 control dependence": ("gt-slice",),
    "F17 PDG / slice": ("gt-slice",),
    "F18 routes / API impact": ("gt-routes", "gt-api"),
    "F19 taint": ("gt-taint",),
    "F20 test feedback / recovery": ("gt-verify", "gt-tests", "gt-check", "gt-failures"),
    "F21 freshness / amend": ("substrate",),
}


def attached_system_section() -> str:
    """The one prompt addition of the attached arm, appended to the stock
    system template. Short on purpose: it is paid on every request."""
    from gt_engine.tool_server import tool_reference

    return (
        "## Code intelligence (optional)\n\n"
        "GroundTruth keeps a code graph of this repository, updated after every edit. "
        "These shell commands answer in well under a second. Use them when they save "
        "you searching or reading; skip them when grep is enough.\n\n"
        f"{tool_reference()}\n\n"
        "`gt-help` lists more (routes and API clients, slices, taint, interface checks, "
        "renames, co-change, recurring failures).\n\n"
        "Your grep/rg/ag results may end with a `[GT]` block listing the definition, "
        "callers, callees and flows of the symbols you searched for. Graph facts are "
        "name-level: confirm by reading the code before editing."
    )


def push_metrics(adapter: Any) -> dict[str, Any]:
    return {
        "gt_delivery_mode": PUSH,
        "gt_bytes_delivered": int(getattr(adapter, "_model_visible_delivery_bytes", 0) or 0),
        "gt_deliveries": int(getattr(adapter, "_model_visible_delivery_count", 0) or 0),
    }


def delivery_report(adapter: Any) -> dict[str, Any]:
    attached = getattr(adapter, "attached_delivery", None) if adapter is not None else None
    if attached is not None:
        invalid = str(getattr(adapter, "attached_treatment_invalid", "") or "")
        return {
            **attached.metrics(),
            "treatment_valid": not invalid,
            "treatment_invalid_reason": invalid,
        }
    if adapter is None:
        return {"gt_delivery_mode": "off"}
    return push_metrics(adapter)


__all__ = [
    "ATTACHED",
    "AttachedDelivery",
    "DELIVERY_MODES",
    "DELIVERY_MODE_ENV",
    "FEATURE_SURFACES",
    "PUSH",
    "UPTAKE_METHOD",
    "UptakeTracker",
    "attached_system_section",
    "delivery_mode",
    "delivery_report",
    "distinct_tokens",
    "is_attached",
    "push_metrics",
]
