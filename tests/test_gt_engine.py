"""gt_engine unit tests: bridge sequence, exit-code parsing, GT-off byte
identity of truncation, indexer detection, profile-2 default fan-out, bash
edit bridges, the gate-kernel submit probe, the task-start capsule, and a
GT-off agent-loop smoke with a stubbed provider (no API key required)."""
from __future__ import annotations

import copy
import os
from typing import Any

import pytest

from gt_engine.bridge import (
    DeliveredSpan,
    apply_profile_env,
    bash_edit_target,
    parse_exit_code,
)
from gt_engine.context import smart_truncate
from gt_engine.indexer import ensure_index, is_code_repo
from nano.agent import Agent
from nano.providers import StepResult, ToolCall, Usage


@pytest.fixture(autouse=True)
def _gt_env_isolation():
    """Strip GT_* env before each test and undo anything a test (or
    apply_profile_env's direct os.environ writes) added - no cross-test leak."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("GT_")}
    for k in saved:
        del os.environ[k]
    yield
    for k in [k for k in os.environ if k.startswith("GT_")]:
        del os.environ[k]
    os.environ.update(saved)

try:
    import groundtruth  # noqa: F401
    HAVE_GT = True
except ImportError:
    HAVE_GT = False

requires_gt = pytest.mark.skipif(not HAVE_GT, reason="groundtruth not installed")


# --------------------------------------------------------------------------- #
# exit-code parsing (decision C: tools.py:172 flattens the code into a string)
# --------------------------------------------------------------------------- #
def test_parse_exit_code_success_is_zero():
    assert parse_exit_code("any output", is_error=False) == 0


def test_parse_exit_code_from_toolerror_text():
    out = "ERROR: FAILED tests/x.py::test_a\n[exit code 1]"
    assert parse_exit_code(out, is_error=True) == 1


def test_parse_exit_code_multiline_and_negative():
    assert parse_exit_code("ERROR: boom\nmore\n[exit code 137]", True) == 137
    assert parse_exit_code("ERROR: killed\n[exit code -9]", True) == -9


def test_parse_exit_code_unparsable_is_none():
    # Timeout / dead shell / dispatch errors carry no "[exit code N]" suffix.
    assert parse_exit_code("ERROR: Command exceeded timeout of 60s", True) is None
    assert parse_exit_code("", True) is None
    # The marker must be terminal, not mid-text.
    assert parse_exit_code("[exit code 3] and then more text", True) is None


# --------------------------------------------------------------------------- #
# GT-off byte identity: smart_truncate with no deliveries == stock truncation
# --------------------------------------------------------------------------- #
def _make_messages(n_results: int = 4, result_len: int = 500,
                   big_input: int = 0) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "task"}]
    for i in range(n_results):
        inp: dict[str, Any] = {"command": "echo hi"}
        if big_input:
            inp["new"] = "y" * big_input
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "bash", "input": inp}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}",
             "content": f"out{i}:" + ("x" * result_len), "is_error": False}]})
    return msgs


@pytest.mark.parametrize("budget,big_input", [
    (10_000_000, 0),   # under budget: no-op
    (1200, 0),         # phase 1 only
    (300, 5000),       # phase 1 exhausts, phase 2 shrinks tool_use inputs
])
def test_smart_truncate_byte_identical_when_no_deliveries(budget, big_input):
    msgs = _make_messages(big_input=big_input)
    agent = Agent.__new__(Agent)  # no provider needed for _truncate_if_needed
    agent.truncation_char_budget = budget

    stock_msgs, stock_tr = copy.deepcopy(msgs), []
    Agent._truncate_if_needed(agent, stock_msgs, stock_tr)

    gt_msgs, gt_tr = copy.deepcopy(msgs), []
    smart_truncate(gt_msgs, gt_tr, char_budget=budget, delivered_spans=[])

    assert gt_msgs == stock_msgs
    assert gt_tr == stock_tr


def test_smart_truncate_drops_evidence_free_blocks_first():
    msgs = _make_messages(n_results=3, result_len=500)
    evidence = "pkg/a.py:1:helper\n"
    warn = "note: check callers\n"
    msgs[2]["content"][0]["content"] += "\n" + evidence   # block t0: VERIFIED
    msgs[4]["content"][0]["content"] += "\n" + warn       # block t1: WARNING
    spans = [DeliveredSpan(text=evidence, tier="VERIFIED",
                           evidence_type="def_ref_partition", dedup_key="k1"),
             DeliveredSpan(text=warn, tier="WARNING",
                           evidence_type="cochange_partner", dedup_key="k2")]
    # A tight budget drops all three blocks; the ORDER must be: the
    # evidence-free block (t2, the NEWEST) first, then WARNING (t1), then
    # VERIFIED (t0) last of all - the stock pass would have gone t0,t1,t2.
    tr: list[dict[str, Any]] = []
    smart_truncate(msgs, tr, char_budget=100, delivered_spans=spans)
    order = [t["tool_use_id"] for t in tr if t["type"] == "truncation"][:3]
    assert order == ["t2", "t1", "t0"]
    for i in (2, 4, 6):
        assert str(msgs[i]["content"][0]["content"]).startswith("[truncated")


def test_smart_truncate_keeps_phase_two():
    # Only oversized tool_use inputs can free the space: phase 2 must run.
    msgs = _make_messages(n_results=1, result_len=10, big_input=8000)
    tr: list[dict[str, Any]] = []
    smart_truncate(msgs, tr, char_budget=500, delivered_spans=[])
    assert str(msgs[1]["content"][0]["input"]["new"]).startswith("[truncated")


# --------------------------------------------------------------------------- #
# indexer: code-repo detection (GT dormant on non-code roots)
# --------------------------------------------------------------------------- #
def test_is_code_repo_detection(tmp_path):
    (tmp_path / "notes.txt").write_text("just text", encoding="utf-8")
    assert not is_code_repo(str(tmp_path))
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert is_code_repo(str(tmp_path))


def test_is_code_repo_skips_vendored_dirs(tmp_path):
    nm = tmp_path / "node_modules" / "dep"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("//", encoding="utf-8")
    assert not is_code_repo(str(tmp_path))


def test_ensure_index_non_code_root_returns_none(tmp_path):
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    assert ensure_index(str(tmp_path)) is None
    assert ensure_index(str(tmp_path / "missing")) is None
    assert ensure_index(None) is None


# --------------------------------------------------------------------------- #
# bridge: the full production sequence against a real graph.db
# --------------------------------------------------------------------------- #
@pytest.fixture
def indexed_repo(tmp_path, monkeypatch):
    if not HAVE_GT:
        pytest.skip("groundtruth not installed")
    monkeypatch.setenv("GT_GATEWAY", "1")
    monkeypatch.setenv("GT_GATEWAY_NATIVE", "1")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "alpha.py").write_text(
        "def helper(x, y):\n    return x + y\n\n\n"
        "def caller_a(v):\n    return helper(v, 1)\n", encoding="utf-8")
    (pkg / "beta.py").write_text(
        "def helper(a, b, c):\n    return a * b * c\n\n\n"
        "def caller_b(v):\n    return helper(v, 2, 3)\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from pkg.alpha import caller_a\n\n\ndef run():\n"
        "    return caller_a(1)\n", encoding="utf-8")
    db = ensure_index(str(tmp_path))
    if db is None:
        pytest.skip("gt-index binary unavailable")
    from gt_engine.bridge import GTBridge
    return GTBridge(repo_root=str(tmp_path), graph_db=db)


_AMBIGUOUS_GREP = "grep -rn helper ."
_GREP_OUT = ("pkg/alpha.py:1:def helper(x, y):\n"
             "pkg/beta.py:1:def helper(a, b, c):\n")


@requires_gt
def test_bridge_delivers_sealed_pure_suffix(indexed_repo):
    b = indexed_repo
    out = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    # Pure suffix (TITO law 1): the original observation bytes are untouched.
    assert out.startswith(_GREP_OUT)
    assert len(out) > len(_GREP_OUT)
    # Sealed delivery: envelope stamped, chain advanced, dedup key recorded.
    assert len(b.deliveries) == 1
    sealed = b.deliveries[0]
    assert sealed.evidence_type == "def_ref_partition"
    assert sealed.receipt_state == "delivered"
    assert sealed.rendered_bytes_hash
    assert b.chain_head
    assert sealed.dedup_key in b.episode.delivered_dedup
    # Native render: no GT tag, no test identity, within budget.
    delta = out[len(_GREP_OUT):]
    assert "<gt-" not in delta.lower()
    assert len(delta) <= 4001  # delta + at most one inserted newline
    # Span tracked for evidence-aware truncation.
    assert b.delivered_spans[0].evidence_type == "def_ref_partition"


@requires_gt
def test_bridge_dedup_suppresses_repeat(indexed_repo):
    b = indexed_repo
    first = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert first != _GREP_OUT
    second = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert second == _GREP_OUT  # same fact never delivered twice
    assert len(b.deliveries) == 1


@requires_gt
def test_bridge_error_observation_never_breaks(indexed_repo):
    b = indexed_repo
    out = b.enrich("bash", {"command": "false"},
                   "ERROR: \n[exit code 1]", True)
    assert out.startswith("ERROR: ")  # raw output survives whatever GT does


@requires_gt
def test_bridge_internal_fault_returns_raw_output(indexed_repo):
    b = indexed_repo
    b.graph_db = 12345  # type: ignore[assignment] - poison the state
    out = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert out == _GREP_OUT  # correct-or-quiet: fault -> unchanged


@requires_gt
def test_bridge_repo_rel_paths(indexed_repo):
    b = indexed_repo
    rel = b._repo_rel(b.repo_root.replace("/", "\\") + "\\pkg\\alpha.py")
    assert rel == "pkg/alpha.py"  # decision J: repo-relative, forward slashes


# --------------------------------------------------------------------------- #
# FIX 1: profile-2 default fan-out (production parity, AGENTS.md §C / W8)
# --------------------------------------------------------------------------- #
@requires_gt
def test_profile_default_fans_out_profile_2():
    apply_profile_env()
    # Profile-1 core + Super-Mode members the edit-turn producers need.
    for flag in ("GT_GATEWAY", "GT_GATEWAY_NATIVE", "GT_GATEWAY_EDIT_BRIDGES",
                 "GT_PATCH_DELTA", "GT_CHANGE_SURFACE", "GT_LOC_RESLOT"):
        assert os.environ.get(flag) == "1", flag
    # Determinism: durable cross-session memory never set by the bridge.
    assert not any(k.startswith("GT_XSESSION") for k in os.environ)


@requires_gt
def test_profile_explicit_member_value_wins(monkeypatch):
    monkeypatch.setenv("GT_PATCH_DELTA", "0")  # user kill-switch
    apply_profile_env()
    assert os.environ["GT_PATCH_DELTA"] == "0"
    assert os.environ.get("GT_GATEWAY") == "1"


@requires_gt
def test_profile_explicit_legacy_token_is_minimal_pair(monkeypatch):
    monkeypatch.setenv("GT_RL_PROFILE", "off")
    apply_profile_env()
    assert os.environ.get("GT_GATEWAY") == "1"
    assert os.environ.get("GT_GATEWAY_NATIVE") == "1"
    assert "GT_PATCH_DELTA" not in os.environ  # no profile fan-out


@requires_gt
def test_profile_explicit_token_resolves_that_profile(monkeypatch):
    monkeypatch.setenv("GT_RL_PROFILE", "1")
    apply_profile_env()
    assert os.environ.get("GT_GATEWAY_EDIT_BRIDGES") == "1"  # profile-1 member
    assert "GT_PATCH_DELTA" not in os.environ  # super-mode only


@requires_gt
def test_profile_unknown_token_never_dark(monkeypatch):
    monkeypatch.setenv("GT_RL_PROFILE", "99")
    apply_profile_env()
    assert os.environ.get("GT_GATEWAY") == "1"  # minimal pair fallback


# --------------------------------------------------------------------------- #
# FIX 1 (live proof): an edit with edit_before_after fires an edit-family
# envelope under the profile-2 defaults (patch_delta was dark before).
# --------------------------------------------------------------------------- #
@requires_gt
def test_edit_fires_signature_mismatch_under_profile_2(indexed_repo, tmp_path):
    apply_profile_env()  # profile-2 defaults on top of the fixture's pair
    b = indexed_repo
    b.issue_text = "helper returns the wrong sum"
    alpha = tmp_path / "pkg" / "alpha.py"
    before = alpha.read_text(encoding="utf-8")
    after = before.replace("def helper(x, y):", "def helper(x):").replace(
        "return x + y", "return x")
    alpha.write_text(after, encoding="utf-8")
    out = b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
                   edit_before=before, edit_after=after)
    assert [d.evidence_type for d in b.deliveries] == ["signature_mismatch"]
    assert out.startswith("edited")           # pure suffix
    assert "helper()" in out                  # the arity diagnostic delivered
    assert "<gt-" not in out.lower()


# --------------------------------------------------------------------------- #
# FIX 3: bash-mediated edit bridges (production _gateway_edit_bridges port)
# --------------------------------------------------------------------------- #
def test_bash_edit_target_shapes():
    assert bash_edit_target("sed -i 's/a/b/' pkg/alpha.py") == "pkg/alpha.py"
    assert bash_edit_target("cat > src/x.js <<'EOF'\ncode\nEOF") == "src/x.js"
    assert bash_edit_target("echo hi >> pkg/mod.py") == "pkg/mod.py"
    assert bash_edit_target(
        "python -c \"open('pkg/z.py','w').write('x')\"") == "pkg/z.py"
    assert bash_edit_target(
        "git apply <<'EOF'\n--- a/pkg/y.py\n+++ b/pkg/y.py\n@@\nEOF") == "pkg/y.py"
    assert bash_edit_target("grep -rn helper .") is None
    assert bash_edit_target("cat pkg/alpha.py") is None
    # A heredoc BODY line must not read as a redirect target.
    assert bash_edit_target(
        "cat > /tmp/t.txt <<'EOF'\n> fake.py\nEOF") is None


@requires_gt
def test_bash_edit_bridges_round_trip(indexed_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("GT_GATEWAY_EDIT_BRIDGES", "1")
    b = indexed_repo
    alpha = tmp_path / "pkg" / "alpha.py"
    pre_content = alpha.read_text(encoding="utf-8")
    args = {"command": "sed -i 's/return x + y/return x+y+0/' pkg/alpha.py"}
    b.capture_bash_preimage(args)
    assert b._bash_preimages == {"pkg/alpha.py": pre_content}
    # simulate the dispatched edit
    alpha.write_text(pre_content.replace("return x + y", "return x+y+0"),
                     encoding="utf-8")
    changed, eba = b._bash_bridges(args["command"])
    assert changed == ("pkg/alpha.py",)
    assert eba == {"pkg/alpha.py": (pre_content,
                                    alpha.read_text(encoding="utf-8"))}


@requires_gt
def test_bash_edit_bridges_creation_before_is_none(indexed_repo, tmp_path,
                                                   monkeypatch):
    monkeypatch.setenv("GT_GATEWAY_EDIT_BRIDGES", "1")
    b = indexed_repo
    args = {"command": "cat > pkg/newmod.py <<'EOF'\nX = 1\nEOF"}
    b.capture_bash_preimage(args)
    assert b._bash_preimages == {"pkg/newmod.py": None}  # positive creation
    (tmp_path / "pkg" / "newmod.py").write_text("X = 1\n", encoding="utf-8")
    changed, eba = b._bash_bridges(args["command"])
    assert changed == ("pkg/newmod.py",)
    assert eba == {"pkg/newmod.py": (None, "X = 1\n")}


@requires_gt
def test_bash_edit_bridges_off_by_flag(indexed_repo):
    b = indexed_repo  # fixture sets only GT_GATEWAY/NATIVE - bridges flag off
    b.capture_bash_preimage({"command": "sed -i 's/a/b/' pkg/alpha.py"})
    assert b._bash_preimages == {}
    assert b._bash_bridges("sed -i 's/a/b/' pkg/alpha.py") == ((), None)


@requires_gt
def test_bash_edit_fires_edit_producer_end_to_end(indexed_repo, tmp_path):
    """A sed edit (no edit_file tool) reaches the edit-turn producers: the
    bridges reconstruct changed_files + before/after and patch_delta fires."""
    apply_profile_env()  # profile-2: GT_GATEWAY_EDIT_BRIDGES + GT_PATCH_DELTA
    b = indexed_repo
    b.issue_text = "helper returns the wrong sum"
    cmd = ("sed -i 's/def helper(x, y):/def helper(x):/; "
           "s/return x + y/return x/' pkg/alpha.py")
    b.capture_bash_preimage({"command": cmd})
    alpha = tmp_path / "pkg" / "alpha.py"
    src = alpha.read_text(encoding="utf-8")
    alpha.write_text(src.replace("def helper(x, y):", "def helper(x):")
                     .replace("return x + y", "return x"), encoding="utf-8")
    out = b.enrich("bash", {"command": cmd}, "", False)
    assert [d.evidence_type for d in b.deliveries] == ["signature_mismatch"]
    assert "helper()" in out  # the arity diagnostic reached the observation


@requires_gt
def test_bash_edit_enrich_records_edited_file(indexed_repo, monkeypatch):
    monkeypatch.setenv("GT_GATEWAY_EDIT_BRIDGES", "1")
    b = indexed_repo
    args = {"command": "sed -i 's/x/y/' pkg/alpha.py"}
    b.capture_bash_preimage(args)
    b.enrich("bash", args, "", False)
    assert b.edited_files == ["pkg/alpha.py"]
    assert b._bash_preimages == {}  # consumed by the observation


# --------------------------------------------------------------------------- #
# FIX 2: gate-kernel submit probe (positive executed evidence only)
# --------------------------------------------------------------------------- #
@requires_gt
def test_submit_probe_blocks_on_real_syntax_error(indexed_repo, tmp_path):
    (tmp_path / "pkg" / "broken.py").write_text("def oops(:\n    pass\n",
                                                encoding="utf-8")
    b = indexed_repo
    b.edited_files.append("pkg/broken.py")
    nudge = b.submit_probe()
    assert nudge is not None
    assert nudge.startswith("pre-commit hook failed:")  # native refusal form
    assert "SyntaxError" in nudge
    assert "pkg/broken.py" in nudge          # repo-relative, the agent's own file
    assert "<gt-" not in nudge.lower()
    # Sealed as a delivery so the audit sees it.
    sealed = b.deliveries[-1]
    assert sealed.evidence_type == "syntax_result"
    assert sealed.receipt_state == "delivered"
    assert sealed.rendered_bytes_hash
    assert b.chain_head


@requires_gt
def test_submit_probe_quiet_on_clean_or_unedited(indexed_repo):
    b = indexed_repo
    assert b.submit_probe() is None          # nothing edited: clean allow
    b.edited_files.append("pkg/alpha.py")    # syntactically fine
    assert b.submit_probe() is None


@requires_gt
def test_submit_probe_fails_open_after_max_bounces(indexed_repo, tmp_path):
    (tmp_path / "pkg" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    b = indexed_repo
    b.edited_files.append("pkg/broken.py")
    assert b.submit_probe() is not None      # first refusal
    assert b.submit_probe() is None          # gate_overridden: never deadlock


# --------------------------------------------------------------------------- #
# FIX 4: task-start capsule (v1r brief) against the real fixture graph.db
# --------------------------------------------------------------------------- #
@requires_gt
def test_task_start_capsule_fires_and_seals(indexed_repo):
    pytest.importorskip("numpy")  # v1r brief hard-requires numpy upstream
    apply_profile_env()  # profile-2: native/minimal brief form
    b = indexed_repo
    b.issue_text = ("helper in pkg/alpha.py returns the wrong sum; "
                    "caller_a breaks when helper drops an argument")
    cap = b.task_start()
    assert cap is not None
    assert cap.startswith("Requirements to satisfy (from the issue):")
    assert "helper" in cap
    assert "<gt-" not in cap.lower()         # frame unwrapped, no tag leaks
    assert len(cap) <= 4000                  # law 8 budget
    sealed = b.deliveries[-1]
    assert sealed.evidence_type == "obligations"
    assert sealed.receipt_state == "delivered"
    assert b.chain_head


@requires_gt
def test_task_start_abstains_without_issue_text(indexed_repo):
    b = indexed_repo
    b.issue_text = ""
    assert b.task_start() is None
    assert b.deliveries == []


def test_agent_prepends_task_start_capsule():
    class _StubBridge:
        issue_text = ""
        delivered_spans: list[Any] = []

        def task_start(self):
            return "CAPSULE"

    steps = [StepResult(text="hi", tool_calls=[], stop_reason="end_turn",
                        usage=_usage())]
    agent = Agent(provider=_ScriptedProvider(steps), system="s")
    agent._gt = _StubBridge()
    result = agent.run("the task")
    assert result.transcript[0]["content"] == "the task\n\nCAPSULE"


# --------------------------------------------------------------------------- #
# GT-off agent-loop smoke: stubbed provider, no API key, gt_root=None
# --------------------------------------------------------------------------- #
class _ScriptedProvider:
    """Provider stub: yields a scripted sequence of StepResults."""

    def __init__(self, steps):
        self._steps = iter(steps)

    def step(self, messages, tools, system):
        return next(self._steps)


def _usage():
    return Usage(input_tokens=10, output_tokens=5, cache_read_tokens=0)


def test_agent_gt_off_smoke_end_to_end():
    steps = [
        StepResult(text=None, tool_calls=[ToolCall(
            id="c1", name="bash", arguments={"command": "echo nano-smoke"})],
            stop_reason="tool_use", usage=_usage()),
        StepResult(text="done", tool_calls=[], stop_reason="end_turn",
                   usage=_usage()),  # first done: challenged once
        StepResult(text=None, tool_calls=[ToolCall(
            id="c2", name="bash", arguments={"command": "echo verified"})],
            stop_reason="tool_use", usage=_usage()),
        StepResult(text="all done", tool_calls=[], stop_reason="end_turn",
                   usage=_usage()),
    ]
    agent = Agent(provider=_ScriptedProvider(steps), system="s")
    assert agent._gt is None  # gt_root defaulted: GT fully dormant
    result = agent.run("say hi")
    assert result.stop_reason == "end_turn"
    assert result.final_text == "all done"
    # GT-off byte identity: the initial user message is exactly the task
    # (no task-start capsule path touched it).
    assert result.transcript[0]["content"] == "say hi"
    tool_outputs = [t for t in result.transcript if t["type"] == "tool_result"]
    assert any("nano-smoke" in t["output"] for t in tool_outputs)


def test_agent_gt_root_on_non_code_dir_gets_dormant_bridge(tmp_path):
    """Phase-3 contract change: a non-code gt_root gets a DORMANT bridge
    (graph_db None, producers abstain) that can WAKE when the agent writes
    source files - it is no longer None-forever."""
    if not HAVE_GT:
        pytest.skip("groundtruth not installed")
    (tmp_path / "data.txt").write_text("no code here", encoding="utf-8")
    steps = [StepResult(text="hi", tool_calls=[], stop_reason="end_turn",
                        usage=_usage())]
    agent = Agent(provider=_ScriptedProvider(steps), system="s",
                  gt_root=str(tmp_path))
    assert agent._gt is not None
    assert agent._gt.graph_db is None      # dormant: no graph substrate
    result = agent.run("t")
    assert result.stop_reason == "end_turn"
    # Dormant bridge delivers nothing: the initial message is the raw task
    # (task_start abstains without a graph) and no evidence was sealed.
    assert result.transcript[0]["content"] == "t"
    assert agent._gt.deliveries == []


# --------------------------------------------------------------------------- #
# WIRE 1: L6 freshness - wake-from-dormant + reindex-after-edit (GT_L6_FRESH)
# --------------------------------------------------------------------------- #
def _node_count(db: str) -> int:
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    finally:
        con.close()


@requires_gt
def test_l6_wake_from_dormant_on_source_edit(tmp_path, monkeypatch):
    """A task that STARTS non-code becomes code: the dormant bridge wakes on
    the first source-file edit and the new module's symbols are in the graph."""
    monkeypatch.setenv("GT_GATEWAY", "1")
    monkeypatch.setenv("GT_GATEWAY_NATIVE", "1")
    monkeypatch.setenv("GT_L6_FRESH", "1")
    (tmp_path / "notes.txt").write_text("non-code at start", encoding="utf-8")
    from gt_engine import create_bridge
    b = create_bridge(str(tmp_path))
    if b is None:
        pytest.skip("gt-index binary unavailable")
    assert b.graph_db is None                       # dormant
    content = "def fresh_fn(a):\n    return a * 2\n"
    (tmp_path / "newmod.py").write_text(content, encoding="utf-8")
    out = b.enrich("edit_file", {"path": str(tmp_path / "newmod.py")},
                   "edited", False, edit_before=None, edit_after=content)
    assert out.startswith("edited")                 # never breaks the turn
    assert b.graph_db is not None                   # WOKE
    import sqlite3
    con = sqlite3.connect(b.graph_db)
    rows = con.execute(
        "SELECT name FROM nodes WHERE name='fresh_fn'").fetchall()
    con.close()
    assert rows == [("fresh_fn",)]                  # the agent's new code


@requires_gt
def test_l6_reindex_after_edit_grows_graph(tmp_path, monkeypatch):
    """A second new module (calling the first) re-indexes: node count grows
    and the cross-file CALLS edge to the NEW symbol exists - the evidence the
    full-reindex decision buys (gt-index -file cannot mint new incoming edges)."""
    monkeypatch.setenv("GT_GATEWAY", "1")
    monkeypatch.setenv("GT_GATEWAY_NATIVE", "1")
    monkeypatch.setenv("GT_L6_FRESH", "1")
    from gt_engine import create_bridge
    (tmp_path / "newmod.py").write_text(
        "def fresh_fn(a):\n    return a * 2\n", encoding="utf-8")
    b = create_bridge(str(tmp_path))
    if b is None or b.graph_db is None:
        pytest.skip("gt-index binary unavailable")
    n0 = _node_count(b.graph_db)
    c2 = "from newmod import fresh_fn\n\n\ndef consumer(v):\n    return fresh_fn(v)\n"
    (tmp_path / "second.py").write_text(c2, encoding="utf-8")
    b.enrich("edit_file", {"path": str(tmp_path / "second.py")}, "edited",
             False, edit_before=None, edit_after=c2)
    n1 = _node_count(b.graph_db)
    assert n1 > n0                                  # graph re-indexed
    import sqlite3
    con = sqlite3.connect(b.graph_db)
    edges = con.execute(
        "SELECT s.name, t.name, e.type FROM edges e "
        "JOIN nodes s ON s.id=e.source_id JOIN nodes t ON t.id=e.target_id "
        "WHERE e.type='CALLS'").fetchall()
    con.close()
    assert ("consumer", "fresh_fn", "CALLS") in edges


@requires_gt
def test_l6_flag_off_never_wakes(tmp_path, monkeypatch):
    monkeypatch.setenv("GT_GATEWAY", "1")
    monkeypatch.setenv("GT_GATEWAY_NATIVE", "1")
    # Explicit kill-switch (an unset flag would be fanned to "1" by the
    # Profile-2 defaults create_bridge applies; explicit user value wins).
    monkeypatch.setenv("GT_L6_FRESH", "0")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    from gt_engine import create_bridge
    b = create_bridge(str(tmp_path))
    if b is None:
        pytest.skip("groundtruth unavailable")
    content = "def f():\n    return 1\n"
    (tmp_path / "m.py").write_text(content, encoding="utf-8")
    b.enrich("edit_file", {"path": str(tmp_path / "m.py")}, "edited", False,
             edit_before=None, edit_after=content)
    assert b.graph_db is None                       # gated off: stays dormant


# --------------------------------------------------------------------------- #
# WIRE 2: executed covering-RED at post-edit + submit covering head
# --------------------------------------------------------------------------- #
@pytest.fixture
def covering_repo(tmp_path, monkeypatch):
    """An indexed repo whose OWN test file covers helper() through a FACT-tier
    import-resolved CALLS edge - the covering lane's selection substrate."""
    if not HAVE_GT:
        pytest.skip("groundtruth not installed")
    monkeypatch.setenv("GT_GATEWAY", "1")
    monkeypatch.setenv("GT_GATEWAY_NATIVE", "1")
    monkeypatch.setenv("GT_VERIFY_EXECUTE", "1")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text(
        "def helper(x, y):\n    return x + y\n\n\n"
        "def caller_a(v):\n    return helper(v, 1)\n", encoding="utf-8")
    (tmp_path / "test_alpha.py").write_text(
        "from pkg.alpha import helper\n\n\n"
        "def test_helper_sum():\n    assert helper(1, 2) == 3\n",
        encoding="utf-8")
    db = ensure_index(str(tmp_path))
    if db is None:
        pytest.skip("gt-index binary unavailable")
    from gt_engine.bridge import GTBridge
    return GTBridge(repo_root=str(tmp_path), graph_db=db)


def _break_helper(root, crash=True):
    alpha = root / "pkg" / "alpha.py"
    before = alpha.read_text(encoding="utf-8")
    repl = ("return x + y + undefined_name" if crash else "return x + y")
    after = before.replace("return x + y", repl)
    alpha.write_text(after, encoding="utf-8")
    return alpha, before, after


@requires_gt
def test_covering_red_fires_at_post_edit(covering_repo, tmp_path):
    """The TB-critical live fire: a real edit that breaks a covering test
    delivers the Format-D RED into the SAME post-edit observation, sealed,
    with ZERO test identity in the delivered bytes."""
    b = covering_repo
    alpha, before, after = _break_helper(tmp_path)
    out = b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
                   edit_before=before, edit_after=after)
    assert out.startswith("edited")                       # pure suffix
    delta = out[len("edited"):]
    assert "A covering test fails:" in delta              # Format-D head
    assert "undefined_name" in delta                      # the real signal
    assert "pkg/alpha.py" in delta                        # the where-to-fix
    # Leak law: no test identity, no GT tag, in the delivered bytes.
    from groundtruth.runtime.native_render import contains_gt_tag, contains_test_identity
    assert not contains_gt_tag(delta)
    assert not contains_test_identity(delta)
    assert "test_alpha" not in delta and "test_helper" not in delta
    # Sealed as THIS observation's one dose.
    assert [d.evidence_type for d in b.deliveries] == ["covering_verdict"]
    assert b.deliveries[0].receipt_state == "delivered"
    assert b.chain_head
    # The executed verdict is cached for the submit gate's covering head.
    assert b._last_covering is not None
    assert b._last_covering.get("verdict") == "fail"


@requires_gt
def test_covering_green_stays_quiet_and_latches(covering_repo, tmp_path):
    """A green covering run delivers nothing (correct-or-quiet), caches the
    non-fail verdict for the submit fast-path, and the per-file latch bounds
    the cost: a second edit to the same file never re-runs the tests."""
    b = covering_repo
    alpha = tmp_path / "pkg" / "alpha.py"
    before = alpha.read_text(encoding="utf-8")
    after = before.replace("return helper(v, 1)", "return helper(v, 2)")
    alpha.write_text(after, encoding="utf-8")
    out = b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
                   edit_before=before, edit_after=after)
    assert "A covering test fails:" not in out
    assert b._last_covering is not None
    assert b._last_covering.get("verdict") == "pass"
    assert "pkg/alpha.py" in b._covering_fired
    # Latch: instrument _run_covering - a second edit to the SAME file must
    # never re-run the covering tests (production's fire-once cost bound).
    calls: list[int] = []
    b._run_covering = (  # type: ignore[method-assign]
        lambda changed: (calls.append(1), (None, []))[1])
    out2 = b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
                    edit_before=after, edit_after=after)
    assert out2.startswith("edited")
    assert calls == []


@requires_gt
def test_covering_off_by_flag(covering_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("GT_VERIFY_EXECUTE", raising=False)
    b = covering_repo
    alpha, before, after = _break_helper(tmp_path)
    out = b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
                   edit_before=before, edit_after=after)
    assert "A covering test fails:" not in out
    assert b._last_covering is None                 # gate off: no execution


# --------------------------------------------------------------------------- #
# WIRE 3: CompletionCertificate delivery at the submit boundary
# --------------------------------------------------------------------------- #
@requires_gt
def test_submit_cert_block_on_covering_red(covering_repo, tmp_path, monkeypatch):
    """Broken edit -> the submit probe re-runs the covering head fresh (G-2:
    a cached FAIL is stale at submit) and delivers the NOT-CLEAN cert as the
    native per-head pre-commit block."""
    monkeypatch.setenv("GT_CERT_DELIVERY", "1")
    b = covering_repo
    alpha, before, after = _break_helper(tmp_path)
    b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
             edit_before=before, edit_after=after)
    nudge = b.submit_probe()
    assert nudge is not None
    assert nudge.startswith("pre-commit hook failed:")
    assert "run covering tests" in nudge            # the cert's covering head
    assert nudge.rstrip().endswith("commit aborted (exit 1)")
    assert "test_alpha" not in nudge                # leak law on the cert too
    assert "<gt-" not in nudge.lower()
    sealed = b.deliveries[-1]
    assert sealed.evidence_type == "submit_refusal"
    # Fail-open: the second probe never deadlocks the run.
    assert b.submit_probe() is None


@requires_gt
def test_submit_cert_block_on_syntax_error(indexed_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("GT_CERT_DELIVERY", "1")
    (tmp_path / "pkg" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    b = indexed_repo
    b.edited_files.append("pkg/broken.py")
    nudge = b.submit_probe()
    assert nudge is not None
    assert "check syntax" in nudge                  # per-head cert line
    assert "Failed" in nudge
    assert b.deliveries[-1].evidence_type == "submit_refusal"


@requires_gt
def test_submit_cert_allow_never_blocks(indexed_repo, monkeypatch):
    """Clean episode + GT_CERT_DELIVERY on: the cert is head-derived and a
    clean head ALWAYS returns None - the cert can never invent a block."""
    monkeypatch.setenv("GT_CERT_DELIVERY", "1")
    b = indexed_repo
    b.edited_files.append("pkg/alpha.py")           # syntactically fine
    assert b.submit_probe() is None
    assert b.deliveries == []


@requires_gt
def test_submit_cert_fault_falls_back_to_plain_refusal(indexed_repo, tmp_path,
                                                       monkeypatch):
    """A poisoned cert renderer degrades to the existing native refusal -
    a real block is never silenced by a cert fault (correct-or-quiet)."""
    monkeypatch.setenv("GT_CERT_DELIVERY", "1")
    import groundtruth.runtime.native_render as nr
    monkeypatch.setattr(nr, "render_completion_cert_native",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    (tmp_path / "pkg" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    b = indexed_repo
    b.edited_files.append("pkg/broken.py")
    nudge = b.submit_probe()
    assert nudge is not None
    assert "syntax_error" in nudge                  # the plain refusal form
    assert b.deliveries[-1].evidence_type == "syntax_result"


# --------------------------------------------------------------------------- #
# WIRE 6: on-disk delivery ledger (both-sides observability)
# --------------------------------------------------------------------------- #
def _read_ledger(root) -> list[dict[str, Any]]:
    import json
    p = root / ".gt" / "gt_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


@requires_gt
def test_ledger_one_line_per_sealed_delivery(covering_repo, tmp_path,
                                             monkeypatch):
    """Ledger line count == len(bridge.deliveries) across a multi-delivery run
    (gateway dose + covering dose + submit refusal), each line joinable to its
    sealed envelope by rendered_bytes_hash; no wall clock, no payload bytes."""
    monkeypatch.setenv("GT_CERT_DELIVERY", "1")
    b = covering_repo
    b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)  # gateway
    alpha, before, after = _break_helper(tmp_path)
    b.enrich("edit_file", {"path": str(alpha)}, "edited", False,
             edit_before=before, edit_after=after)                   # covering
    b.submit_probe()                                                 # submit
    lines = _read_ledger(tmp_path)
    assert len(lines) == len(b.deliveries) >= 2
    by_hash = {ln["rendered_bytes_hash"]: ln for ln in lines}
    for sealed in b.deliveries:
        ln = by_hash[sealed.rendered_bytes_hash]     # 1:1 join (dose law)
        assert ln["evidence_type"] == sealed.evidence_type
        assert ln["dedup_key"] == sealed.dedup_key
        assert ln["len_shipped_chars"] > 0
        assert "timestamp" not in ln and "time" not in ln
        # Leak law applies to the ledger too: no payload, no test identity.
        assert "test_alpha" not in str(ln)


@requires_gt
def test_ledger_write_failure_never_unseals(indexed_repo, monkeypatch):
    b = indexed_repo
    monkeypatch.setattr(type(b), "_ledger_path",
                        lambda self: (_ for _ in ()).throw(RuntimeError()))
    out = b.enrich("bash", {"command": _AMBIGUOUS_GREP}, _GREP_OUT, False)
    assert len(out) > len(_GREP_OUT)                # delivery still happened
    assert len(b.deliveries) == 1                   # and stayed sealed


def test_ledger_absent_when_gt_off(tmp_path):
    steps = [StepResult(text="hi", tool_calls=[], stop_reason="end_turn",
                        usage=_usage())]
    agent = Agent(provider=_ScriptedProvider(steps), system="s")  # gt_root=None
    assert agent._gt is None
    agent.run("t")
    assert not (tmp_path / ".gt").exists()
