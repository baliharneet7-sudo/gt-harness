"""The ``attached`` GT delivery mode (HAR-93, GitNexus ``native_augment`` pattern).

``push`` (default) is the canonical delivery: host-selected evidence appended
to requests, the persistent plan, the submit gate, steers. ``attached`` keeps
every GT computation but changes how it reaches the agent:

* ``gt-*`` shell tools the agent chooses to call (``tool_server``);
* a ``[GT]`` block appended to the agent's own grep/rg/ag observation
  (``grep_augment``), and to its edits and failing test runs
  (``action_augment``);
* nothing pushed, nothing blocked: the push pipeline runs in SHADOW, and the
  plan call, submit gate and churn abort are bypassed.

Per-edit freshness is kept: both surfaces read the graph through EngineState.
"""
from __future__ import annotations

import os
import re
import sqlite3
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
        from gt_engine import wheel_perf
        from gt_engine.action_augment import ActionAugmenter
        from gt_engine.grep_augment import GrepAugmenter
        from gt_engine.tool_server import ToolDispatcher

        # Attached answers are paid on the agent's clock; the push arm keeps
        # the unmodified wheel path so the A/B control stays byte-identical.
        wheel_perf.install()
        self.session = session
        self.dispatcher = ToolDispatcher(session)
        self.augmenter = GrepAugmenter(session)
        self.action_augmenter = ActionAugmenter(session)
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

    plan_bytes_delivered: int = 0
    plan_features: tuple[str, ...] = ()

    #: Turns between delivery checkpoints into the metrics file (see
    #: scripts/miniswe_gt_run.py _checkpoint_report).
    CHECKPOINT_EVERY_TURNS = 5
    on_turn: Any = None
    _turns: int = 0

    def observe_turn(self, commands: Iterable[str | None], outputs: list[dict],
                     facts: list[dict | None] | None = None) -> list[dict]:
        """Account uptake and append ``[GT]`` blocks to action observations.

        ``commands[i]`` is the shell command of action ``i`` (None for a
        non-shell action); ``outputs`` and ``facts`` are index-aligned.
        ``facts[i]`` carries the action's recorded edit (``changes``,
        ``syntax``) and ``returncode``/``output``. Returns new outputs.
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
            block = self._block(command, (facts or [])[index] if index < len(facts or []) else None)
            if not block:
                continue
            self.uptake.register(block, command)
            result = dict(augmented[index])
            original = str(result.get("output") or "")
            result["output"] = f"{original}\n\n{block}" if original else block
            augmented[index] = result
        try:
            augmented = self._deliver_plan_once(commands, augmented)
        except Exception:  # noqa: BLE001 - the plan never costs the observation
            pass
        try:
            self._record_inventory()
        except Exception:  # noqa: BLE001 - observability never costs the observation
            pass
        self._turns += 1
        if self.on_turn is not None and self._turns % self.CHECKPOINT_EVERY_TURNS == 0:
            try:
                self.on_turn()
            except Exception:  # noqa: BLE001 - a checkpoint never costs a turn
                pass
        return augmented

    def _deliver_plan_once(self, commands: Iterable[str | None], outputs: list[dict]) -> list[dict]:
        """Append the task plan to this turn's first shell observation, once,
        as soon as a current graph exists (see ``attached_plan``)."""
        from gt_engine.tool_server import EXIT_ANSWER, plan_holder

        if getattr(self, "session", None) is None:
            return outputs
        holder = plan_holder(self.session)
        if holder.delivered or holder.failed:
            return outputs
        index = next((i for i, command in enumerate(commands) if command is not None), None)
        plan = holder.get() if index is not None and index < len(outputs) else None
        if plan is None:
            return outputs
        holder.delivered = True
        if not plan.worth_showing:
            store = getattr(getattr(self.session, "_engine", None), "store", None)
            if store is not None:
                store.append("attached_plan_withheld", reason="no_requirement_anchored_and_no_related_code")
            return outputs
        text, code = self.dispatcher.render("gt-plan", [])
        if code != EXIT_ANSWER:
            return outputs
        self.plan_features = plan.features
        self.plan_bytes_delivered = len(text.encode("utf-8"))
        self.uptake.register(text, "")
        result = dict(outputs[index])
        original = str(result.get("output") or "")
        result["output"] = f"{original}\n\n{text}" if original else text
        return [*outputs[:index], result, *outputs[index + 1:]]

    feature_inventory: dict[str, int] = {}
    _inventory_graph: str = ""

    def _record_inventory(self) -> None:
        """Journal what the repository's graph holds per feature, once per
        adopted graph (``feature_trace``)."""
        from gt_engine.feature_trace import inventory

        state = getattr(getattr(self.session, "_engine", None), "engine_state", None)
        graph = str(getattr(state, "graph_path", "") or "")
        if not graph or graph == self._inventory_graph or self.feature_inventory:
            return
        conn = sqlite3.connect(Path(graph).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            self.feature_inventory = inventory(conn)
        finally:
            conn.close()
        self._inventory_graph = graph
        store = getattr(getattr(self.session, "_engine", None), "store", None)
        if store is not None:
            store.append("gt_feature_inventory", counts=self.feature_inventory)

    def features_reached(self) -> dict[str, int]:
        """Deliveries per feature across every attached surface."""
        from gt_engine.feature_trace import merge

        tool_features: dict[str, int] = {}
        for tool, count in (self.dispatcher.metrics.as_dict().get("gt_tool_calls_by_name") or {}).items():
            for feature, surfaces in FEATURE_SURFACES.items():
                if tool in surfaces:
                    fid = feature.split()[0]
                    tool_features[fid] = tool_features.get(fid, 0) + int(count or 0)
        substrate = {"F1": 1, "F21": 1} if self.feature_inventory.get("F2") else {}
        return merge(self.augmenter.metrics.features, self.action_augmenter.metrics.features,
                     self.plan_features, tool_features, substrate)

    def _wake_on_new_source(self, changes: dict) -> None:
        """An edit that writes source into a graph-less workspace starts the
        (background, never blocking) build. Only searches used to: TB2
        db-wal-recovery (run 36351259430) wrote fix_wal.py, never searched,
        and got no GT for the whole task."""
        from gt_engine.indexer import SOURCE_EXTS
        from gt_engine.tool_server import refresh_if_stale

        state = getattr(getattr(self.session, "_engine", None), "engine_state", None)
        if state is not None and getattr(state, "graph_path", ""):
            return
        if any(Path(str(path)).suffix.lower() in SOURCE_EXTS for path in changes):
            try:
                refresh_if_stale(self.session, passive=True)
            except Exception:  # noqa: BLE001 - waking the graph never costs the action
                pass

    def _block(self, command: str, facts: dict | None) -> str:
        """Search, edit and failure blocks for one action, in that order."""
        blocks = [self.augmenter.augment(command)]
        if facts:
            if facts.get("changes"):
                self._wake_on_new_source(facts["changes"])
                blocks.append(self.action_augmenter.after_edit(
                    facts["changes"], facts.get("syntax") or (), str(facts.get("pre_edit_graph") or "")))
            blocks.append(self.action_augmenter.after_failure(
                command, str(facts.get("output") or ""), facts.get("returncode"),
                str(facts.get("test_outcome") or "")))
        return "\n\n".join(block for block in blocks if block)

    def metrics(self) -> dict[str, Any]:
        tools = self.dispatcher.metrics.as_dict()
        augment = self.augmenter.metrics.as_dict(self.augmenter.search_commands)
        actions = self.action_augmenter.metrics.as_dict()
        return {
            "gt_delivery_mode": ATTACHED,
            **tools,
            **augment,
            **actions,
            "gt_plan_delivered": plan_holder_delivered(self.session),
            "gt_plan_bytes_delivered": self.plan_bytes_delivered,
            "gt_plan_features": list(self.plan_features),
            "features_reached": self.features_reached(),
            "feature_inventory": dict(self.feature_inventory),
            "gt_search_commands": self.augmenter.search_commands,
            "gt_bytes_delivered": (tools["gt_tool_bytes_delivered"] + augment["augment_bytes_delivered"]
                                   + actions["action_augment_bytes_delivered"] + self.plan_bytes_delivered),
            **self.uptake.as_dict(),
        }


def plan_holder_delivered(session: "GTSession") -> bool:
    holder = getattr(getattr(session, "_engine", None), "attached_plan", None)
    return bool(getattr(holder, "delivered", False))


# How each of the 21 audited GT features reaches the agent in attached mode.
# "substrate" features have no surface of their own: every graph answer is
# built from them. A test pins that every named surface exists and answers.
FEATURE_SURFACES: dict[str, tuple[str, ...]] = {
    "F1 parsing": ("substrate", "edit-augment"),
    "F2 definitions": ("gt-def", "gt-context", "augment"),
    "F3 references": ("gt-refs", "augment"),
    "F4 callers/callees": ("gt-callers", "gt-context", "gt-impact", "augment", "edit-augment"),
    "F5 direct call resolution": ("gt-calls", "augment"),
    "F6 callable values": ("gt-calls", "augment"),
    "F7 receiver/inheritance/overload": ("gt-shape", "gt-calls", "augment"),
    "F8 framework/DI/middleware": ("gt-routes", "augment"),
    "F9 processes": ("gt-flows", "augment"),
    "F10 communities": ("gt-module", "augment"),
    "F11 hybrid retrieval": ("gt-query", "plan"),
    "F12 symbol context": ("gt-context", "augment"),
    "F13 patch impact / co-change": ("gt-changes", "gt-impact", "gt-cochange", "augment", "edit-augment"),
    "F14 CFG": ("gt-slice", "failure-augment"),
    "F15 reaching definitions": ("gt-slice", "failure-augment"),
    "F16 control dependence": ("gt-slice", "failure-augment"),
    "F17 PDG / slice": ("gt-slice", "failure-augment"),
    "F18 routes / API impact": ("gt-routes", "gt-api", "augment", "edit-augment"),
    "F19 taint": ("gt-taint", "edit-augment"),
    "F20 test feedback / recovery": ("gt-verify", "gt-tests", "gt-check", "gt-failures",
                                     "edit-augment", "failure-augment"),
    "F21 freshness / amend": ("substrate",),
}


def attached_system_section() -> str:
    """The one prompt addition of the attached arm, appended to the stock
    system template. Short on purpose: it is paid on every request."""
    from gt_engine.tool_server import tool_reference

    # Modelled on GitNexus's "when to use what" table: the first GT-on runs
    # (runs 36303712349/36303714218/36303715831) made 0 tool calls in 11
    # tasks under a prompt that said "skip them when grep is enough", so only
    # grep augmentation ever reached the agent. The commands stay optional -
    # nothing is enforced - but each is tied to the moment it pays off.
    return (
        "## Code intelligence\n\n"
        "GroundTruth keeps a code graph of this repository, updated after every edit. "
        "These shell commands answer in well under a second and replace several "
        "grep/cat rounds each:\n\n"
        "| When you need to | Run |\n"
        "|---|---|\n"
        "| find where the task's behaviour lives | `gt-query \"<words from the issue>\"` |\n"
        "| understand a function before touching it | `gt-context <symbol>` |\n"
        "| know what breaks if you change it | `gt-impact <symbol>` |\n"
        "| pick the tests to run for a file | `gt-tests <file>` |\n"
        "| check your edits before submitting | `gt-changes` |\n\n"
        f"{tool_reference()}\n\n"
        "`gt-help` lists more (routes and API clients, slices, taint, interface checks, "
        "renames, co-change, recurring failures).\n\n"
        "Your grep/rg/ag results may end with a `[GT]` block about the symbols you searched "
        "for (definition, callers, callees, flows, references, overrides, routes, module). "
        "After an edit, a `[GT]` block lists the functions you changed, their callers and "
        "the tests that reach them; after a failing test run, where it failed and the lines "
        "that value depends on. A `[GT] task plan` ties the issue's lines to the code they "
        "name (run gt-plan to see it again). Graph facts are name-level: confirm by reading the code."
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
