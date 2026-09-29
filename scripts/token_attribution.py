"""Where do GT's extra tokens come from? Per task, GT trajectory vs the same task's baseline runs.

Input tokens are the context re-sent every step, so a byte GT adds at step k is
paid again at every later step. The excess of GT total tokens over the
baseline mean is split into:

  template   the GT prompt sections (system + task message) x GT steps
  carry      GT blocks and gt-* tool outputs, each counted once per later step
  steps      everything else: extra steps and the agent's own larger outputs

Bytes are converted to tokens with the task's own ratio (prompt tokens / prompt
chars at the first step), so the split adds up per model and tokenizer.
Also reports GT bytes by feature and how often the agent reused a block's
names in its next 3 actions (uptake), to separate costly-and-used from
costly-and-ignored.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

KINDS = [
    ("grep", re.compile(r"^\[GT\] graph context for your search")),
    ("read", re.compile(r"^\[GT\] about ")),
    ("edit", re.compile(r"^\[GT\] after your edit")),
    ("failure", re.compile(r"^\[GT\] (where|the failing|failure|your test run failed)", re.I)),
    ("review", re.compile(r"^\[GT\] before you submit")),
]
NAME = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{3,})\b")


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _kind(block: str) -> str:
    for name, pattern in KINDS:
        if pattern.search(block):
            return name
    return "other_gt"


def analyse(path: str) -> dict | None:
    try:
        messages = json.loads(Path(path).read_text(encoding="utf-8"))["messages"]
    except (OSError, ValueError, KeyError):
        return None
    system, instance = _text(messages[0].get("content")), _text(messages[1].get("content"))
    template_chars = len(system) + len(instance)
    steps, total, first_prompt = 0, 0, None
    commands: list[str] = []
    obs_gt: list[tuple[int, str, int, str]] = []  # (step, kind, chars, text)
    tool_steps = 0
    tool_chars_by_step: list[tuple[int, int]] = []
    for message in messages[2:]:
        role = message.get("role")
        if role == "assistant":
            steps += 1
            usage = ((message.get("extra") or {}).get("response") or {}).get("usage") or {}
            prompt = int(usage.get("prompt_tokens") or 0)
            total += prompt + int(usage.get("completion_tokens") or 0)
            if first_prompt is None and prompt:
                first_prompt = prompt
            cmds = [a.get("command", "") for a in (message.get("extra") or {}).get("actions", [])]
            commands.append(" ".join(cmds))
            if any(re.match(r"\s*(cd [^&]+&&\s*)?gt-[a-z]", c) for c in cmds):
                tool_steps += 1
        elif role in ("tool", "user") and steps:
            text = _text(message.get("content"))
            idx = text.find("[GT]")
            if idx >= 0:
                for block in re.split(r"\n(?=\[GT\])", text[idx:]):
                    obs_gt.append((steps, _kind(block), len(block), block))
            if commands and re.match(r"\s*(cd [^&]+&&\s*)?gt-[a-z]", commands[-1]):
                tool_chars_by_step.append((steps, len(text)))
    if not steps or not first_prompt:
        return None
    tok_per_char = first_prompt / max(1, template_chars + 1)
    carry_by_kind: dict[str, float] = defaultdict(float)
    bytes_by_kind: dict[str, int] = defaultdict(int)
    uptake_by_kind: dict[str, list[int]] = defaultdict(list)
    for step, kind, chars, block in obs_gt:
        later = steps - step
        carry_by_kind[kind] += chars * later * tok_per_char
        bytes_by_kind[kind] += chars
        names = {n for n in NAME.findall(block) if not n.startswith("GT")} - set(NAME.findall(commands[step - 1]))
        window = " ".join(commands[step:step + 3])
        uptake_by_kind[kind].append(1 if any(n in window for n in names) else 0)
    tool_carry = sum(chars * (steps - step) * tok_per_char for step, chars in tool_chars_by_step)
    return {"steps": steps, "total": total, "template_chars": template_chars, "tok_per_char": tok_per_char,
            "carry_by_kind": dict(carry_by_kind), "bytes_by_kind": dict(bytes_by_kind),
            "uptake_by_kind": {k: v for k, v in uptake_by_kind.items()}, "tool_carry": tool_carry,
            "tool_steps": tool_steps}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args(argv)
    gt_map = json.loads(Path(args.gt).read_text(encoding="utf-8"))
    base_map = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    rows = []
    for task, (path, solved) in gt_map.items():
        g = analyse(path)
        bs = [b for b in (analyse(p) for p, _ in base_map.get(task, [])) if b]
        if not g or not bs:
            continue
        b_total = statistics.fmean(b["total"] for b in bs)
        b_steps = statistics.fmean(b["steps"] for b in bs)
        b_template = statistics.fmean(b["template_chars"] for b in bs)
        template = max(0.0, (g["template_chars"] - b_template) * g["tok_per_char"] * g["steps"])
        carry = sum(g["carry_by_kind"].values()) + g["tool_carry"]
        excess = g["total"] - b_total
        rows.append({"task": task, "solved": solved, "excess": excess, "template": template, "carry": carry,
                     "rest": excess - template - carry, "g": g, "b_total": b_total,
                     "steps_ratio": g["steps"] / b_steps if b_steps else float("nan")})
    n = len(rows)
    tot = lambda key: sum(r[key] for r in rows)
    base_total = sum(r["b_total"] for r in rows)
    print(f"## {args.title} - {n} paired tasks")
    print(f"GT excess over baseline: {tot('excess')/1e6:+.1f}M tokens ({100*tot('excess')/base_total:+.1f}% of baseline)")
    for key, label in (("template", "GT prompt sections x steps"), ("carry", "GT blocks + gt-* tool output carried"),
                       ("rest", "extra steps / agent's own context")):
        print(f"  {label:40s} {tot(key)/1e6:+8.1f}M  ({100*tot(key)/base_total:+5.1f}% of baseline)")
    print(f"  median steps ratio GT/baseline {statistics.median(r['steps_ratio'] for r in rows):.3f}; "
          f"GT steps that ran a gt-* tool: {sum(r['g']['tool_steps'] for r in rows)} of {sum(r['g']['steps'] for r in rows)}")
    print("\nGT blocks by feature: carried tokens (share of baseline), bytes delivered, uptake in next 3 actions")
    kinds = sorted({k for r in rows for k in r["g"]["carry_by_kind"]})
    for kind in kinds:
        carry = sum(r["g"]["carry_by_kind"].get(kind, 0) for r in rows)
        byts = sum(r["g"]["bytes_by_kind"].get(kind, 0) for r in rows)
        up = [u for r in rows for u in r["g"]["uptake_by_kind"].get(kind, [])]
        print(f"  {kind:10s} carry {carry/1e6:7.1f}M ({100*carry/base_total:4.1f}%)  bytes {byts/1e3:8.0f}k  "
              f"blocks {len(up):5d}  uptake {100*statistics.fmean(up) if up else 0:5.1f}%")
    tool = sum(r["g"]["tool_carry"] for r in rows)
    print(f"  {'gt-tools':10s} carry {tool/1e6:7.1f}M ({100*tool/base_total:4.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
