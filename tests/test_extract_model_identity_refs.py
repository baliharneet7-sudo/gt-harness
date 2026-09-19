"""The reference extractor, on a synthetic trajectory tree (the real one is not on CI)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import extract_model_identity_refs as extractor
from scripts import model_identity_probe as probe
from tests.test_model_identity_probe import COMMITTED_REFS, FINGERPRINT

# --------------------------------------------------------------------------
# the extractor
# --------------------------------------------------------------------------


def _trajectory(system: str, user: str, prompt_tokens: int, reasoning: int) -> dict[str, Any]:
    return {
        "trajectory_format": "mini-swe-agent-1.1",
        "info": {"config": {"model": {"model_kwargs": {"temperature": 1.0}}}},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {
                "role": "assistant",
                "content": "",
                "extra": {
                    "response": {
                        "model": "deepseek-v4-flash",
                        "system_fingerprint": FINGERPRINT,
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": 50,
                            "completion_tokens_details": {"reasoning_tokens": reasoning},
                            "prompt_tokens_details": {"cached_tokens": 1024},
                        },
                    }
                },
            },
        ],
    }


def _synthetic_tree(root: Path, sizes: dict[str, int]) -> None:
    for task, tokens in sizes.items():
        path = root / "matrix_cache" / task / f"job-{task}" / f"{task}__abc" / "agent"
        path.mkdir(parents=True)
        doc = _trajectory("sys\n", f"Please solve this issue: {task}\\n", tokens, 7)
        (path / "miniswe_trajectory.json").write_text(json.dumps(doc), encoding="utf-8")


def test_extractor_picks_the_smallest_prompts_verbatim(tmp_path):
    sizes = {"c": 1500, "a": 1200, "b": 1100, "d": 2000}
    _synthetic_tree(tmp_path, sizes)

    doc = extractor.extract(tmp_path, count=2, now="2026-09-19T00:00:00Z")

    assert doc["schema"] == "gt.model_identity_refs.v1"
    assert doc["baseline_id"] == "miniswe_tb2_gtoff_20260731"
    assert doc["served_snapshot"] == "DeepSeek-V4-Flash-0731"
    assert doc["system_fingerprint"] == FINGERPRINT
    assert doc["extracted_at"] == "2026-09-19T00:00:00Z"
    assert doc["population"]["trajectories"] == 4
    assert doc["population"]["reasoning_positive"] == 4
    assert [r["task"] for r in doc["refs"]] == ["b", "a"]
    first = doc["refs"][0]
    assert first["prompt_tokens"] == 1100
    assert first["reasoning_tokens"] == 7
    assert first["messages"] == [
        {"role": "system", "content": "sys\n"},
        {"role": "user", "content": "Please solve this issue: b\\n"},
    ]
    assert first["source_trajectory"] == (
        "matrix_cache/b/job-b/b__abc/agent/miniswe_trajectory.json"
    )
    raw = (tmp_path / first["source_trajectory"]).read_bytes()
    assert first["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert doc["source_trajectory_sha256"][first["source_trajectory"]] == first["source_sha256"]


def test_extractor_is_rerunnable_and_writes_json(tmp_path):
    _synthetic_tree(tmp_path / "base", {"a": 1200, "b": 1100})
    out = tmp_path / "refs.json"
    args = ["--root", str(tmp_path / "base"), "--count", "2", "--output", str(out)]

    assert extractor.main(args) == 0
    first = json.loads(out.read_text(encoding="utf-8"))
    assert extractor.main(args) == 0
    second = json.loads(out.read_text(encoding="utf-8"))
    first.pop("extracted_at")
    second.pop("extracted_at")
    assert first == second


def test_extractor_refuses_a_mixed_fingerprint(tmp_path):
    _synthetic_tree(tmp_path, {"a": 1200, "b": 1100})
    path = next((tmp_path / "matrix_cache" / "a").rglob("miniswe_trajectory.json"))
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["messages"][2]["extra"]["response"]["system_fingerprint"] = "fp_other"
    path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint"):
        extractor.extract(tmp_path, count=2)


def test_extractor_refuses_too_few_trajectories(tmp_path):
    _synthetic_tree(tmp_path, {"a": 1200})

    with pytest.raises(ValueError, match="count"):
        extractor.extract(tmp_path, count=2)


def test_bash_tool_is_the_pinned_2_2_8_schema_recorded_in_the_refs():
    """The baseline ran mini-swe-agent 2.2.8; its BASH_TOOL was verified
    byte-identical to the pinned schema. Compare against the committed refs,
    not whatever mini-swe-agent happens to be installed."""
    doc = json.loads(COMMITTED_REFS.read_text(encoding="utf-8"))

    assert doc["tools"] == extractor.BASH_TOOLS
    assert "2.2.8" in doc["tools_source"]
    assert "verified identical" in doc["tools_source"]
    assert "2.2.8" in extractor.__doc__ and "verified" in extractor.__doc__


# --------------------------------------------------------------------------
# the committed refs
# --------------------------------------------------------------------------


def test_committed_refs_file_is_valid():
    doc = json.loads(COMMITTED_REFS.read_text(encoding="utf-8"))

    assert doc["schema"] == "gt.model_identity_refs.v1"
    assert doc["baseline_id"] == "miniswe_tb2_gtoff_20260731"
    assert doc["served_snapshot"] == "DeepSeek-V4-Flash-0731"
    assert doc["system_fingerprint"] == FINGERPRINT
    assert doc["tools"] == extractor.BASH_TOOLS
    assert isinstance(doc["extracted_at"], str) and doc["extracted_at"]
    refs = doc["refs"]
    assert len(refs) == 12
    assert len({r["task"] for r in refs}) == 12
    tokens = [r["prompt_tokens"] for r in refs]
    assert tokens == sorted(tokens)
    for ref in refs:
        assert isinstance(ref["prompt_tokens"], int) and not isinstance(ref["prompt_tokens"], bool)
        assert 1000 <= ref["prompt_tokens"] <= 2400
        assert isinstance(ref["reasoning_tokens"], int) and ref["reasoning_tokens"] > 0
        assert [m["role"] for m in ref["messages"]] == ["system", "user"]
        assert all(isinstance(m["content"], str) and m["content"] for m in ref["messages"])
        assert set(ref["messages"][0]) == {"role", "content"}
        assert ref["source_trajectory"].startswith("matrix_cache/")
        assert ref["source_trajectory"].endswith("/agent/miniswe_trajectory.json")
        assert len(ref["source_sha256"]) == 64
        assert doc["source_trajectory_sha256"][ref["source_trajectory"]] == ref["source_sha256"]
    # The committed file is loadable by the probe and fits the default cap.
    loaded = probe.load_refs(COMMITTED_REFS)
    assert probe.planned_input_tokens(loaded, 5) <= probe.DEFAULT_MAX_INPUT_TOKENS
