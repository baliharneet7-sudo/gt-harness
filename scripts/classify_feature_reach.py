"""Why each of the 21 GT features did or did not reach the agent, per task.

For every task under ``--root`` (a downloaded run: ``agent/miniswe_report.json``
+ ``agent/events.jsonl`` + the task's published graphs) each feature gets ONE
category, decided from recorded evidence only:

REACHED            a delivery the agent saw carried it (tagged augment/edit/
                   failure block, or a gt-* tool answer that serves it)
NO_GRAPH           the task never had a graph (index failed / not applicable)
NOT_IN_REPO        the repository's graph holds none of what the feature
                   reports (no routes, no overrides, no co-change history ...)
TOOL_ONLY_UNCALLED only a gt-* tool serves it and the agent never called one
NO_TRIGGER         data exists, but the agent never took the action that
                   surfaces it (no failing test run, no edit, no search)
DARK               the triggering action happened and the repo has the data,
                   but no delivery carried it (the searched/edited/failing
                   symbols had none of it, or the block was silent)
DEGRADED           GT itself withheld it: over budget, stale-graph silence,
                   augmentation errors

The graph checks count the producer's own tables on the task's largest
published revision; nothing is inferred from logs or model text.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gt_engine.attached_delivery import FEATURE_SURFACES  # noqa: E402

FEATURES = list(FEATURE_SURFACES)
TOOL_FEATURES: dict[str, set[str]] = {}
for _feature, _surfaces in FEATURE_SURFACES.items():
    for _surface in _surfaces:
        if _surface.startswith("gt-"):
            TOOL_FEATURES.setdefault(_surface, set()).add(_feature.split()[0])

# What each feature needs in the graph to have anything to say (SQL -> count).
APPLICABILITY: dict[str, str] = {
    "F1": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method','Class')",
    "F2": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method','Class','Interface')",
    "F3": "SELECT COUNT(*) FROM edges WHERE type IN ('CALLS','ACCESSES','READS','WRITES','INJECTS','IMPORTS')",
    "F4": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS'",
    "F5": "SELECT COUNT(*) FROM edges WHERE type = 'SELECTED_TARGET'",
    "F6": "SELECT COUNT(*) FROM nodes WHERE label = 'Callsite' AND dispatch_form = 'function_value'",
    "F7": "SELECT COUNT(*) FROM edges WHERE type IN ('OVERRIDES','METHOD_OVERRIDES','EXTENDS','IMPLEMENTS','DECLARED_IMPLEMENTS')",
    "F8": "SELECT COUNT(*) FROM edges WHERE type IN ('HANDLES_ROUTE','MIDDLEWARE_ON','INJECTS')",
    "F9": "SELECT COUNT(*) FROM processes",
    "F10": "SELECT COUNT(*) FROM communities",
    "F11": "SELECT COUNT(*) FROM nodes",
    "F12": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method','Class')",
    "F13": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS'",
    "F14": "SELECT COUNT(*) FROM cfg_blocks",
    "F15": "SELECT COUNT(*) FROM cfg_blocks",
    "F16": "SELECT COUNT(*) FROM cfg_blocks",
    "F17": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method')",
    "F18": "SELECT COUNT(*) FROM edges WHERE type IN ('HANDLES_ROUTE','API_CALL')",
    "F19": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS'",
    "F20": "SELECT COUNT(*) FROM nodes WHERE is_test = 1",
    "F21": "SELECT COUNT(*) FROM nodes",
}
# Passive surfaces and the agent action that triggers them.
EDIT_FEATURES = {"F1", "F13", "F18", "F19", "F20", "F4"}
FAILURE_FEATURES = {"F14", "F15", "F16", "F17", "F20"}
GREP_FEATURES = {"F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F12", "F13", "F18"}
# The Python persisted-CFG gap: F14-F16 facades abstain on Python, but the
# failure block's slice (F14-F17) runs on the runtime ast CFG.
SLICE_FEATURES = {"F14", "F15", "F16", "F17"}


def _events(agent_dir: Path) -> list[dict[str, Any]]:
    path = agent_dir / "events.jsonl"
    if not path.is_file():
        found = sorted(agent_dir.rglob("events.jsonl"))
        path = found[0] if found else path
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _graph_counts(agent_dir: Path) -> dict[str, int] | None:
    graphs = sorted((p for p in agent_dir.rglob("graph.db") if "revisions" in p.parts),
                    key=lambda p: p.stat().st_size, reverse=True)
    if not graphs:
        return None
    conn = sqlite3.connect(graphs[0].resolve().as_uri() + "?mode=ro", uri=True)
    counts: dict[str, int] = {}
    try:
        for feature, sql in APPLICABILITY.items():
            try:
                counts[feature] = int(conn.execute(sql).fetchone()[0])
            except sqlite3.Error:
                counts[feature] = 0
        try:
            counts["cochange_rows"] = int(conn.execute("SELECT COUNT(*) FROM cochanges").fetchone()[0])
        except sqlite3.Error:
            counts["cochange_rows"] = 0
        counts["languages"] = dict(conn.execute(
            "SELECT language, COUNT(*) FROM nodes WHERE label IN ('Function','Method')"
            " GROUP BY language ORDER BY 2 DESC LIMIT 3").fetchall())  # type: ignore[assignment]
    finally:
        conn.close()
    return counts


def _num(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def classify_task(agent_dir: Path) -> dict[str, Any]:
    report = json.loads((agent_dir / "miniswe_report.json").read_text(encoding="utf-8"))
    delivery = report.get("gt_delivery") or {}
    events = _events(agent_dir)
    graph = _graph_counts(agent_dir)
    augment = Counter(str(r.get("outcome")).split(":")[0] for r in events if r.get("event") == "gt_augment")
    action = [r for r in events if r.get("event") == "gt_action_augment"]
    edit_rows = [r for r in action if r.get("kind") == "edit"]
    tests = [r for r in events if r.get("event") == "execution_evidence" and r.get("kind") == "test"]
    failing_tests = [r for r in tests if r.get("observed_test_outcome") in ("fail", "env_fail")
                     or _num(r.get("returncode")) != 0]
    tool_calls = Counter(str(r.get("tool")) for r in events if r.get("event") == "gt_tool_call"
                         and str(r.get("exit_code")) == "0")
    reached: dict[str, list[str]] = {}
    for feature, count in (delivery.get("augment_features") or {}).items():
        if _num(count):
            reached.setdefault(feature, []).append(f"grep x{count}")
    for feature, count in (delivery.get("action_augment_features") or {}).items():
        if _num(count):
            reached.setdefault(feature, []).append(f"edit/failure x{count}")
    for feature in delivery.get("gt_plan_features") or ():
        reached.setdefault(feature, []).append("task plan")
    for tool, count in tool_calls.items():
        for feature in TOOL_FEATURES.get(tool, ()):
            reached.setdefault(feature, []).append(f"{tool} x{count}")
    if graph is not None and delivery.get("treatment_valid"):
        for feature in ("F1", "F21"):
            reached.setdefault(feature, []).append("substrate")
    triggers = {
        "searches": _num(delivery.get("gt_search_commands")),
        "search_hits": _num(delivery.get("augment_hits")),
        "search_silent_stale": augment.get("silent_stale", 0),
        "search_errors": augment.get("error", 0),
        "edits": len({r.get("sequence") for r in edit_rows}),
        "edit_hits": _num(delivery.get("edit_augment_hits")),
        "taint_over_budget": sum(1 for r in edit_rows if r.get("skipped") == "taint_over_budget"),
        "test_runs": len(tests),
        "failing_test_runs": len(failing_tests),
        "failure_blocks": _num(delivery.get("failure_augment_calls")),
        "failure_hits": _num(delivery.get("failure_augment_hits")),
        "tool_calls": dict(tool_calls),
    }
    categories: dict[str, dict[str, Any]] = {}
    for name in FEATURES:
        feature = name.split()[0]
        if feature in reached:
            categories[name] = {"category": "REACHED", "why": ", ".join(reached[feature])}
            continue
        if graph is None:
            categories[name] = {"category": "NO_GRAPH", "why": "no published graph"}
            continue
        have = graph.get(feature, 0)
        if feature == "F13":
            have = graph.get("F13", 0) + graph.get("cochange_rows", 0)
        if have == 0:
            categories[name] = {"category": "NOT_IN_REPO",
                                "why": f"graph has 0 rows for it ({APPLICABILITY[feature][21:70]}...)"}
            continue
        surfaces = FEATURE_SURFACES[name]
        passive = [s for s in surfaces if not s.startswith("gt-") and s != "substrate"]
        if not passive:
            categories[name] = {"category": "TOOL_ONLY_UNCALLED",
                                "why": f"only {', '.join(surfaces)}; agent called none"}
            continue
        why: list[str] = []
        triggered = False
        if "failure-augment" in passive:
            if triggers["failing_test_runs"] == 0 and triggers["failure_blocks"] == 0:
                why.append("no failing test run")
            else:
                triggered = True
                why.append(f"{triggers['failure_blocks']} failure block(s), {triggers['failure_hits']} hit")
        if "edit-augment" in passive:
            if triggers["edits"] == 0:
                why.append("no edit")
            else:
                triggered = True
                if feature == "F19" and triggers["taint_over_budget"]:
                    categories[name] = {"category": "DEGRADED",
                                        "why": f"taint skipped over budget on {triggers['taint_over_budget']}/"
                                               f"{triggers['edits']} edits"}
                why.append(f"{triggers['edits']} edit(s) did not carry it")
        if "augment" in passive:
            if triggers["searches"] == 0:
                why.append("no search")
            else:
                triggered = True
                why.append(f"{triggers['search_hits']}/{triggers['searches']} searches hit; "
                           f"none on a symbol with it (repo has {have})")
        if name in categories:
            continue
        if triggers["search_errors"] or (triggers["search_silent_stale"] and "augment" in passive):
            categories[name] = {"category": "DEGRADED", "why": f"augment errors={triggers['search_errors']}"
                                f" stale-silent={triggers['search_silent_stale']}; " + "; ".join(why)}
        elif triggered:
            categories[name] = {"category": "DARK", "why": "; ".join(why)}
        else:
            categories[name] = {"category": "NO_TRIGGER", "why": "; ".join(why)}
    reward = None
    for candidate in (agent_dir.parent / "verifier" / "reward.txt", agent_dir.parent / "reward.txt"):
        if candidate.is_file():
            reward = candidate.read_text(encoding="utf-8").strip()
            break
    return {"task": agent_dir.parent.name.split("__")[0], "reward": reward,
            "valid": delivery.get("treatment_valid"), "graph": graph, "triggers": triggers,
            "plan_delivered": delivery.get("gt_plan_delivered"), "features": categories}


def render(tasks: list[dict[str, Any]]) -> str:
    order = ["REACHED", "DARK", "NO_TRIGGER", "TOOL_ONLY_UNCALLED", "NOT_IN_REPO", "DEGRADED", "NO_GRAPH"]
    short = {"REACHED": "OK", "DARK": "DARK", "NO_TRIGGER": "notrig", "TOOL_ONLY_UNCALLED": "tool",
             "NOT_IN_REPO": "n/a", "DEGRADED": "DEGR", "NO_GRAPH": "nograph"}
    lines = ["| feature | " + " | ".join(t["task"][:18] for t in tasks) + " | reached |",
             "|---|" + "---|" * len(tasks) + "---|"]
    for name in FEATURES:
        cells = [short[t["features"][name]["category"]] for t in tasks]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {cells.count('OK')}/{len(tasks)} |")
    lines += ["", "Totals: " + ", ".join(
        f"{cat}={sum(1 for t in tasks for f in t['features'].values() if f['category'] == cat)}"
        for cat in order)]
    lines += ["", "Triggers per task:"]
    for t in tasks:
        tr = t["triggers"]
        lines.append(f"- {t['task']}: reward={t['reward']} valid={t['valid']} plan={t['plan_delivered']}"
                     f" searches={tr['search_hits']}/{tr['searches']} edits={tr['edit_hits']}/{tr['edits']}"
                     f" tests={tr['test_runs']} failing={tr['failing_test_runs']}"
                     f" failure_blocks={tr['failure_hits']}/{tr['failure_blocks']}"
                     f" taint_over_budget={tr['taint_over_budget']} tools={tr['tool_calls']}"
                     f" langs={(t['graph'] or {}).get('languages')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, action="append")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--why", action="store_true", help="print the reason for every non-REACHED cell")
    args = parser.parse_args(argv)
    tasks = []
    for root in args.root:
        for report in sorted(root.rglob("agent/miniswe_report.json")):
            if "gt-state" in report.parts:
                continue
            tasks.append(classify_task(report.parent))
    print(render(tasks))
    if args.why:
        for t in tasks:
            print(f"\n## {t['task']}")
            for name, row in t["features"].items():
                if row["category"] != "REACHED":
                    print(f"- {name}: {row['category']} - {row['why']}")
    if args.json:
        args.json.write_text(json.dumps(tasks, indent=2, default=str), encoding="utf-8")
    return 0 if tasks else 1


if __name__ == "__main__":
    raise SystemExit(main())
