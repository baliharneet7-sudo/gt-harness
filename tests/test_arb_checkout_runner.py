from __future__ import annotations

import pytest

from scripts.arb_adapter import RetrievalProbe
from scripts.arb_checkout_runner import (
    _load_dense_backend,
    _repo_cache_path,
    group_probes,
    run_groups,
)


def _probe(sample_id: str, repo: str, commit: str) -> RetrievalProbe:
    return RetrievalProbe(sample_id, repo, commit, "q", (), f"arb:{commit}")


def test_group_probes_is_deterministic_and_snapshot_scoped() -> None:
    groups = group_probes(
        (
            _probe("b", "z/repo", "2"),
            _probe("a", "a/repo", "1"),
            _probe("c", "z/repo", "2"),
        )
    )
    assert list(groups) == [("a/repo", "1"), ("z/repo", "2")]
    assert [item.sample_id for item in groups[("z/repo", "2")]] == ["b", "c"]


def test_repo_cache_path_rejects_path_injection(tmp_path) -> None:
    with pytest.raises(ValueError, match="invalid repository"):
        _repo_cache_path(tmp_path, "../escape")


def test_shard_validation() -> None:
    with pytest.raises(ValueError, match="shard_index"):
        run_groups(
            (),
            cache_dir="cache",
            work_dir="work",
            state_dir="state",
            output_dir="out",
            shard_index=2,
            shard_count=2,
        )


def test_shard_selection_is_deterministic() -> None:
    probes = tuple(_probe(str(i), "owner/repo", str(i)) for i in range(5))
    groups = list(group_probes(probes).items())
    assert [key for key, _ in groups[1::2]] == [("owner/repo", "1"), ("owner/repo", "3")]


def test_dense_backend_is_optional_but_required_mode_fails_closed(tmp_path) -> None:
    assert _load_dense_backend(None, require_dense=False) is None
    with pytest.raises(ValueError, match="dense model directory"):
        _load_dense_backend(None, require_dense=True)


def test_dense_backend_loads_the_pinned_snowflake_onnx_model_once(
    tmp_path, monkeypatch
) -> None:
    sentinel = object()
    calls: list[object] = []

    def fake_from_directory(path):
        calls.append(path)
        return sentinel

    monkeypatch.setattr(
        "scripts.arb_checkout_runner.SnowflakeOnnxDenseBackend.from_directory",
        fake_from_directory,
    )

    loaded = _load_dense_backend(tmp_path, require_dense=True)

    assert loaded is sentinel
    assert calls == [tmp_path]
