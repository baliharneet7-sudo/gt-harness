"""Per-task TB2 report: official reward, run metrics and a token-derived cost.

Joins two receipts on ``task_id``: the ``gt.benchmark_progress.v1`` progress
receipt (the only official statement of reward and grading) and the per-task
``gt-run.json`` product receipt (turns, calls, tokens). A task that appears in
progress with no ``gt-run.json`` still gets a row - it is exactly the shape a
trial that died before writing its receipt leaves behind, and dropping it
would hide the loss.

Cost is derived from recorded tokens and a rate the caller declares, never
from the harness ``total_cost`` field, which is 0.0 by design
(``MSWEA_COST_TRACKING=ignore_errors``; litellm carries no price entry for
these models). A printed ``$0.00`` has repeatedly been read as "this run was
free", so this refuses to print a cost it cannot derive:

  * ``--rates config/provider_route_<model>.v1.json`` reads that manifest's
    ``pricing`` block (``prompt_usd_per_token`` / ``completion_usd_per_token``).
  * ``--prompt-price`` / ``--completion-price`` supply the rate directly, for
    a manifest that does not carry the block yet.
  * Neither available is a hard error, not a zero.

There is deliberately no built-in price table here. A table drifts silently
against the route the run actually used; the manifest is the route.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROGRESS_SCHEMA = "gt.benchmark_progress.v1"
_GT_RUN_NAME = "gt-run.json"

_COST_CAVEAT = "cost is token-derived; the harness total_cost is 0.0 by design"


class RateUnavailable(RuntimeError):
    """No token price could be established, so no cost may be printed."""


class BaselineUnreadable(RuntimeError):
    """The baseline SUMMARY's own header row does not describe its columns."""


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _num(value: Any) -> int | float | None:
    """Numeric passthrough; bools, non-finite values and the rest become None.

    ``json.dumps`` writes bare ``NaN``, ``Infinity`` and ``-Infinity`` - it is
    Python's own default - and ``json.loads`` reads them back as floats, so a
    receipt can carry one. Passing it through printed a number-shaped ``nan``
    in the row AND poisoned every cohort total that summed the column
    (``sum(row["input_tokens"] or 0 ...)`` propagates it: NaN is truthy), so a
    single unmeasured task turned the whole report's tokens, cache-hit rate
    and cost into ``nan``. A value that is not a finite number measured
    nothing, and unmeasured is None here - which every caller already renders
    as ``-`` and leaves out of the sums.

    This is the module's only numeric conversion; every row field that a
    receipt supplies goes through it, which is why one guard covers the token
    counts, the call counters and the reward alike.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return value


# --- rates -----------------------------------------------------------------


def read_pricing(path: Path | str) -> tuple[float, float] | None:
    """Read a route manifest's ``pricing`` block, or None if it has none.

    The block is being added to ``config/provider_route_*.json`` separately,
    so its absence is an ordinary outcome, not a fault. A block that is
    present but unusable is a fault, and says so.
    """
    body = _read_json(Path(path))
    if body is None:
        raise RateUnavailable(f"rates manifest is missing or is not JSON: {path}")
    pricing = body.get("pricing")
    if pricing is None:
        return None
    if not isinstance(pricing, dict):
        raise RateUnavailable(f"pricing block in {path} is not an object")
    prompt = _num(pricing.get("prompt_usd_per_token"))
    completion = _num(pricing.get("completion_usd_per_token"))
    if prompt is None or completion is None:
        raise RateUnavailable(
            f"pricing block in {path} needs both prompt_usd_per_token and "
            "completion_usd_per_token"
        )
    return float(prompt), float(completion)


def resolve_rates(
    rates_path: Path | str | None = None,
    prompt_price: float | None = None,
    completion_price: float | None = None,
) -> tuple[float, float, str]:
    """Return (prompt rate, completion rate, where it came from), or refuse.

    Explicit flags win over the manifest: they are the operator's override for
    a route whose manifest does not carry a price yet. ``0.0`` is a legitimate
    recorded price (the retired stealth preview model was genuinely free), so
    every test here is against None, never against falsiness.
    """
    if prompt_price is not None and completion_price is not None:
        return float(prompt_price), float(completion_price), "--prompt-price/--completion-price flags"
    if prompt_price is not None or completion_price is not None:
        raise RateUnavailable(
            "--prompt-price and --completion-price must be given together; "
            "half a rate is not a rate"
        )
    pricing = read_pricing(rates_path) if rates_path else None
    if pricing is not None:
        return pricing[0], pricing[1], f"pricing block of {rates_path}"
    where = f"{rates_path} has no pricing block" if rates_path else "no --rates manifest given"
    raise RateUnavailable(
        f"no token rate available: {where}. Pass --rates pointing at a route "
        "manifest that carries a pricing block, or pass --prompt-price and "
        "--completion-price. Refusing to print a cost rather than print $0.00, "
        "which is what the harness total_cost field already reports by design."
    )


# --- inputs ----------------------------------------------------------------


# The harness owns exactly these subtrees of a trial directory, and Pier names
# one directory per trial ``<task>__<hash>`` that sits at the artifact root,
# one level down (``<task>/``) or two (``<job-name>/<task>__<hash>/``).
# Everything below a trial is the task's own repository checkout: unbounded in
# size and full of JSON that looks like ours. An unbounded ``rglob`` parsed
# ~850 files per task and, because the join is first-in-sorted-order-wins,
# a vendored ``.venv/lib/site-packages/harness/gt-run.json`` sorted ahead of
# ``agent/`` and was reported as that task's turns. The relationship to the
# sibling walkers is not one of equality and never claims to be:
#   * _HARNESS_GLOBS below is verify_run_receipts._HARNESS_GLOBS spelling for
#     spelling, and covers gt_audit._MINISWE_REPORT_GLOBS. A location added
#     there and not here is a location this report cannot see, which is what
#     test_the_harness_owned_locations_match_the_sibling_walkers asserts (as a
#     subset check, so the sibling can never be silently ahead).
#   * _TRIAL_GLOBS is a strict SUPERSET of verify_run_receipts._TRIAL_GLOBS:
#     three depths against its two - see its own comment for why. The trial
#     test itself (a ``__`` in the name AND an owned ``agent/``, and nothing
#     below a trial) is the same in both.
# A new artifact location is added here deliberately, never discovered by
# walking.
_HARNESS_GLOBS = (
    "*.json",  # the trial dir's own top level
    "agent/*.json",
    # Only the state dir's top level: one level deeper are the per-request
    # provider blobs, thousands of files, and no receipt lives among them.
    "agent/gt-state/*/*.json",
    "artifacts/*.json",
    "official-evaluator/*.json",
    "progress/*.json",
)
# A Pier trial is named ``<task>__<hash>`` and OWNS an ``agent/`` directory.
# verify_run_receipts.find_trials looks one and two levels down; a downloaded
# attestation bundle nests one level deeper still
# (``<job>/<artifact>/<task>__<hash>/agent/``), and a trial this report cannot
# see is a row that prints "-" for every metric it has on disk. Depth is the
# only thing widened here: the ``__`` in the name and the owned ``agent/`` are
# both still required, and the depths are tried in ORDER - see _find_trials.
# This module and verify_run_receipts.find_trials must agree about what a trial
# is; they are kept independent deliberately (this is a reporting tool and that
# is a gate) so neither can drag the other's walk with it.
_TRIAL_GLOBS = ("*__*", "*/*__*", "*/*/*__*")

# Which harness-owned location speaks for a task when two of them carry a
# ``gt-run.json``, best first. The agent writes the receipt; every other
# location holds a copy, and the trial's top level is globbed first, so glob
# order alone would elect the copy. An unlisted location ranks last.
_GT_RUN_AUTHORITY = ("agent", "", "artifacts", "official-evaluator", "progress")


def _is_trial(path: Path) -> bool:
    """A Pier trial directory: ``<task>__<hash>/`` owning an ``agent/``."""
    return "__" in path.name and path.is_dir() and path.joinpath("agent").is_dir()


def _inside_a_trial(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` sits below a trial, i.e. inside its checkout.

    The rule, and it is the SAME rule in verify_run_receipts and in
    diagnose_benchmark_run (each keeps its own copy - two are gates, this is a
    reporting tool - and tests/test_tb2_report.py asserts the three agree):
    ``candidate`` is inside a trial when some ancestor between it and the
    resolved ``root``, ``root`` INCLUDED, owns an ``agent/``.

    M-3: searching every depth at once reaches one level INSIDE a resolved
    trial, where a vendored package or fixture tree owning an ``agent/``
    (``<trial>/sub__x/agent/``) counts as a second trial - and then its JSON is
    read as this task's receipts. Nothing below a trial is ever a trial, so
    every ancestor up to ``root`` is tested rather than only the parent's name.
    The directory NAME is no part of the test: ``root`` itself may legitimately
    be named with a ``__`` (a download directory named after a SWE-bench
    instance) and a flat ``<root>/<task>/agent/`` task directory carries none,
    so only an owned ``agent/`` says anything.

    M-1 (round 6): both paths are resolved first. ``Path(".").parent`` IS
    ``Path(".")``, so an ancestor walk over a RELATIVE root terminated before
    its first step and answered False for everything under it -
    ``python -m scripts.tb2_report .`` from inside a trial then searched the
    task's own checkout and reported a fixture document as a graded row.

    L-3 (round 6): resolving both sides also means a candidate can resolve
    OUT from under the root. One that does is excluded, never searched.
    """
    root = root.resolve()
    candidate = candidate.resolve()
    if candidate == root:
        # The root is where the search starts; it is not inside anything.
        return False
    ancestors: list[Path] = []
    for parent in candidate.parents:
        ancestors.append(parent)
        if parent == root:
            break
    else:
        # L-3 (round 7): ``candidate`` is not under ``root`` at all. Both
        # sides are resolved first, so a symlink under a trial pointing
        # outside the root arrives here already resolved out from under it,
        # the walk runs off the top, and answering False said "not inside a
        # trial" - which made the escapee a SEARCH ROOT and another project's
        # receipts this run's. A path that escapes the root is never a trial
        # OF THIS ROOT, so it is excluded exactly as a checkout is.
        return True
    return any(parent.joinpath("agent").is_dir() for parent in ancestors)


def _find_trials(root: Path) -> list[Path]:
    """Every Pier trial under ``root``, at the shallowest depth that has one.

    Depth order is the whole point: pointed at the job directory, the trials
    are one level down and everything below them is the task's own repository
    checkout, which may hold any directory name at all. The deeper glob is
    consulted only when the shallower one found nothing.
    """
    for pattern in _TRIAL_GLOBS:
        found = [
            path
            for path in sorted(root.glob(pattern))
            if _is_trial(path) and not _inside_a_trial(root, path)
        ]
        if found:
            return found
    return []


def _trial_roots(root: Path) -> list[Path]:
    """``root``, the directories directly inside it, and any Pier trial dir.

    Artifact layouts differ per workflow: a flat download, ``<root>/<task>/``,
    and Pier's ``<root>/<job-name>/<task>__<hash>/``, which is two levels down
    (three in a downloaded attestation bundle). Nothing below a trial is ever
    treated as one: below that is the checkout.

    M-1: the direct children were added unconditionally, so a report run over
    ONE trial directory - the shape a per-task artifact download has, and what
    a caller passes to look at a single task - made ``<trial>/checkout/`` a
    search root and ran the harness globs inside the task's own repository. A fixture progress document at
    ``<trial>/checkout/agent/progress.json`` then produced a row
    (``DECOY-TASK graded=yes reward=1``) that the footer counted in
    officially_graded and solved. When ``root`` owns an ``agent/`` it IS the
    trial and only its own harness subtrees are searched; the same
    ``_inside_a_trial`` guard the deeper walks use says so, so there is one
    rule about what sits inside a checkout and not two.
    """
    roots = [root]
    try:
        children = sorted(child for child in root.iterdir() if child.is_dir())
    except OSError:
        children = []
    roots.extend(child for child in children if not _inside_a_trial(root, child))
    roots.extend(trial for trial in _find_trials(root) if trial not in roots)
    return roots


def _harness_files(root: Path) -> list[tuple[Path, Path]]:
    """``(trial dir, json file)`` for every harness-owned JSON under ``root``.

    Order is stable (trial dir, then the glob list, then name) so two runs over
    the same tree read the same files in the same order.
    """
    if not root.is_dir():
        return [(root.parent, root)] if root.is_file() else []
    found: dict[Path, Path] = {}
    for trial in _trial_roots(root):
        for pattern in _HARNESS_GLOBS:
            for path in sorted(trial.glob(pattern)):
                if path.is_file():
                    found.setdefault(path, trial)
    return [(trial, path) for path, trial in found.items()]


def _trial_task_id(trial: Path) -> str:
    """The task a trial directory is named for: ``<task>__<hash>`` -> ``task``.

    M-3 (round 6): the whole directory name was used, and under Pier that name
    is ``<task>__<hash>`` - a string no progress row ever carries. A
    ``gt-run.json`` that omits ``task_id`` (the shape a trial-level receipt
    has) was therefore collected under a key nothing joined to: the row printed
    "-" for every metric sitting on disk and the footer said
    "$0.00 over 0 task(s)" for a run that had spent real tokens.

    The hash is separated at the LAST ``__``, which leaves a SWE-bench
    instance id whole (``amoffat__sh-744__<hash>`` -> ``amoffat__sh-744``);
    same semantics as verify_run_receipts.Inputs.trial_task_id. A flat
    ``<root>/<task>/`` directory carries no ``__`` at all, and then the whole
    name is the task.
    """
    task, _, _digest = trial.name.rpartition("__")
    return task or trial.name


def _authority(trial: Path, path: Path) -> int:
    """Rank of the harness-owned location ``path`` sits in under ``trial``."""
    try:
        parts = path.relative_to(trial).parts
    except ValueError:  # pragma: no cover - a file root, handled by the caller
        return len(_GT_RUN_AUTHORITY)
    head = parts[0] if len(parts) > 1 else ""
    try:
        return _GT_RUN_AUTHORITY.index(head)
    except ValueError:
        return len(_GT_RUN_AUTHORITY)


def collect_rows(
    roots: list[Path | str],
    *,
    warn: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per progress task, joined to its gt-run.json when there is one.

    ``warn`` is called once per task whose receipt was found in more than one
    harness-owned location. Both locations are ours, so the loser cannot be
    dropped silently; ``agent/`` wins because that is where the agent writes it.
    """
    files: list[tuple[Path, Path]] = []
    for root in roots:
        files.extend(_harness_files(Path(root)))

    metrics: dict[str, tuple[int, Path, dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for trial, path in files:
        body = _read_json(path)
        if body is None:
            continue
        if path.name == _GT_RUN_NAME:
            # `<task>/agent/gt-run.json` is the usual layout, so the trial
            # directory name is the fallback when the receipt omits task_id.
            task_id = body.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                task_id = _trial_task_id(trial)
            rank = _authority(trial, path)
            held = metrics.get(task_id)
            if held is None:
                metrics[task_id] = (rank, path, body)
                continue
            winner, loser = (held[1], path) if held[0] <= rank else (path, held[1])
            if rank < held[0]:
                metrics[task_id] = (rank, path, body)
            if warn is not None:
                warn(
                    f"{task_id}: {_GT_RUN_NAME} found in two harness-owned "
                    f"locations; reporting {winner} and ignoring {loser}"
                )
            continue
        if body.get("schema") != PROGRESS_SCHEMA:
            continue
        model = str(body.get("model") or body.get("effective_model") or "")
        for task in body.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            rows.append(
                {
                    "task": task_id,
                    "state": str(task.get("state") or ""),
                    "reward": _num(task.get("reward")),
                    "graded": task.get("official_verifier") is True,
                    "error": str(task.get("error_code") or ""),
                    "model": model,
                }
            )

    for row in rows:
        held = metrics.get(row["task"])
        row["has_metrics"] = held is not None
        receipt = held[2] if held is not None else {}
        row["turns"] = _num(receipt.get("agent_turn_calls"))
        row["calls"] = _num(receipt.get("provider_calls"))
        row["provider_failed_calls"] = _num(receipt.get("provider_failed_calls"))
        row["input_tokens"] = _num(receipt.get("input_tokens"))
        row["cached_tokens"] = _num(receipt.get("cached_tokens"))
        row["output_tokens"] = _num(receipt.get("output_tokens"))
    return sorted(rows, key=lambda row: row["task"])


# The SUMMARY header spelling -> the key it is returned under. The header row
# is the contract; column order is not. Reading the sixth cell as `calls`
# because it was the sixth cell in the one SUMMARY we had is how a reordered
# table gets silently parsed as reward=calls, and a wrong baseline is worse
# than no baseline.
_BASELINE_COLUMNS = {
    "task": "task",
    "solved": "solved",
    "reward / error": "reward",
    "prompt tok": "prompt_tokens",
    "comp tok": "completion_tokens",
    "calls": "calls",
}


def _table_cells(line: str) -> list[str] | None:
    """The cells of a markdown table row, or None if the line is not one."""
    line = line.strip()
    if not line.startswith("|") or not line.endswith("|"):
        return None
    return [cell.strip() for cell in line.strip("|").split("|")]


def _header_index(cells: list[str]) -> dict[str, int] | None:
    """Map each wanted column to its position, or None if this is not the header."""
    named = {" ".join(cell.split()).casefold(): index for index, cell in enumerate(cells)}
    if "task" not in named:
        return None
    missing = [name for name in _BASELINE_COLUMNS if name not in named]
    if missing:
        raise BaselineUnreadable(
            "baseline SUMMARY table header is missing required column(s): "
            + ", ".join(missing)
            + f". Header read as: {', '.join(cells)}"
        )
    return {key: named[name] for name, key in _BASELINE_COLUMNS.items()}


def parse_baseline_summary(text: str) -> dict[str, dict[str, Any]]:
    """Read the frozen GT-off SUMMARY.md result table, by its header row.

    The table looks like::

        | task | solved | reward / error | prompt tok | comp tok | calls |
        |---|---|---|---|---|---|
        | extract-elf | yes | {"reward": 1.0} | 5,561,759 | 4,842,368 | 42 |

    Columns are located by name, so a SUMMARY that reorders or inserts one
    still parses and a SUMMARY that is missing one fails loudly instead of
    pairing against whatever sat in that position. Prose above the table is
    skipped; the table ends at the first line that is not a table row, so a
    second, unrelated table further down cannot leak rows in.
    """
    index: dict[str, int] | None = None
    baseline: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        cells = _table_cells(line)
        if cells is None:
            if index is not None:
                break
            continue
        if index is None:
            index = _header_index(cells)
            continue
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue  # the |---|---| separator
        if len(cells) <= max(index.values()):
            continue
        solved = cells[index["solved"]]
        if solved not in ("yes", "no"):
            continue  # a totals row or any other row that is not a task
        try:
            calls = int(cells[index["calls"]].replace(",", ""))
            prompt_tokens = int(cells[index["prompt_tokens"]].replace(",", ""))
            completion_tokens = int(cells[index["completion_tokens"]].replace(",", ""))
        except ValueError:
            continue
        try:
            reward = _num((json.loads(cells[index["reward"]]) or {}).get("reward"))
        except (ValueError, AttributeError):
            reward = None
        baseline[cells[index["task"]]] = {
            "solved": solved == "yes",
            "reward": reward,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "calls": calls,
        }
    if index is None:
        raise BaselineUnreadable(
            "no markdown table with a 'task' header column was found in the "
            "baseline SUMMARY; pairing against an empty baseline would report "
            "'GT-off solved 0', which is not what the baseline says"
        )
    return baseline


# --- rendering -------------------------------------------------------------


def _cost(row: dict[str, Any], prompt_price: float, completion_price: float) -> float | None:
    """Token-derived cost, or None when no tokens were recorded.

    Cached input tokens are billed at the prompt rate here because the pricing
    block carries no cached rate; when one is added this is the single place
    that has to change.
    """
    if not row["has_metrics"]:
        return None
    inp = row["input_tokens"]
    out = row["output_tokens"]
    if inp is None and out is None:
        return None
    return (inp or 0) * prompt_price + (out or 0) * completion_price


def _cells(
    row: dict[str, Any],
    prompt_price: float,
    completion_price: float,
    baseline: dict[str, dict[str, Any]] | None,
) -> list[str]:
    inp, cached, out = row["input_tokens"], row["cached_tokens"], row["output_tokens"]
    cost = _cost(row, prompt_price, completion_price)
    hit = f"{100.0 * cached / inp:.1f}%" if inp and cached is not None else "-"
    cells = [
        row["task"],
        # A report is routinely run over several roots at once, and two roots
        # can be two models. Collecting the model and not printing it is how a
        # mixed-model table reads as one experiment.
        row["model"] or "-",
        "-" if row["reward"] is None else f"{row['reward']:.0f}",
        "yes" if row["graded"] else "no",
        "-" if row["turns"] is None else f"{row['turns']:,.0f}",
        "-" if row["calls"] is None else f"{row['calls']:,.0f}",
        "-" if row["provider_failed_calls"] is None else f"{row['provider_failed_calls']:,.0f}",
        "-" if inp is None else f"{inp:,.0f}",
        "-" if cached is None else f"{cached:,.0f}",
        hit,
        "-" if out is None else f"{out:,.0f}",
        "-" if cost is None else f"{cost:.2f}",
    ]
    if baseline is not None:
        pair = baseline.get(row["task"])
        cells.append("-" if pair is None else ("yes" if pair["solved"] else "no"))
        cells.append("-" if pair is None else f"{pair['calls']:,.0f}")
    state = row["state"] + (f"/{row['error']}" if row["error"] else "")
    cells.append(state or "-")
    return cells


_HEADERS = ["task", "model", "reward", "graded", "turns", "calls", "nofc",
            "in_tok", "cached", "cache%", "out_tok", "cost$"]
_BASELINE_HEADERS = ["base", "base_calls"]
_WIDTHS = [30, 34, 7, 7, 7, 7, 6, 13, 13, 8, 11, 9]
_BASELINE_WIDTHS = [6, 11]
# Identity columns read left to right; every measurement is a number and reads
# right to left. Aligning by name, not by index, so adding a column cannot
# silently re-align the two that were there.
_LEFT_ALIGNED = frozenset({"task", "model"})


def _padded(cells: list[str], headers: list[str], widths: list[int]) -> str:
    return "".join(
        cell.ljust(width) if header in _LEFT_ALIGNED else cell.rjust(width)
        for cell, header, width in zip(cells, headers, widths, strict=False)
    )


def format_report(
    rows: list[dict[str, Any]],
    *,
    prompt_price: float,
    completion_price: float,
    baseline: dict[str, dict[str, Any]] | None = None,
    markdown: bool = False,
    rate_source: str = "explicit rates",
) -> str:
    headers = list(_HEADERS) + (list(_BASELINE_HEADERS) if baseline is not None else []) + ["state/error"]
    body = [_cells(row, prompt_price, completion_price, baseline) for row in rows]

    # `cells`/`headers` carry state/error as one extra trailing entry that is
    # rendered unpadded, so every zip against `widths` truncates on purpose.
    lines: list[str] = []
    if markdown:
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        lines.extend("| " + " | ".join(cells) + " |" for cells in body)
    else:
        widths = list(_WIDTHS) + (list(_BASELINE_WIDTHS) if baseline is not None else [])
        header = _padded(headers, headers, widths) + "  state/error"
        lines.append(header)
        lines.append("-" * len(header))
        for cells in body:
            lines.append(_padded(cells, headers, widths) + "  " + cells[-1])
        lines.append("-" * len(header))

    lines.extend(_footer(rows, prompt_price, completion_price, baseline, rate_source))
    return "\n".join(lines)


def _footer(
    rows: list[dict[str, Any]],
    prompt_price: float,
    completion_price: float,
    baseline: dict[str, dict[str, Any]] | None,
    rate_source: str,
) -> list[str]:
    graded = [row for row in rows if row["graded"]]
    solved = [row for row in graded if (row["reward"] or 0) > 0]
    missing = [row for row in rows if not row["has_metrics"]]
    costed = [row for row in rows if _cost(row, prompt_price, completion_price) is not None]
    total_in = sum(row["input_tokens"] or 0 for row in costed)
    total_cached = sum(row["cached_tokens"] or 0 for row in costed)
    total_out = sum(row["output_tokens"] or 0 for row in costed)
    total_cost = sum(_cost(row, prompt_price, completion_price) or 0.0 for row in costed)

    lines = [
        f"tasks={len(rows)}  officially_graded={len(graded)}  solved={len(solved)}",
        f"tokens: input={total_in:,}  cached={total_cached:,} "
        f"({100.0 * total_cached / total_in if total_in else 0:.1f}% cache hit)  "
        f"output={total_out:,}  total={total_in + total_out:,}",
        f"cost ${total_cost:.2f} over {len(costed)} task(s) at {rate_source}; {_COST_CAVEAT}",
    ]
    if missing:
        lines.append(
            f"no {_GT_RUN_NAME} for {len(missing)} task(s), so they carry no metrics and "
            f"no cost: {', '.join(row['task'] for row in missing)}"
        )
    if baseline is not None:
        paired = [row for row in rows if row["task"] in baseline]
        off_solved = sum(1 for row in paired if baseline[row["task"]]["solved"])
        on_solved = sum(1 for row in paired if row["graded"] and (row["reward"] or 0) > 0)
        lines.append(f"paired {len(paired)}, GT-off solved {off_solved}, GT-on solved {on_solved}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="+", help="artifact roots, searched recursively")
    parser.add_argument("--rates", help="route manifest carrying a pricing block")
    parser.add_argument("--prompt-price", type=float, help="USD per prompt token")
    parser.add_argument("--completion-price", type=float, help="USD per completion token")
    parser.add_argument("--baseline", help="frozen GT-off SUMMARY.md to pair against")
    parser.add_argument("--markdown", action="store_true", help="emit a markdown table")
    args = parser.parse_args(argv)

    try:
        prompt_price, completion_price, rate_source = resolve_rates(
            rates_path=args.rates,
            prompt_price=args.prompt_price,
            completion_price=args.completion_price,
        )
    except RateUnavailable as exc:
        print(f"tb2_report: {exc}", file=sys.stderr)
        return 2

    rows = collect_rows(
        args.roots, warn=lambda message: print(f"tb2_report: {message}", file=sys.stderr)
    )
    if not rows:
        print(
            f"tb2_report: no {PROGRESS_SCHEMA} receipt with tasks found in the "
            "harness-owned locations under "
            f"{', '.join(str(root) for root in args.roots)}",
            file=sys.stderr,
        )
        return 2

    baseline = None
    if args.baseline:
        # L-4: the read itself is an input fault like any other - a missing
        # path, a directory, a summary pasted in latin-1 - and every other one
        # here returns 2 with a message. A traceback out of a workflow step
        # reads as the harness having crashed rather than as a bad argument.
        try:
            text = Path(args.baseline).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"tb2_report: cannot read --baseline {args.baseline}: {exc}", file=sys.stderr)
            return 2
        try:
            baseline = parse_baseline_summary(text)
        except BaselineUnreadable as exc:
            print(f"tb2_report: {exc}", file=sys.stderr)
            return 2

    print(
        format_report(
            rows,
            prompt_price=prompt_price,
            completion_price=completion_price,
            baseline=baseline,
            markdown=args.markdown,
            rate_source=rate_source,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
