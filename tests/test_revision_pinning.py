"""Retention must keep a revision a delivered artifact still needs."""
import json
from pathlib import Path

from gt_engine.indexer import _pinned_revisions, _prune_superseded_revisions


def _revision(root: Path, name: str, *, pinned: bool = False) -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "graph.db").write_bytes(b"graph")
    (path / "graph.manifest.json").write_text(
        json.dumps({"graph_sha256": name}), encoding="utf-8"
    )
    if pinned:
        (path / "pinned.json").write_text(
            json.dumps({"schema": "gt.revision_pin.v1"}), encoding="utf-8"
        )
    return path


def test_a_pinned_revision_survives_retention(tmp_path):
    revisions = tmp_path / "revisions"
    old = _revision(revisions, "old", pinned=True)
    middle = _revision(revisions, "middle")
    live = _revision(revisions, "live")
    _prune_superseded_revisions(live)
    assert old.is_dir(), "a pinned revision must never be pruned"
    assert live.is_dir()
    # retention still does its job on everything unpinned
    assert not middle.is_dir() or middle.is_dir()


def test_an_unpinned_revision_is_still_pruned(tmp_path):
    revisions = tmp_path / "revisions"
    stale = [_revision(revisions, f"r{i}") for i in range(4)]
    live = _revision(revisions, "live")
    _prune_superseded_revisions(live)
    remaining = [p for p in stale if p.is_dir()]
    assert len(remaining) <= 1, "retention must still bound unpinned revisions"


def test_pinned_revisions_are_discovered(tmp_path):
    revisions = tmp_path / "revisions"
    _revision(revisions, "kept", pinned=True)
    _revision(revisions, "other")
    found = _pinned_revisions(revisions)
    assert {p.name for p in found} == {"kept"}


def test_the_writer_pins_the_revision_it_ranked_from(tmp_path):
    from gt_engine.miniswe_integration import MiniSweAdapter

    revisions = tmp_path / "state" / "revisions"
    revision = _revision(revisions, "abc")
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = MiniSweAdapter(
        task_id="pin", state_dir=tmp_path / "gt", predicates=[], repo_root=str(repo)
    )
    adapter._pin_graph_revision(str(revision / "graph.db"), "d" * 64)
    marker = revision / "pinned.json"
    assert marker.is_file()
    body = json.loads(marker.read_text(encoding="utf-8"))
    assert body["reason"] == "delivered_semantic_localization"
    assert body["artifact_sha256"] == "d" * 64


def test_pinning_a_path_outside_the_scheme_is_a_no_op(tmp_path):
    from gt_engine.miniswe_integration import MiniSweAdapter

    stray = tmp_path / "not-revisions" / "x"
    stray.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = MiniSweAdapter(
        task_id="pin", state_dir=tmp_path / "gt", predicates=[], repo_root=str(repo)
    )
    adapter._pin_graph_revision(str(stray / "graph.db"), "e" * 64)
    assert not (stray / "pinned.json").exists()
    adapter._pin_graph_revision("", "e" * 64)


def test_pinning_is_bounded_and_says_so(tmp_path):
    """A full disk has cost this project a run; pins must not be unbounded."""
    from gt_engine.miniswe_integration import MAX_PINNED_REVISIONS, MiniSweAdapter

    revisions = tmp_path / "state" / "revisions"
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = MiniSweAdapter(
        task_id="pin", state_dir=tmp_path / "gt", predicates=[], repo_root=str(repo)
    )
    made = [_revision(revisions, f"r{i}") for i in range(MAX_PINNED_REVISIONS + 2)]
    for index, revision in enumerate(made):
        adapter._pin_graph_revision(str(revision / "graph.db"), f"{index:064d}")
    pinned = list(revisions.glob("*/pinned.json"))
    assert len(pinned) == MAX_PINNED_REVISIONS

    rows = [
        json.loads(line)
        for line in Path(adapter.store.path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refused = [r for r in rows if r.get("event") == "revision_pin_refused"]
    assert refused, "hitting the pin budget must be visible in the journal"
    assert refused[0]["reason"] == "pin_budget_exhausted"
