"""What GT actually put in front of the agent, and which features built it.

Reads each task's ``agent/miniswe_trajectory.json`` (the messages the model
saw), extracts every ``[GT]`` block, classifies it (task plan, search block,
edit block, failure block, gt-* tool answer) and every fact line in it. Each
caller/callee row a block showed is then matched to the exact CALLS edge in
the task's published graphs, and the edge's provenance columns are tallied:
those columns are how features that never print their own line (call
resolution, callable-value flow, receiver dispatch, framework semantics) are
proven to have shaped what the agent read.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SITE = re.compile(r"([A-Za-z_$][\w.$<>]*) \(([^():]+):(\d+)\)")
EDGE_COLUMNS = ("resolution_method", "derivation_kind", "pass_kind", "evidence_type",
                "trust_tier", "receiver_origin", "verification_status")


def _messages(agent_dir: Path) -> list[dict[str, Any]]:
    path = agent_dir / "miniswe_trajectory.json"
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("messages") or [])


def _text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") if isinstance(part, dict) else str(part)
                     for part in content or [])


def gt_blocks(agent_dir: Path) -> list[tuple[str, str]]:
    """(kind, text) of every [GT] block in a tool/user observation."""
    blocks = []
    for message in _messages(agent_dir):
        if message.get("role") == "system":
            continue
        text = _text(message)
        for chunk in text.split("[GT]")[1:]:
            body = "[GT]" + chunk.split("\n\n[GT]")[0]
            head = body.splitlines()[0]
            if head.startswith("[GT] task plan"):
                kind = "plan"
            elif head.startswith("[GT] graph context for your search"):
                kind = "grep"
            elif head.startswith("[GT] after your edit"):
                kind = "edit"
            elif head.startswith("[GT] about this failure"):
                kind = "failure"
            else:
                kind = "tool:" + head[5:40].split(" ")[0]
            blocks.append((kind, body))
    return blocks


def _line_features(kind: str, line: str) -> set[str]:
    s = line.strip()
    out: set[str] = set()
    if kind == "grep":
        if re.match(r"^\S.* \((Function|Method|Class|Interface|\w+)\) \S+:\d+", s):
            out |= {"F2", "F12"}
        if s.startswith(("called by:", "calls:")):
            out.add("F4")
        if s.startswith("in flow:"):
            out.add("F9")
        if s.startswith("referenced from"):
            out.add("F3")
        if s.startswith("call sites:"):
            out.add("F5")
            if "function value" in s:
                out.add("F6")
        if s.startswith(("overridden by", "overrides", "extended/implemented")):
            out.add("F7")
        if s.startswith(("handles route",)):
            out |= {"F8", "F18"}
        if s.startswith(("middleware on", "injected into")):
            out.add("F8")
        if s.startswith("module "):
            out.add("F10")
        if s.startswith("usually changes with"):
            out.add("F13")
    elif kind == "edit":
        if s.startswith("PARSE ERROR"):
            out.add("F1")
        if s.startswith("changed:"):
            out.add("F13")
        if "is called by" in s:
            out |= {"F4", "F13"}
        if "sink" in s:
            out.add("F19")
        if "handles route" in s:
            out |= {"F8", "F18"}
        if s.startswith("tests reaching"):
            out.add("F20")
    elif kind == "failure":
        if s.startswith("failing test"):
            out.add("F20")
        if s.startswith("failure surfaced"):
            out.add("F20")
        if "backward slice" in s:
            out |= {"F14", "F15", "F16", "F17"}
        if s.startswith("same failure"):
            out.add("F20")
    elif kind == "plan":
        if "->" in s and "no code anchor" not in s:
            out |= {"F2", "F4"}
        if "hop(s) away" in s:
            out.add("F20")
    return out


def _graphs(agent_dir: Path) -> list[Path]:
    return sorted((p for p in agent_dir.rglob("graph.db") if "revisions" in p.parts),
                  key=lambda p: p.stat().st_size, reverse=True)


def edge_provenance(agent_dir: Path, blocks: list[tuple[str, str]]) -> dict[str, Counter]:
    """Provenance of the CALLS edges behind every caller/callee row shown."""
    rows: list[tuple[str, str, str, int]] = []   # (direction, name, path, line)
    for kind, body in blocks:
        if kind not in ("grep", "edit"):
            continue
        for line in body.splitlines():
            s = line.strip()
            direction = "caller" if ("called by" in s) else "callee" if s.startswith("calls:") else ""
            if not direction:
                continue
            for name, path, number in SITE.findall(s.split(":", 1)[1]):
                rows.append((direction, name, path, int(number)))
    tallies: dict[str, Counter] = defaultdict(Counter)
    graphs = _graphs(agent_dir)
    if not graphs or not rows:
        return tallies
    conns = [sqlite3.connect(g.resolve().as_uri() + "?mode=ro", uri=True) for g in graphs[:3]]
    cols = ", ".join(f"e.{c}" for c in EDGE_COLUMNS)
    try:
        for direction, name, path, number in rows:
            short = name.rsplit(".", 1)[-1]
            found = None
            for conn in conns:
                if direction == "caller":
                    sql = (f"SELECT {cols}, e.metadata FROM edges e JOIN nodes s ON s.id = e.source_id"
                           " WHERE e.type = 'CALLS' AND s.name = ? AND s.file_path = ? AND e.source_line = ? LIMIT 1")
                else:
                    sql = (f"SELECT {cols}, e.metadata FROM edges e JOIN nodes t ON t.id = e.target_id"
                           " WHERE e.type = 'CALLS' AND t.name = ? AND t.file_path = ? AND t.start_line = ? LIMIT 1")
                try:
                    found = conn.execute(sql, (short, path, number)).fetchone()
                except sqlite3.Error:
                    found = None
                if found:
                    break
            if not found:
                tallies["_matched"]["unmatched"] += 1
                continue
            tallies["_matched"]["matched"] += 1
            for column, value in zip(EDGE_COLUMNS, found[:-1]):
                tallies[column][str(value)] += 1
            try:
                mechanism = json.loads(found[-1] or "{}").get("mechanism")
            except (TypeError, ValueError):
                mechanism = None
            tallies["metadata.mechanism"][str(mechanism)] += 1
    finally:
        for conn in conns:
            conn.close()
    return tallies


def analyse(agent_dir: Path) -> dict[str, Any]:
    blocks = gt_blocks(agent_dir)
    kinds = Counter(kind for kind, _ in blocks)
    features: Counter = Counter()
    for kind, body in blocks:
        seen: set[str] = set()
        for line in body.splitlines()[1:]:
            seen |= _line_features(kind, line)
        if kind.startswith("tool:"):
            seen.add("tool:" + kind[5:])
        features.update(seen)
    return {"task": agent_dir.parent.name.split("__")[0], "blocks": dict(kinds),
            "features_seen": dict(sorted(features.items())),
            "edge_provenance": {k: dict(v) for k, v in edge_provenance(agent_dir, blocks).items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    results = []
    for root in args.root:
        for traj in sorted(root.rglob("agent/miniswe_trajectory.json")):
            if "gt-state" in traj.parts:
                continue
            results.append(analyse(traj.parent))
    for row in results:
        print(json.dumps(row, default=str))
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
