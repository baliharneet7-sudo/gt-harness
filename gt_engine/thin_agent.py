"""GT on the baseline harness, the GitNexus way.

GitNexus (abhigyanpatwari/GitNexus eval/agents/gitnexus_agent.py) is a
``DefaultAgent`` subclass that overrides one method: ``execute_actions`` runs
each action with ``self.env.execute`` and appends a knowledge-graph block to a
search's observation (5 s timeout, silent on a miss). Its index is built in
``env.start()``, before the agent's clock. Nothing else in the loop changes:
same model, same model kwargs, same environment, no supervisor, no per-action
bookkeeping.

The GT-on arm this replaces was a different harness from its own baseline
(run 36448406432 vs the space-bunny GT-off runs, all 30 easy-task losses
traced): a supervisor SIGKILLed the agent's daemons before grading (6 TB2
losses), ``max_tokens=16384`` truncated long turns into format errors (4),
per-action workspace snapshots and a SHADOW push pipeline taxed every command
(2), and the agent/model/mini-swe version all differed. None of that was GT's
content.

This module keeps GT's content - grep/read/edit/failure blocks, the gt-*
tools, graph freshness after edits, the one-time submit review - and delivers
it the GitNexus way:

* ``GTAttachedAgent.execute_actions`` = stock ``execute_actions`` + one
  ``AttachedDelivery.observe_turn`` call bounded by ``AUGMENT_TIMEOUT_SECONDS``;
* edits are detected by ``EditProbe`` (git status / stat), only for commands
  that could write - never a full-workspace hash per action;
* the graph is built before the agent loop (``build_attached_session``), and at
  install time when the launcher runs ``prebuild``;
* no task-start plan block: GitNexus has none, and ours was keyword-anchored
  noise with a truncated requirement list (run 36450157395, 7 of 7 plans).
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent

AUGMENT_TIMEOUT_SECONDS = 5.0  # GitNexus AUGMENT_TIMEOUT_SECONDS
MAX_TRACKED_BYTES = 1_000_000
MAX_WALK_ENTRIES = 50_000
MAX_PRECACHE_BYTES = 20_000_000
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "target", "dist", "build"}
# First words of commands that never write to the workspace.
_READ_ONLY = {
    "cat", "head", "tail", "nl", "less", "more", "grep", "egrep", "fgrep", "rg", "ag", "ls", "tree",
    "wc", "file", "stat", "pwd", "which", "type", "echo", "printf", "diff", "cmp", "du", "df", "env",
    "whoami", "id", "uname", "date", "true", "false", "test", "[", "cd", "gt-query", "gt-context",
    "gt-impact", "gt-tests", "gt-verify", "gt-changes", "gt-check", "gt-help", "gt-plan",
}
_READ_ONLY_GIT = {"status", "diff", "log", "show", "grep", "blame", "ls-files", "rev-parse", "branch"}
# Redirections that do not write into the workspace.
_HARMLESS_REDIRECT = re.compile(r"\d?>&\d|\d?>\s*/dev/null")


def could_write(command: str) -> bool:
    """False only when every segment is a known read-only command with no
    redirection into a file. Anything unrecognised may write."""
    from gt_engine.grep_augment import _segments

    if ">" in _HARMLESS_REDIRECT.sub("", command) or " tee " in f" {command} ":
        return True
    segments = _segments(command)
    if not segments:
        return True
    for segment in segments:
        head = Path(segment[0]).name
        if head == "sed":
            if any(token.startswith(("-i", "--in-place")) for token in segment[1:]):
                return True
            continue
        if head == "find":
            if any(token in {"-delete", "-exec", "-execdir", "-fprint", "-fprint0", "-fprintf", "-fls",
                             "-ok", "-okdir"} for token in segment[1:]):
                return True
            continue
        if head == "git":
            if len(segment) < 2 or segment[1] not in _READ_ONLY_GIT:
                return True
            continue
        if head not in _READ_ONLY:
            return True
    return False


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TRACKED_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


@dataclass
class EditProbe:
    """Which workspace files an action changed, and their before/after text,
    without hashing the workspace: ``git status`` + stat for a git checkout,
    a bounded stat walk over source files otherwise."""

    root: Path
    last_seen: dict[str, str] = field(default_factory=dict)
    git: bool = False
    _before: dict[str, tuple[int, int] | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.git = (self.root / ".git").exists() and self._git(["rev-parse", "--git-dir"]) is not None
        if not self.git:
            self._precache()
            return
        # A file already dirty when the task starts (a benchmark's setup diff)
        # has its on-disk text as "before", never HEAD's: otherwise the setup
        # diff would be reported as the agent's first edit.
        for rel in self._candidates():
            text = _read_text(self.root / rel)
            if text is not None:
                self.last_seen[rel] = text

    def _git(self, args: list[str]) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                  text=True, timeout=20, errors="replace")
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    def _walk(self) -> list[str]:
        from gt_engine.indexer import SOURCE_EXTS

        found: list[str] = []
        stack = [self.root]
        while stack and len(found) < MAX_WALK_ENTRIES:
            directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIRS:
                        stack.append(Path(entry.path))
                elif Path(entry.name).suffix.lower() in SOURCE_EXTS:
                    found.append(Path(entry.path).relative_to(self.root).as_posix())
        return found

    def _precache(self) -> None:
        total = 0
        for rel in self._walk():
            text = _read_text(self.root / rel)
            if text is None:
                continue
            total += len(text)
            if total > MAX_PRECACHE_BYTES:
                return
            self.last_seen[rel] = text

    def _candidates(self) -> list[str]:
        if not self.git:
            return self._walk()
        out = self._git(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        if out is None:
            return []
        paths: list[str] = []
        records = out.split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if len(record) < 4:
                continue
            status, path = record[:2], record[3:]
            if "R" in status or "C" in status:
                index += 1  # the rename source follows as its own record
            paths.append(path)
        return paths

    def _stat(self, rel: str) -> tuple[int, int] | None:
        try:
            info = (self.root / rel).stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def before(self) -> None:
        self._before = {rel: self._stat(rel) for rel in self._candidates()}

    def after(self) -> dict[str, tuple[str | None, str | None]]:
        """``{path: (before_text, after_text)}`` for every file whose stat
        changed since ``before()``; ``None`` marks absent/unreadable."""
        changes: dict[str, tuple[str | None, str | None]] = {}
        for rel in self._candidates():
            now = self._stat(rel)
            if rel in self._before and self._before[rel] == now:
                continue
            after = _read_text(self.root / rel) if now is not None else None
            before = self.last_seen.get(rel)
            if before is None and self.git:
                before = self._git(["show", f"HEAD:{rel}"])
            if before == after:
                continue
            changes[rel] = (before, after)
            if after is not None:
                self.last_seen[rel] = after
        return changes


def syntax_rows(root: Path, changes: dict[str, tuple[str | None, str | None]]) -> list[dict]:
    """Parse each changed source file's post-image with gt-index's inspector,
    falling back to ``ast`` for Python (the push runtime's contract)."""
    import ast

    rows: list[dict] = []
    parseable = {path: after for path, (_before, after) in changes.items()
                 if after is not None and Path(path).suffix.lower() in
                 {".py", ".pyi", ".go", ".ts", ".tsx", ".js", ".jsx", ".rs"}}
    parsed: dict[str, dict] = {}
    try:
        from gt_engine.parser_inspection import ParserInspectionRequest, inspect_sources

        requests = [ParserInspectionRequest(f"thin:{path}", path, text.encode("utf-8"))
                    for path, text in parseable.items()]
        parsed = {str(row["request_id"])[5:]: row for row in inspect_sources(requests)}
    except Exception:  # noqa: BLE001 - the parser is optional; ast covers Python
        parsed = {}
    for path, text in parseable.items():
        row = parsed.get(path)
        if row is not None:
            rows.append({"path": path, "valid": bool(row.get("complete")),
                         "diagnostics": list(row.get("diagnostics") or ())})
        elif path.endswith((".py", ".pyi")):
            try:
                ast.parse(text, filename=path)
                rows.append({"path": path, "valid": True})
            except SyntaxError as exc:
                rows.append({"path": path, "valid": False, "line": int(exc.lineno or 0),
                             "error": type(exc).__name__})
    return rows


def test_outcome(command: str, output: str, returncode: int | None) -> str:
    try:
        from gt_engine.runtime_observation import compile_execution_evidence

        evidence = compile_execution_evidence(command=command, output=output, returncode=returncode,
                                              action_id=0, repository_revision="")
        return str(getattr(evidence, "observed_test_outcome", "") or "")
    except Exception:  # noqa: BLE001 - an unparsed run is simply not a test run
        return ""


class GTAttachedAgent(DefaultAgent):
    """``DefaultAgent`` with GT's observations appended to its own actions."""

    def __init__(self, model: Any, env: Any, *, delivery: Any, adapter: Any, **kwargs: Any):
        super().__init__(model, env, **kwargs)
        self.gt_delivery = delivery
        self.gt_adapter = adapter
        self.gt_probe = EditProbe(Path(getattr(adapter, "repo_root", "") or env.config.cwd or "."))
        self.gt_lock = threading.Lock()  # serializes GT's engine work (worker vs note_edit)
        self.gt_pending_lock = threading.Lock()  # guards gt_pending_edits only
        self.gt_worker: threading.Thread | None = None
        self.gt_refresher: threading.Thread | None = None
        self.gt_pending_edits: list[str] = []
        self.gt_stats = {"augment_timeouts": 0, "augment_skipped_busy": 0, "augment_faults": 0,
                         "augment_seconds": 0.0, "probe_seconds": 0.0, "submit_review_held": 0}

    # -- the one override ----------------------------------------------------

    def execute_actions(self, message: dict) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        outputs: list[dict] = []
        facts: list[dict | None] = []
        held = False
        for action in actions:
            command = str(action.get("command", "") or "")
            if held:
                # The baseline's Submitted ends the turn at the submit; actions
                # after a held submit are not run either.
                outputs.append({"output": "(not run: it followed the submit command in the same turn)",
                                "returncode": -1, "exception_info": ""})
                facts.append(None)
                continue
            review = self._held_submit(command)
            if review:
                outputs.append({"output": review, "returncode": 0, "exception_info": ""})
                facts.append(None)
                held = True
                continue
            pre_edit_graph = str(getattr(getattr(self.gt_adapter, "engine_state", None), "graph_path", "") or "")
            probing = could_write(command)
            if probing:
                self._timed_probe(self.gt_probe.before)
            outputs.append(self.env.execute(action))  # Submitted propagates exactly as in DefaultAgent
            facts.append(self._facts(command, outputs[-1], pre_edit_graph, probing))
        outputs = self._augment([str(a.get("command", "") or "") for a in actions], outputs, facts)
        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))

    # -- pieces --------------------------------------------------------------

    def _held_submit(self, command: str) -> str:
        from gt_engine.miniswe_evidence import is_submit_command

        if not is_submit_command(command):
            return ""
        try:
            review = self.gt_delivery.submit_review_once()
        except Exception:  # noqa: BLE001 - a review never costs the submit
            return ""
        if review:
            self.gt_stats["submit_review_held"] += 1
        return review

    def _timed_probe(self, fn):
        started = time.perf_counter()
        try:
            return fn()
        except Exception:  # noqa: BLE001 - edit facts are optional
            return None
        finally:
            self.gt_stats["probe_seconds"] += time.perf_counter() - started

    def _facts(self, command: str, output: dict, pre_edit_graph: str, probing: bool) -> dict:
        text = str(output.get("output") or "")
        returncode = output.get("returncode")
        changes = (self._timed_probe(self.gt_probe.after) or {}) if probing else {}
        if changes:
            self._note_edit(list(changes))
        return {
            "changes": changes,
            "syntax": tuple(syntax_rows(self.gt_probe.root, changes)) if changes else (),
            "pre_edit_graph": pre_edit_graph,
            "returncode": returncode,
            "test_outcome": test_outcome(command, text, returncode),
            "output": text,
        }

    def _take_pending(self) -> list[str]:
        with self.gt_pending_lock:
            pending, self.gt_pending_edits = self.gt_pending_edits, []
        return pending

    def _note_edit(self, paths: list[str]) -> None:
        """Mark the graph stale for these paths; the amend happens on the next
        graph read (refresh-before-query). Never waits on a busy worker: the
        paths are queued and the worker applies them before its next turn."""
        with self.gt_pending_lock:
            self.gt_pending_edits.extend(paths)
        if not self.gt_lock.acquire(blocking=False):
            return
        try:
            self._apply_edits(self._take_pending())
        finally:
            self.gt_lock.release()

    def _apply_edits(self, paths: list[str]) -> None:
        adapter = self.gt_adapter
        try:
            if getattr(adapter, "phase", "") != "IMPLEMENT" and hasattr(adapter, "begin_implement"):
                adapter.begin_implement()
            adapter.note_edit(tuple(dict.fromkeys(paths)))
        except Exception as exc:  # noqa: BLE001 - bookkeeping never costs the action
            self._journal("gt_thin_note_edit_fault", error=type(exc).__name__)

    def _augment(self, commands: list[str], outputs: list[dict], facts: list[dict | None]) -> list[dict]:
        if self.gt_worker is not None and self.gt_worker.is_alive():
            self.gt_stats["augment_skipped_busy"] += 1
            return outputs
        result: dict[str, list[dict]] = {}
        ready = threading.Event()

        def work() -> None:
            with self.gt_lock:
                pending = self._take_pending()
                if pending:
                    self._apply_edits(pending)
                try:
                    result["outputs"] = self.gt_delivery.observe_turn(commands, outputs, facts)
                except Exception as exc:  # noqa: BLE001 - enrichment never costs the observation
                    self.gt_stats["augment_faults"] += 1
                    self._journal("gt_augment_fault", error=type(exc).__name__)
                ready.set()

        started = time.perf_counter()
        self.gt_worker = threading.Thread(target=work, name="gt-augment", daemon=True)
        self.gt_worker.start()
        ready.wait(AUGMENT_TIMEOUT_SECONDS)
        self.gt_stats["augment_seconds"] += time.perf_counter() - started
        if not ready.is_set():
            self.gt_stats["augment_timeouts"] += 1
            self._journal("gt_augment_timeout", seconds=AUGMENT_TIMEOUT_SECONDS)
            return outputs
        # The observation is out; bring the graph current while the model
        # thinks - on its own thread, so the next turn's observation never
        # waits for an amend (it answers from the verifiably unchanged graph).
        self._start_refresh()
        return result.get("outputs", outputs)

    def _start_refresh(self) -> None:
        """One amend at a time, off every path the agent waits on. An edit
        during an amend supersedes it (the engine refuses to publish a graph
        of a tree that moved on) and the next turn amends again."""
        if getattr(self.gt_adapter, "graph_fresh", True):
            return
        if self.gt_refresher is not None and self.gt_refresher.is_alive():
            return
        refresher = threading.Thread(target=self._refresh_after_turn, name="gt-refresh", daemon=True)
        refresher.start()
        self.gt_refresher = refresher

    def _refresh_after_turn(self) -> None:
        """Amend a stale graph after the observation was returned (refresher
        thread). Reads during a turn never amend inline in the thin arm
        (adapter.passive_refresh_inline = False)."""
        adapter = self.gt_adapter
        if getattr(adapter, "graph_fresh", True):
            return
        started = time.perf_counter()
        try:
            from gt_engine.tool_server import refresh_if_stale

            refresh_if_stale(self.gt_delivery.session)
        except Exception as exc:  # noqa: BLE001 - freshness never costs the run
            self._journal("gt_thin_refresh_fault", error=type(exc).__name__)
        finally:
            self.gt_stats["refresh_seconds"] = self.gt_stats.get("refresh_seconds", 0.0) + (
                time.perf_counter() - started)

    def _journal(self, event: str, **row: Any) -> None:
        store = getattr(self.gt_adapter, "store", None)
        if store is not None:
            try:
                store.append(event, **row)
            except Exception:  # noqa: BLE001 - journaling never costs the action
                pass

    def serialize(self, *extra_dicts: dict) -> dict:
        try:
            metrics = dict(self.gt_delivery.metrics())
        except Exception:  # noqa: BLE001 - metrics never cost the trajectory
            metrics = {}
        metrics.update({key: round(value, 3) if isinstance(value, float) else value
                        for key, value in self.gt_stats.items()})
        return super().serialize({"info": {"gt": {"mode": "attached_thin", "metrics": metrics}}}, *extra_dicts)


def build_attached_session(*, task: str, cwd: str, state_dir: str, task_id: str,
                           model: str = "", resolved_model: str = "",
                           embedding_budget_seconds: float = 0.0):
    """The GT engine for one task with its graph already built: adapter,
    SHADOW session, attached delivery (tools + augmenters). Synchronous by
    design - it runs before the agent loop, as GitNexus's ``env.start()``."""
    from gt_engine.engine_state import RuntimeLayout
    from gt_engine.gt_session import GTMode, GTSession, GTSessionConfig
    from gt_engine.indexer import ensure_index_with_receipt
    from gt_engine.miniswe_controller import Predicate
    from gt_engine.miniswe_integration import MiniSweAdapter
    from gt_engine.runtime_observation import capture_workspace
    from gt_engine.task_contract import extract_task_contract
    from gt_engine.verification_contract import compile_obligation_predicates

    os.environ["GT_PERSISTENT_PLAN"] = "0"
    # The adapter's failure paths read the delivery mode: attached GT only
    # adds, so a lost graph leaves the stock agent running.
    os.environ["GT_DELIVERY_MODE"] = "attached"
    layout = RuntimeLayout.resolve(workspace=cwd, state_root=state_dir, task_id=task_id)
    contract = extract_task_contract(task)
    compiled = compile_obligation_predicates(contract)
    predicates = tuple(Predicate(compiled[item.obligation_id].predicate_id, item.text)
                       for item in contract.obligations if item.obligation_id in compiled)
    adapter = MiniSweAdapter(layout=layout, task_id=task_id, state_dir=state_dir,
                             predicates=predicates, contract=contract, repo_root=cwd,
                             graph_db=None, issue_text=task, requested_model=model,
                             resolved_model=resolved_model)
    adapter.lsp_promotion_enabled = False
    # Reads the agent did not ask for never wait on an amend; GTAttachedAgent
    # amends after each turn instead (_refresh_after_turn).
    adapter.passive_refresh_inline = False
    adapter.record_repository_snapshot(
        capture_workspace(layout.workspace, excluded_roots=layout.excluded_roots), boundary="task_start")
    started = time.perf_counter()

    def build():
        return ensure_index_with_receipt(
            cwd, layout=layout, excluded_roots=layout.excluded_roots,
            contract_store_path=layout.contract_store_path,
            source_revision=adapter.repository_revision,
            embedding_budget_seconds=embedding_budget_seconds)

    class _Done:
        def __init__(self, fn):
            try:
                self._value, self._exc = fn(), None
            except BaseException as exc:  # noqa: BLE001 - carried to the adapter's poll
                self._value, self._exc = None, exc

        def done(self) -> bool:
            return True

        def result(self):
            if self._exc is not None:
                raise self._exc
            return self._value

    adapter._startup_index = _Done(build)
    adapter._background_graph_builder = lambda: _Done(build)
    adapter._poll_startup_index()
    adapter.store.append("gt_thin_index_ready", seconds=round(time.perf_counter() - started, 3),
                         graph=str(getattr(adapter.engine_state, "graph_path", "") or ""))
    session = GTSession(
        GTSessionConfig(task_id=adapter.task_id, repo_root=cwd, state_dir=state_dir, graph_db="",
                        capabilities=(), issue_text=task, mode=GTMode.SHADOW,
                        capability_modes={}, disabled_capabilities=("typed_actions",),
                        delivery_path="compiled"),
        engine=adapter,
    )
    from gt_engine.attached_delivery import AttachedDelivery

    delivery = AttachedDelivery(session)
    delivery.deliver_plan = False
    adapter.attached_delivery = delivery
    return adapter, session, delivery, layout


def prebuild(argv: list[str] | None = None) -> int:
    """Build the task's graph during agent setup (outside the agent clock).
    The run's ``ensure_index_with_receipt`` then reuses it: the graph cache is
    keyed by workspace path and source manifest, not by task."""
    import argparse

    parser = argparse.ArgumentParser(prog="gt_engine.thin_agent prebuild")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args(argv)
    try:
        build_attached_session(task="", cwd=args.cwd, state_dir=args.state_dir, task_id="prebuild")
    except Exception as exc:  # noqa: BLE001 - the run builds it itself if this fails
        print(f"gt prebuild failed: {type(exc).__name__}: {exc}")
        return 0
    print("gt prebuild done")
    return 0


if __name__ == "__main__":
    import sys

    if sys.argv[1:2] == ["prebuild"]:
        raise SystemExit(prebuild(sys.argv[2:]))
    raise SystemExit("usage: python -m gt_engine.thin_agent prebuild --cwd DIR --state-dir DIR")
