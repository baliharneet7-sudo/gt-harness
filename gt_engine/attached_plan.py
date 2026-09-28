"""The task plan in attached delivery: built once, shown once, re-readable.

The push arm's persistent plan spends a planning provider call, runs the
repository's suite for a baseline, merges its rows into the task contract, and
gates submission on them - and the gate is what cost TB2 (every submission
refused under an unverifiable row). What was never shown to hurt is the plan's
substance: the issue's own requirement lines, each tied to the code it names
on the verified graph, in callee-before-caller order, with the tests that
reach those files.

Attached delivery keeps exactly that substance and none of the control:

* built deterministically from the issue text and the first current graph
  (no provider call, no baseline run, no contract merge);
* appended ONCE to the first observation after it exists;
* re-readable at any time with ``gt-plan``;
* never gates, never steers, never updates itself into the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gt_engine.gt_session import GTSession

MAX_ROWS_SHOWN = 12
MAX_ROW_CHARS = 220
MAX_ANCHORS_PER_ROW = 3
MAX_CALLERS_PER_ANCHOR = 3
MAX_TESTS_SHOWN = 6


@dataclass(frozen=True)
class AttachedPlan:
    requirements: tuple[dict[str, Any], ...]
    tests: tuple[dict[str, Any], ...]
    rows_total: int
    anchored_rows: int
    graph_revision: str
    # F11: the hybrid (lexical + dense) rank of the code for the issue text.
    # Attached runs computed it on every turn in shadow (runs 3633*: 30-104
    # shadow_task_start_localization rows per task) and never showed it.
    related: tuple[dict[str, Any], ...] = ()
    # Framework wiring (routes, middleware, injection) and sink reach of the
    # anchored code: F8/F18/F19 surface only when the agent happens to search
    # or edit a handler; the plan is the one delivery every task gets early.
    wiring: tuple[dict[str, Any], ...] = ()
    wiring_features: tuple[str, ...] = ()

    @property
    def features(self) -> tuple[str, ...]:
        found = ["F2", "F4"] if self.anchored_rows else []
        if self.related:
            found.append("F11")
        if self.tests:
            found.append("F20")
        found += [f for f in self.wiring_features if f not in found]
        return tuple(found)

    @property
    def worth_showing(self) -> bool:
        """A plan whose requirements name no code is the issue text again
        (TB2 extract-elf: six rows, every one "no code anchor")."""
        return bool(self.anchored_rows or self.related)

    def as_answer(self) -> dict[str, Any]:
        answer: dict[str, Any] = {"requirements (from the issue, in suggested edit order)":
                                  list(self.requirements)}
        if self.related:
            answer["code most related to the issue (hybrid lexical + semantic rank)"] = list(self.related)
        if self.wiring:
            answer["graph facts about the anchored code (dispatch, call resolution, flows, "
                   "routes, injection, sinks)"] = list(self.wiring)
        if self.tests:
            answer["tests reaching the anchored code"] = list(self.tests)
        return answer


def _row_entry(row: Any, anchors: tuple[Any, ...], callers: dict[int, tuple[Any, ...]],
               index: int) -> dict[str, Any]:
    text = " ".join(str(row.text).split())
    if len(text) > MAX_ROW_CHARS:
        text = text[:MAX_ROW_CHARS - 3] + "..."
    entry: dict[str, Any] = {"name": f"R{index}: {text}"}
    if not anchors:
        entry["name"] += "  -> no code anchor in the graph (locate it yourself)"
        return entry
    shown = []
    for anchor in anchors[:MAX_ANCHORS_PER_ROW]:
        callers_of = [caller.name for caller in callers.get(anchor.node_id, ())][:MAX_CALLERS_PER_ANCHOR]
        called_by = f", called by {', '.join(callers_of)}" if callers_of else ""
        shown.append(f"{anchor.qualified_name or anchor.name} ({anchor.file_path}:{anchor.start_line}{called_by})")
    entry["name"] += "  -> " + "; ".join(shown)
    return entry


def build_attached_plan(session: "GTSession", issue_text: str) -> AttachedPlan | None:
    """None while no current graph exists (the caller retries later)."""
    from gt_engine.capabilities._query import graph_db_path
    from gt_engine.persistent_plan.anchors import build_anchor_result
    from gt_engine.persistent_plan.ledger import build_requirement_ledger
    from gt_engine.tool_server import _tests_by_reachability

    graph = graph_db_path(session)
    if not graph or not issue_text.strip():
        return None
    ledger = build_requirement_ledger(issue_text)
    if not ledger.rows:
        return None
    anchors = build_anchor_result(graph, ledger)
    by_id = {row.row_id: row for row in ledger.rows}
    order = [row_id for row_id in anchors.edit_order if row_id in by_id]
    order += [row.row_id for row in ledger.rows if row.row_id not in order]
    requirements = tuple(
        _row_entry(by_id[row_id], tuple(anchors.anchors.get(row_id, ())), anchors.callers, index)
        for index, row_id in enumerate(order[:MAX_ROWS_SHOWN], start=1)
    )
    if len(order) > MAX_ROWS_SHOWN:
        requirements += ({"name": f"... {len(order) - MAX_ROWS_SHOWN} more requirement line(s) in the issue"},)
    files = sorted({anchor.file_path for items in anchors.anchors.values() for anchor in items
                    if anchor.file_path})
    tests = tuple(_tests_by_reachability(session, files)[:MAX_TESTS_SHOWN]) if files else ()
    engine = getattr(session, "_engine", None)
    return AttachedPlan(
        requirements=requirements,
        tests=tests,
        rows_total=len(ledger.rows),
        anchored_rows=anchors.anchored_rows(),
        graph_revision=str(getattr(getattr(engine, "engine_state", None), "graph_source_revision", "") or ""),
        related=_related_code(session, issue_text),
        **_wiring(graph, [anchor for items in anchors.anchors.values() for anchor in items], session),
    )


MAX_WIRING_SHOWN = 14
MAX_WIRING_ANCHORS = 40  # indexed lookups only; flows are capped separately
MAX_FLOW_ANCHORS = 3


def _wiring(graph: str, anchors: list[Any], session: "GTSession | None" = None) -> dict[str, Any]:
    """What the graph knows about the anchored symbols beyond their callers.

    Live full runs (run 36359464192, 62 graphs) showed these features present
    in the graph but never delivered on 17-31 tasks each, because they surface
    only when the agent happens to search or edit the one symbol that carries
    them: dispatch (F7, 31 tasks), sink reach (F19, 31), frameworks (F8, 28),
    flows (F9, 26), function values (F6, 21), routes (F18, 17). The plan is
    the one delivery every task gets, and the anchored symbols are the ones
    the issue names, so each fact here is about code the task is about."""
    import sqlite3

    from gt_engine.action_augment import _reached_sinks
    from gt_engine.graph_facts import _dispatch, _framework, _guarded, _resolution, _resolution_mix

    found: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def add(anchor: Any, text: str, *carried: str) -> None:
        found.append((tuple(f for f in carried if f),
                      {"file_path": anchor.file_path, "line": anchor.start_line,
                       "name": f"{anchor.qualified_name or anchor.name} {text}"}))

    distinct: list[Any] = []
    for anchor in anchors:
        if anchor.node_id not in {a.node_id for a in distinct}:
            distinct.append(anchor)
    distinct = distinct[:MAX_WIRING_ANCHORS]
    try:
        conn = sqlite3.connect(Path(graph).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        for anchor in distinct:
            for fact in _guarded(lambda: _framework(conn, anchor.node_id)) or ():
                add(anchor, fact, *(("F8", "F18") if fact.startswith("handles route") else ("F8",)))
            for fact in _guarded(lambda: _dispatch(conn, anchor.node_id, anchor.label or "")) or ():
                add(anchor, fact, "F7")
            mix = _guarded(lambda: _resolution_mix(conn, anchor.node_id))
            if mix and set(mix[0].split()) - {"F5"}:  # only direct calls: nothing to add
                add(anchor, mix[1], *mix[0].split())
            resolution = _guarded(lambda: _resolution(conn, anchor.node_id))
            if resolution and "function value" in resolution:
                add(anchor, resolution, "F5", "F6")
            sinks = _guarded(lambda: _reached_sinks(conn, anchor.node_id))
            if sinks:
                add(anchor, f"reaches sink-like call(s): {', '.join(sinks)}", "F19")
    finally:
        conn.close()
    for anchor in distinct[:MAX_FLOW_ANCHORS] if session is not None else ():
        for flow in _flows(session, anchor):
            add(anchor, f"is in flow: {flow}", "F9")
    rows = _one_of_each_first(found, MAX_WIRING_SHOWN)
    features: list[str] = []
    for carried, row in found:
        if any(row is kept for kept in rows):
            features.extend(f for f in carried if f not in features)
    return {"wiring": tuple(rows), "wiring_features": tuple(features)}


def _one_of_each_first(found: list[tuple[tuple[str, ...], dict[str, Any]]],
                       limit: int) -> list[dict[str, Any]]:
    """Up to ``limit`` rows, taking one of each kind of fact (its feature set)
    before a second of any kind, in discovery order: seven overriders of one
    method must not crowd out the only sink or route row."""
    kinds: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for carried, row in found:
        kinds.setdefault(carried, []).append(row)
    chosen: list[dict[str, Any]] = []
    depth = 0
    while len(chosen) < limit and any(len(rows) > depth for rows in kinds.values()):
        for rows in kinds.values():
            if len(rows) > depth and len(chosen) < limit:
                chosen.append(rows[depth])
        depth += 1
    order = {id(row): index for index, (_c, row) in enumerate(found)}
    return sorted(chosen, key=lambda row: order[id(row)])


def _flows(session: "GTSession", anchor: Any) -> list[str]:
    """F9: detected entry-to-terminal flows through the anchored symbol."""
    from gt_engine.capabilities import structure
    from gt_engine.grep_augment import MAX_FLOWS_SHOWN

    try:
        result = structure.symbol_context(session, anchor.qualified_name or anchor.name)
    except Exception:  # noqa: BLE001 - flows are advisory
        return []
    answer = result.answer if isinstance(result.answer, dict) else {}
    definition = answer.get("definition") if isinstance(answer.get("definition"), dict) else {}
    if definition.get("file_path") not in (None, anchor.file_path):
        return []  # a same-named symbol elsewhere; its flows are not this anchor's
    out = []
    for flow in (answer.get("flows") or [])[:MAX_FLOWS_SHOWN]:
        text = (flow.get("display_label") or flow.get("label")) if isinstance(flow, dict) else flow
        if text:
            out.append(str(text))
    return out


MAX_RELATED_SHOWN = 6
_RELATED_QUERY_CHARS = 1_000


def _related_code(session: "GTSession", issue_text: str) -> tuple[dict[str, Any], ...]:
    """Top non-test code for the issue from the certified hybrid rank."""
    from gt_engine.capabilities import localization
    from gt_engine.tool_server import _QUERY_CANDIDATES, _shape_query

    try:
        result = localization.hybrid_rank(session, " ".join(issue_text.split())[:_RELATED_QUERY_CHARS],
                                          k=_QUERY_CANDIDATES)
    except Exception:  # noqa: BLE001 - the rank is advisory
        return ()
    shaped = _shape_query(result.answer, [])
    rows = shaped.get("1 source") if isinstance(shaped, dict) else None
    return tuple(row for row in rows or () if row.get("file_path"))[:MAX_RELATED_SHOWN]


class AttachedPlanHolder:
    """Builds the plan on the first read that finds a current graph, then
    keeps that capture: the plan is about the code the task started from."""

    def __init__(self, session: "GTSession"):
        self.session = session
        self.plan: AttachedPlan | None = None
        self.delivered = False
        self.failed = ""

    def _issue_text(self) -> str:
        return str(getattr(getattr(self.session, "_engine", None), "issue_text", "") or "")

    def get(self) -> AttachedPlan | None:
        if self.plan is None and not self.failed:
            try:
                self.plan = build_attached_plan(self.session, self._issue_text())
            except Exception as exc:  # noqa: BLE001 - the plan is advisory
                self.failed = f"{type(exc).__name__}: {exc}"[:200]
                self._journal("attached_plan_unavailable", error=self.failed)
                return None
            if self.plan is not None:
                self._journal("attached_plan_built", rows=self.plan.rows_total,
                              anchored_rows=self.plan.anchored_rows, tests=len(self.plan.tests),
                              graph_revision=self.plan.graph_revision,
                              features=list(self.plan.features))
        return self.plan

    def _journal(self, event: str, **row: Any) -> None:
        store = getattr(getattr(self.session, "_engine", None), "store", None)
        if store is not None:
            try:
                store.append(event, **row)
            except Exception:  # noqa: BLE001 - journaling never fails the action
                pass


__all__ = ["AttachedPlan", "AttachedPlanHolder", "build_attached_plan"]
