"""Paired, outcome-aware efficiency: GT-on (one run) vs the same tasks' GT-off runs.

Totals are dominated by a few long tasks and confounded by outcome (a failing
run burns tokens to its limit). This report instead:

* pairs every task with ITS OWN baseline runs and averages per-task ratios
  (geometric mean, bootstrap 95% CI over tasks, Wilcoxon signed-rank p);
* compares like for like - tasks GT solved against the baseline runs that
  also solved them (the cost of reaching the same solution);
* reports cost per solved task with a bootstrap CI;
* splits input into uncached and cached (provider-reported cache hits),
  and adds output tokens, steps and wall-clock seconds;
* measures GT's own footprint: the share of observation bytes that were
  GT blocks.

Trajectory layout is mini-swe-agent's: info + messages; assistant messages
carry extra.response.usage and extra.timestamp.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

METRICS = ("total", "input", "output", "cached_in", "uncached_in", "steps", "wall_s")
RNG_SEED = 20260929
BOOTSTRAP = 4000


@dataclass
class Attempt:
    task: str
    solved: bool
    total: float
    input: float
    uncached_in: float
    cached_in: float
    output: float
    steps: float
    wall_s: float
    gt_bytes: float = 0.0
    obs_bytes: float = 0.0


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def attempt_from_trajectory(path: Path, task: str, solved: bool) -> Attempt | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    uncached = cached = output = 0.0
    stamps: list[float] = []
    steps = 0
    gt_bytes = obs_bytes = 0.0
    for message in data.get("messages") or ():
        extra = message.get("extra") or {}
        if message.get("role") == "assistant":
            steps += 1
            usage = (extra.get("response") or {}).get("usage") or {}
            prompt = float(usage.get("prompt_tokens") or 0)
            hit = float(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
            cached += hit
            uncached += max(0.0, prompt - hit)
            output += float(usage.get("completion_tokens") or 0)
            if extra.get("timestamp"):
                stamps.append(float(extra["timestamp"]))
        elif message.get("role") in ("tool", "user"):
            text = _text(message.get("content"))
            obs_bytes += len(text.encode("utf-8"))
            index = text.find("[GT]")
            if index >= 0:
                gt_bytes += len(text[index:].encode("utf-8"))
    if steps == 0:
        return None
    wall = (max(stamps) - min(stamps)) if len(stamps) > 1 else 0.0
    return Attempt(task, solved, uncached + cached + output, uncached + cached, uncached, cached, output,
                   float(steps), wall, gt_bytes, obs_bytes)


def _geo_mean(values: list[float]) -> float:
    values = [v for v in values if v > 0]
    return math.exp(statistics.fmean(math.log(v) for v in values)) if values else float("nan")


def _bootstrap(values: list[float], stat, rng: random.Random) -> tuple[float, float]:
    if len(values) < 3:
        return (float("nan"), float("nan"))
    draws = sorted(stat([rng.choice(values) for _ in values]) for _ in range(BOOTSTRAP))
    return draws[int(0.025 * BOOTSTRAP)], draws[int(0.975 * BOOTSTRAP) - 1]


def _wilcoxon_p(diffs: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank p (normal approximation, ties averaged)."""
    diffs = [d for d in diffs if d != 0]
    n = len(diffs)
    if n < 6:
        return float("nan")
    ordered = sorted(range(n), key=lambda i: abs(diffs[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(diffs[ordered[j + 1]]) == abs(diffs[ordered[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[ordered[k]] = (i + j) / 2 + 1
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, diffs) if d > 0)
    mean = n * (n + 1) / 4
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w_plus - mean) / sd
    return math.erfc(abs(z) / math.sqrt(2))


def paired(gt: dict[str, Attempt], base: dict[str, list[Attempt]], tasks: list[str], metric: str,
           rng: random.Random) -> dict:
    ratios, diffs = [], []
    for task in tasks:
        b = statistics.fmean(getattr(a, metric) for a in base[task])
        g = getattr(gt[task], metric)
        if b > 0 and g > 0:
            ratios.append(g / b)
            diffs.append(g - b)
    low, high = _bootstrap(ratios, _geo_mean, rng)
    return {"tasks": len(ratios), "geo_mean_ratio": _geo_mean(ratios), "ci95": [low, high],
            "wilcoxon_p": _wilcoxon_p(diffs)}


def report(gt: dict[str, Attempt], base: dict[str, list[Attempt]]) -> dict:
    rng = random.Random(RNG_SEED)
    common = sorted(t for t in gt if base.get(t))
    solved_both = [t for t in common if gt[t].solved and any(a.solved for a in base[t])]
    base_solved = {t: [a for a in base[t] if a.solved] for t in solved_both}
    out: dict = {"tasks_paired": len(common), "tasks_like_for_like": len(solved_both)}
    out["all_tasks"] = {m: paired(gt, base, common, m, rng) for m in METRICS}
    out["like_for_like"] = {m: paired(gt, base_solved, solved_both, m, rng) for m in METRICS}

    def totals(tasks: list[str], pool: dict[str, list[Attempt]]) -> dict:
        rows = {}
        for m in METRICS:
            g = sum(getattr(gt[t], m) for t in tasks)
            b = sum(statistics.fmean(getattr(a, m) for a in pool[t]) for t in tasks)
            rows[m] = {"gt": g, "baseline": b, "ratio": g / b if b else float("nan")}
        return rows

    out["totals_all"] = totals(common, base)
    out["totals_like_for_like"] = totals(solved_both, base_solved)

    def per_solve(attempts_by_task: dict[str, list[Attempt]], metric: str) -> float:
        total = sum(statistics.fmean(getattr(a, metric) for a in atts) for atts in attempts_by_task.values())
        solves = sum(statistics.fmean(1.0 if a.solved else 0.0 for a in atts) for atts in attempts_by_task.values())
        return total / solves if solves else float("nan")

    gt_lists = {t: [gt[t]] for t in common}
    base_lists = {t: base[t] for t in common}
    cps = {}
    for metric in ("total", "input", "output"):
        g, b = per_solve(gt_lists, metric), per_solve(base_lists, metric)

        def boot_ratio(sample: list[str], metric=metric) -> float:
            gs = per_solve({t: gt_lists[t] for t in sample}, metric)
            bs = per_solve({t: base_lists[t] for t in sample}, metric)
            return gs / bs if bs and not math.isnan(bs) and not math.isnan(gs) else float("nan")

        draws = sorted(x for x in (boot_ratio([rng.choice(common) for _ in common]) for _ in range(1000))
                       if not math.isnan(x))
        cps[metric] = {"gt": g, "baseline": b, "ratio": g / b if b else float("nan"),
                       "ci95": [draws[25], draws[974]] if len(draws) >= 1000 else [float("nan")] * 2}
    out["cost_per_solved_task"] = cps
    gt_bytes = sum(gt[t].gt_bytes for t in common)
    obs = sum(gt[t].obs_bytes for t in common)
    out["gt_share_of_observation_bytes"] = gt_bytes / obs if obs else 0.0
    return out


def render(title: str, r: dict) -> str:
    names = {"total": "TOTAL tokens (input+output)", "input": "input tokens (all)",
             "uncached_in": "  of which uncached", "cached_in": "  of which cached (provider cache hits)",
             "output": "output tokens", "steps": "steps", "wall_s": "wall-clock seconds"}
    fmt = lambda x: f"{x:.3f}" if isinstance(x, float) and not math.isnan(x) else "n/a"

    def amount(x: float, metric: str) -> str:
        if metric == "steps":
            return f"{x:,.0f}"
        if metric == "wall_s":
            return f"{x / 3600:.1f} h"
        return f"{x / 1e6:.2f}M"

    lines = [f"## {title}", "",
             f"All paired tasks: {r['tasks_paired']}. Solved-only (apples to apples): {r['tasks_like_for_like']} tasks "
             "GT solved, each against only the baseline runs that also solved it.", "",
             "### 1. Totals (GT vs the baseline's per-task mean, summed)", "",
             "| metric | all tasks: GT | baseline | GT/baseline | solved-only: GT | baseline | GT/baseline |",
             "|---|---|---|---|---|---|---|"]
    for metric in METRICS:
        a, s = r["totals_all"][metric], r["totals_like_for_like"][metric]
        lines.append(f"| {names[metric]} | {amount(a['gt'], metric)} | {amount(a['baseline'], metric)} | {fmt(a['ratio'])} | "
                     f"{amount(s['gt'], metric)} | {amount(s['baseline'], metric)} | {fmt(s['ratio'])} |")
    lines += ["", "### 2. Per task (paired; geometric mean of GT/baseline ratios, every task counts equally)", "",
              "| metric | all tasks: ratio | 95% CI | Wilcoxon p | solved-only: ratio | 95% CI | Wilcoxon p |",
              "|---|---|---|---|---|---|---|"]
    for metric in METRICS:
        a, s = r["all_tasks"][metric], r["like_for_like"][metric]
        lines.append(f"| {names[metric]} | {fmt(a['geo_mean_ratio'])} | {fmt(a['ci95'][0])}-{fmt(a['ci95'][1])} | "
                     f"{fmt(a['wilcoxon_p'])} | {fmt(s['geo_mean_ratio'])} | {fmt(s['ci95'][0])}-{fmt(s['ci95'][1])} | "
                     f"{fmt(s['wilcoxon_p'])} |")
    lines += ["", "### 3. Per solved task (all tokens spent / tasks solved)"]
    lines += ["", "| per solved task | GT | baseline | ratio | 95% CI |", "|---|---|---|---|---|"]
    for metric, row in r["cost_per_solved_task"].items():
        lines.append(f"| {names[metric]} | {row['gt']/1e3:.1f}k | {row['baseline']/1e3:.1f}k | {row['ratio']:.3f} | "
                     f"{row['ci95'][0]:.3f}-{row['ci95'][1]:.3f} |")
    lines += ["", f"GT blocks were {100 * r['gt_share_of_observation_bytes']:.1f}% of observation bytes."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt", required=True, help="JSON: {task: [trajectory_path, solved]}")
    parser.add_argument("--baseline", required=True, help="JSON: {task: [[trajectory_path, solved], ...]}")
    parser.add_argument("--title", default="Efficiency")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    gt_map = json.loads(Path(args.gt).read_text(encoding="utf-8"))
    base_map = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    gt = {t: a for t, (p, s) in gt_map.items() if (a := attempt_from_trajectory(Path(p), t, bool(s)))}
    base: dict[str, list[Attempt]] = {}
    for t, rows in base_map.items():
        for p, s in rows:
            a = attempt_from_trajectory(Path(p), t, bool(s))
            if a:
                base.setdefault(t, []).append(a)
    result = report(gt, base)
    Path(args.out).write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    text = render(args.title, result)
    Path(args.out).with_suffix(".md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
