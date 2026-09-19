"""Cross-host greedy comparison of model-probe receipts.

Offline: every receipt is produced by scripts.model_identity_probe against the
fake provider in tests/test_model_identity_probe.py.
"""

from __future__ import annotations

import json

from scripts import model_identity_compare as compare
from scripts import model_identity_probe as probe
from tests.test_model_identity_probe import (  # noqa: F401  (autouse fixture)
    FakeProvider,
    _no_real_transport,
    _run,
    _write_refs,
)

# --------------------------------------------------------------------------
# greedy, across hosts
# --------------------------------------------------------------------------


def _probe_receipt(tmp_path, monkeypatch, capsys, name, content, *extra, **overrides):
    refs = tmp_path / "refs.json"
    if not refs.exists():
        _write_refs(tmp_path)
    fake = FakeProvider(refs, content=content, **overrides)
    args = extra or ("--provider", name)
    _, receipt, _ = _run(tmp_path, monkeypatch, capsys, fake, *args, refs=refs)
    target = tmp_path / f"{name}.json"
    (tmp_path / "receipt.json").replace(target)
    return target, receipt


def test_greedy_hash_is_recorded_per_replay(tmp_path, monkeypatch, capsys):
    _, receipt = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})

    greedy = receipt["checks"]["greedy"]
    assert greedy["severity"] == "DEFERRED"
    assert len(greedy["hashes"]) == 5
    assert all(len(h["sha256"]) == 64 for h in greedy["hashes"])


def test_compare_agreement_passes(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {"task-4": "x"})
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {"task-4": "y"})
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(b), "--json", str(out)])
    receipt = json.loads(out.read_text(encoding="utf-8"))

    # 4 of 5 agree; ceil(5/2) = 3.
    assert rc == 0
    assert receipt["mode"] == "compare"
    assert receipt["checks"]["greedy"]["severity"] == "PASS"
    pair = receipt["checks"]["greedy"]["pairs"][0]
    assert pair["hosts"] == [0, 1]
    assert pair["agreeing"] == 4
    assert pair["required"] == 3
    assert pair["severity"] == "PASS"
    per_task = {row["task"]: row["agree"] for row in pair["tasks"]}
    assert per_task["task-4"] is False and per_task["task-0"] is True


def test_compare_disagreement_fails(tmp_path, monkeypatch, capsys):
    diff = {f"task-{i}": "a" for i in range(3)}
    other = {f"task-{i}": "b" for i in range(3)}
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", diff)
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", other)
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(b), "--json", str(out)])
    receipt = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 1
    assert receipt["checks"]["greedy"]["severity"] == "FAIL"
    assert receipt["checks"]["greedy"]["pairs"][0]["agreeing"] == 2


def test_compare_needs_two_receipts_over_the_same_refs(tmp_path, monkeypatch, capsys):
    a, receipt = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    doctored = dict(receipt, refs_sha256="f" * 64)
    b = tmp_path / "b.json"
    b.write_text(json.dumps(doctored), encoding="utf-8")
    out = tmp_path / "compare.json"

    assert probe.main(["--compare", str(a), "--json", str(out)]) == 2
    assert probe.main(["--compare", str(a), str(b), "--json", str(out)]) == 2
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["error_code"] == "compare_refs_mismatch"


def test_greedy_hash_covers_content_reasoning_and_tool_calls():
    message = {
        "content": "",
        "reasoning": "r",
        "tool_calls": [{"id": "call_random", "function": {"name": "bash", "arguments": "{}"}}],
    }
    other_id = json.loads(json.dumps(message))
    other_id["tool_calls"][0]["id"] = "call_other"
    other_args = json.loads(json.dumps(message))
    other_args["tool_calls"][0]["function"]["arguments"] = '{"command": "ls"}'

    assert probe._greedy_hash(message) == probe._greedy_hash(other_id)
    assert probe._greedy_hash(message) != probe._greedy_hash(other_args)


def test_self_consistency_is_recorded(tmp_path, monkeypatch, capsys):
    _, same = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    _, drift = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {}, repeat_content="other")

    assert same["self_consistent"] is True
    assert drift["self_consistent"] is False
    assert drift["checks"]["greedy"]["self_consistent"] is False


def test_greedy_hashes_carry_completion_tokens_and_finish_reason(tmp_path, monkeypatch, capsys):
    _, receipt = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})

    row = receipt["checks"]["greedy"]["hashes"][0]
    assert row["completion_tokens"] == 64
    assert row["finish_reason"] == "length"


def test_greedy_hash_strips_whitespace():
    a = {"content": "  ok\n", "reasoning": "\nthink  "}
    b = {"content": "ok", "reasoning": "think"}

    assert probe._greedy_hash(a) == probe._greedy_hash(b)


def test_compare_excludes_non_self_consistent_receipts(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {})
    c, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "c", {}, repeat_content="drift")
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(b), str(c), "--json", str(out)])
    receipt = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 0
    greedy = receipt["checks"]["greedy"]
    assert [pair["hosts"] for pair in greedy["pairs"]] == [[0, 1]]
    assert greedy["excluded"] == [{"index": 2, "reason": "not_self_consistent"}]


def test_compare_excludes_override_receipts(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    _, receipt = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {})
    native = dict(
        receipt,
        override=True,
        provider_routing=None,
        base_url="https://api.deepseek.com",
    )
    b = tmp_path / "native.json"
    b.write_text(json.dumps(native), encoding="utf-8")
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(b), "--json", str(out)])
    result = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 2
    assert result["checks"]["greedy"]["excluded"] == [{"index": 1, "reason": "override"}]
    assert result["error_code"] == "compare_needs_two_eligible_receipts"


def test_compare_refuses_the_same_receipt_twice(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(a), "--json", str(out)])
    receipt = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 2
    assert receipt["error_code"] == "compare_duplicate_receipt"


def test_compare_refuses_two_receipts_from_the_same_host(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    copy = tmp_path / "a-copy.json"
    copy.write_bytes(a.read_bytes())
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(copy), "--json", str(out)])
    receipt = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 2
    assert receipt["error_code"] == "compare_duplicate_host"


def test_compare_reports_every_host_pair(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {})
    c, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "c", {f"task-{i}": "z" for i in range(5)})
    out = tmp_path / "compare.json"

    rc = probe.main(["--compare", str(a), str(b), str(c), "--json", str(out)])
    greedy = json.loads(out.read_text(encoding="utf-8"))["checks"]["greedy"]

    assert rc == 1
    verdicts = {tuple(pair["hosts"]): pair["severity"] for pair in greedy["pairs"]}
    assert verdicts == {(0, 1): "PASS", (0, 2): "FAIL", (1, 2): "FAIL"}


# --------------------------------------------------------------------------
# re-review follow-ups: empty output, reasoning variance, threshold, module
# --------------------------------------------------------------------------


def _compare(tmp_path, *paths):
    out = tmp_path / "compare.json"
    rc = probe.main(["--compare", *map(str, paths), "--json", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8"))


def test_empty_output_is_not_hashed(tmp_path, monkeypatch, capsys):
    _, receipt = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {}, reasoning="")

    assert receipt["checks"]["thinking"]["severity"] == "PASS"
    assert all(h["sha256"] is None for h in receipt["checks"]["greedy"]["hashes"])
    assert receipt["self_consistent"] is None


def test_empty_output_on_every_host_is_unresolved_not_agreement(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {}, reasoning="")
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {}, reasoning="")

    rc, receipt = _compare(tmp_path, a, b)

    assert rc == 2
    assert receipt["status"] == "UNRESOLVED"
    assert receipt["proven"] == []


def test_a_pair_with_no_comparable_task_is_unknown(tmp_path, monkeypatch, capsys):
    paths = []
    for name in ("a", "b"):
        _, receipt = _probe_receipt(tmp_path, monkeypatch, capsys, name, {}, reasoning="")
        forced = dict(receipt, self_consistent=True)
        path = tmp_path / f"forced-{name}.json"
        path.write_text(json.dumps(forced), encoding="utf-8")
        paths.append(path)

    rc, receipt = _compare(tmp_path, *paths)

    assert rc == 2
    pair = receipt["checks"]["greedy"]["pairs"][0]
    assert pair["compared"] == 0
    assert pair["severity"] == "UNKNOWN"
    assert receipt["status"] == "UNRESOLVED"


def test_a_host_with_different_reasoning_text_disagrees(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {}, reasoning="Plan A.")
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {}, reasoning="Plan A.")
    c, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "c", {}, reasoning="Plan C.")

    rc, receipt = _compare(tmp_path, a, b, c)

    assert rc == 1
    assert receipt["status"] == "DISAGREES"
    verdicts = {
        tuple(p["hosts"]): (p["severity"], p["agreeing"])
        for p in receipt["checks"]["greedy"]["pairs"]
    }
    assert verdicts == {(0, 1): ("PASS", 5), (0, 2): ("FAIL", 0), (1, 2): ("FAIL", 0)}


def test_exactly_half_agreeing_meets_the_majority_threshold(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(
        tmp_path,
        monkeypatch,
        capsys,
        "a",
        {"task-2": "x", "task-3": "x"},
        "--provider",
        "a",
        "--count",
        "4",
    )
    b, _ = _probe_receipt(
        tmp_path,
        monkeypatch,
        capsys,
        "b",
        {"task-2": "y", "task-3": "y"},
        "--provider",
        "b",
        "--count",
        "4",
    )

    rc, receipt = _compare(tmp_path, a, b)

    pair = receipt["checks"]["greedy"]["pairs"][0]
    assert (pair["compared"], pair["agreeing"], pair["required"]) == (4, 2, 2)
    assert pair["severity"] == "PASS"
    assert rc == 0
    assert receipt["status"] == "AGREES"
    assert receipt["proven"] == receipt["scope"]


def test_compare_lives_in_its_own_module(tmp_path, monkeypatch, capsys):
    a, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "a", {})
    b, _ = _probe_receipt(tmp_path, monkeypatch, capsys, "b", {})

    receipt = compare.run_compare([a, b])

    assert receipt["mode"] == "compare"
    assert receipt["status"] == "AGREES"
    assert receipt["does_not_prove"] == ["weights"]
