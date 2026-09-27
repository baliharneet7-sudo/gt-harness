"""The SWE-bench-Live Lite catalog builder, offline.

Registry behaviour is replayed through an injected fetch (no network, no
pulls); rendering and materialization run against small fixture rows; the
committed catalog is re-verified against the checked-in dataset snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_swelive_catalog as catalog_module
from scripts.build_swelive_catalog import (
    CATALOG_PATH,
    MANIFEST_PATH,
    MATRIX_JOB_LIMIT,
    Resolution,
    RegistryResolver,
    build_catalog,
    build_manifest,
    catalog_sha256,
    image_name,
    load_catalog,
    load_rows,
    materialize,
    render_task,
    shard_tasks,
    snapshot_sha256,
    template_files,
    verify_catalog,
    verify_manifest,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
V2 = "application/vnd.docker.distribution.manifest.v2+json"
TEMPLATES = {"test.sh": b"#!/bin/bash\necho verify\n", "grade.py": b"print('grade')\n"}


def _row(instance_id: str, repo: str, pull: int) -> dict:
    return {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": "0" * 40,
        "pull_number": pull,
        "problem_statement": f"  Fix {instance_id}.  \n",
        "test_patch": "diff --git a/t.py b/t.py\n",
        "test_cmds": ["pytest -rA tests/t.py"],
        "FAIL_TO_PASS": ["tests/t.py::test_a"],
        "PASS_TO_PASS": [],
        "log_parser": "pytest",
    }


ROWS = [
    _row("owner__repo-1", "owner/repo", 1),
    _row("Delgan__loguru-2", "Delgan/loguru", 2),
    _row("owner__missing-3", "owner/missing", 3),
]


class FakeRegistry:
    """Recorded registry behaviour: a script of responses per URL kind."""

    def __init__(self, manifests: dict[str, list[tuple[int, dict]]], token_statuses=()):
        self.manifests = {repo: list(responses) for repo, responses in manifests.items()}
        self.token_statuses = list(token_statuses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers):
        self.calls.append((method, url))
        if url.startswith(catalog_module.AUTH_URL):
            status = self.token_statuses.pop(0) if self.token_statuses else 200
            body = json.dumps({"token": f"t{len(self.calls)}", "expires_in": 300}).encode()
            return status, {"retry-after": "7"} if status == 429 else {}, body if status == 200 else b""
        assert method == "HEAD", "the resolver must never GET (pull) a manifest"
        assert headers["Authorization"].startswith("Bearer t")
        repo = url.split("/v2/", 1)[1].rsplit("/manifests/", 1)[0]
        status, extra = self.manifests[repo].pop(0)
        return status, extra, b""


def _ok(digest: str = DIGEST_A) -> tuple[int, dict]:
    return 200, {"docker-content-digest": digest, "content-type": V2}


def _repo(instance_id: str) -> str:
    return image_name(instance_id)


def test_image_name_is_the_official_evaluator_rule() -> None:
    assert image_name("aiogram__aiogram-1594") == "starryzhang/sweb.eval.x86_64.aiogram_1776_aiogram-1594"
    # Docker Hub names are lower-case; the evaluator lower-cases the id.
    assert image_name("Delgan__loguru-2") == "starryzhang/sweb.eval.x86_64.delgan_1776_loguru-2"
    catalog = load_catalog()
    assert all(row["container_image"] == image_name(row["task_id"]) for row in catalog["tasks"])


def test_one_token_serves_a_batch_and_is_cached() -> None:
    repos = [_repo(row["instance_id"]) for row in ROWS[:2]]
    fetch = FakeRegistry({repo: [_ok(), _ok()] for repo in repos})
    resolver = RegistryResolver(fetch=fetch, sleep=lambda _: None, clock=lambda: 0.0)
    resolver.prefetch(repos)
    for repo in repos:
        assert resolver.resolve(repo).digest == DIGEST_A
    assert resolver.resolve(repos[0]).reason == "resolved"
    assert resolver.token_requests == 1
    token_urls = [url for _, url in fetch.calls if url.startswith(catalog_module.AUTH_URL)]
    assert len(token_urls) == 1 and token_urls[0].count("scope=repository") == 2


def test_expired_token_is_renewed() -> None:
    repo = _repo("owner__repo-1")
    now = [0.0]
    fetch = FakeRegistry({repo: [_ok(), _ok()]})
    resolver = RegistryResolver(fetch=fetch, sleep=lambda _: None, clock=lambda: now[0])
    resolver.resolve(repo)
    now[0] = 290.0  # inside the 30 s slack before the 300 s expiry
    resolver.resolve(repo)
    assert resolver.token_requests == 2


def test_throttling_backs_off_honouring_retry_after() -> None:
    repo = _repo("owner__repo-1")
    slept: list[float] = []
    fetch = FakeRegistry({repo: [(429, {"retry-after": "11"}), (503, {}), _ok()]}, token_statuses=[429, 200])
    resolver = RegistryResolver(fetch=fetch, sleep=slept.append, clock=lambda: 0.0)
    resolution = resolver.resolve(repo)
    assert resolution.digest == DIGEST_A
    assert slept == [7.0, 11.0, 2.0]
    assert resolver.throttled == 3


def test_throttling_past_the_budget_is_recorded_not_raised() -> None:
    repo = _repo("owner__repo-1")
    fetch = FakeRegistry({repo: [(429, {})] * 3})
    resolver = RegistryResolver(fetch=fetch, sleep=lambda _: None, clock=lambda: 0.0, max_attempts=3)
    assert resolver.resolve(repo).reason == "registry_throttled"


def test_missing_images_are_typed() -> None:
    missing_tag = _repo("owner__repo-1")
    missing_repo = _repo("owner__missing-3")
    bad_header = _repo("Delgan__loguru-2")
    fetch = FakeRegistry({
        missing_tag: [(404, {})],
        missing_repo: [(401, {}), (401, {})],
        bad_header: [(200, {"docker-content-digest": "sha256:short", "content-type": V2})],
    })
    resolver = RegistryResolver(fetch=fetch, sleep=lambda _: None, clock=lambda: 0.0)
    assert resolver.resolve(missing_tag).reason == "image_tag_not_found"
    assert resolver.resolve(missing_repo).reason == "image_repository_unavailable"
    assert resolver.resolve(bad_header).reason == "digest_header_invalid"


def _fixture_catalog() -> dict:
    resolutions = {
        "owner__repo-1": Resolution(image_name("owner__repo-1"), DIGEST_A, V2, "resolved"),
        "Delgan__loguru-2": Resolution(image_name("Delgan__loguru-2"), DIGEST_B, V2, "resolved"),
        "owner__missing-3": Resolution(image_name("owner__missing-3"), None, None, "image_repository_unavailable", "HTTP 401"),
    }
    return build_catalog(
        ROWS, resolutions, templates=TEMPLATES, snapshot_digest="f" * 64,
        hf_revision="rev", hf_parity=None, resolved_at="2026-09-27T00:00:00Z",
    )


def test_unresolved_instances_are_excluded_with_a_reason_never_dropped() -> None:
    catalog = _fixture_catalog()
    assert [row["task_id"] for row in catalog["tasks"]] == ["owner__repo-1", "Delgan__loguru-2"]
    assert [row["ordinal"] for row in catalog["tasks"]] == [1, 2]
    assert catalog["excluded"] == [{
        "task_id": "owner__missing-3",
        "container_image": image_name("owner__missing-3"),
        "reason": "image_repository_unavailable",
        "detail": "HTTP 401",
    }]
    assert catalog["task_count"] == 2 and catalog["excluded_count"] == 1
    assert verify_catalog(catalog, ROWS, templates=TEMPLATES, snapshot_digest="f" * 64) == []


def test_verification_catches_a_tampered_digest_or_dropped_row() -> None:
    catalog = _fixture_catalog()
    tampered = json.loads(json.dumps(catalog))
    tampered["tasks"][0]["container_digest"] = DIGEST_B
    errors = verify_catalog(tampered, ROWS, templates=TEMPLATES, snapshot_digest="f" * 64)
    assert "catalog_task_config_digest_mismatch:owner__repo-1" in errors
    dropped = json.loads(json.dumps(catalog))
    dropped["excluded"] = []
    dropped["excluded_count"] = 0
    errors = verify_catalog(dropped, ROWS, templates=TEMPLATES, snapshot_digest="f" * 64)
    assert "catalog_does_not_partition_the_snapshot" in errors
    assert "catalog_snapshot_digest_mismatch" in verify_catalog(
        catalog, ROWS, templates=TEMPLATES, snapshot_digest="0" * 64
    )


def test_manifest_derives_from_the_catalog_and_binds_its_digest() -> None:
    catalog = _fixture_catalog()
    manifest = build_manifest(catalog, "c" * 64)
    assert manifest["catalog"] == {
        "path": "config/swelive_lite_catalog_v1.json", "sha256": "c" * 64, "excluded_count": 1,
    }
    assert [row["task_id"] for row in manifest["tasks"]] == ["owner__repo-1", "Delgan__loguru-2"]
    assert verify_manifest(manifest, catalog, "c" * 64) == []
    assert verify_manifest(manifest, catalog, "d" * 64) == ["manifest_does_not_derive_from_catalog"]


def test_materialize_writes_verifies_and_refuses_drift(tmp_path: Path) -> None:
    catalog = _fixture_catalog()
    written = materialize(catalog, ROWS, tmp_path, ["Delgan__loguru-2"], templates=TEMPLATES)
    task = written[0]
    assert (task / "task.toml").is_file() and (task / "tests/grade.py").read_bytes() == TEMPLATES["grade.py"]
    assert DIGEST_B in (task / "environment/Dockerfile").read_text(encoding="utf-8")
    # A second pass confirms rather than rewrites.
    materialize(catalog, ROWS, tmp_path, ["Delgan__loguru-2"], templates=TEMPLATES)
    (task / "instruction.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="drifted"):
        materialize(catalog, ROWS, tmp_path, ["Delgan__loguru-2"], templates=TEMPLATES)
    with pytest.raises(ValueError, match="not in the catalog"):
        materialize(catalog, ROWS, tmp_path, ["owner__missing-3"], templates=TEMPLATES)
    pinned_wrong = json.loads(json.dumps(catalog))
    pinned_wrong["tasks"][0]["task_config_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest differs"):
        materialize(pinned_wrong, ROWS, tmp_path / "fresh", ["owner__repo-1"], templates=TEMPLATES)


def test_task_config_digest_is_checkout_independent() -> None:
    files = render_task(ROWS[0], image=image_name("owner__repo-1"), digest=DIGEST_A, templates=TEMPLATES)
    crlf = {**files, "task.toml": files["task.toml"].replace(b"\n", b"\r\n")}
    assert catalog_module.task_config_sha256(crlf) == catalog_module.task_config_sha256(files)


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_shards_partition_the_cohort(count: int) -> None:
    tasks = [f"t{i}" for i in range(300)]
    if count == 1:
        assert shard_tasks(tasks, 1, 1) == tasks
        return
    shards = [shard_tasks(tasks, index, count) for index in range(1, count + 1)]
    assert sorted(sum(shards, [])) == sorted(tasks)
    assert sum(len(shard) for shard in shards) == len(tasks)
    assert max(len(shard) for shard in shards) - min(len(shard) for shard in shards) <= 1


def test_shard_inputs_are_validated() -> None:
    for index, count in ((0, 1), (2, 1), (1, 0), (True, 1)):
        with pytest.raises(ValueError):
            shard_tasks(["a", "b"], index, count)
    with pytest.raises(ValueError, match="empty"):
        shard_tasks(["a"], 2, 2)


def test_the_full_lite_split_needs_two_shards_and_two_suffice() -> None:
    tasks = [row["task_id"] for row in load_catalog()["tasks"]]
    assert len(tasks) > MATRIX_JOB_LIMIT
    assert all(len(shard_tasks(tasks, i, 2)) <= MATRIX_JOB_LIMIT for i in (1, 2))


def test_committed_catalog_is_the_full_lite_split_and_verifies() -> None:
    catalog = load_catalog()
    rows = load_rows()
    assert catalog["dataset"]["name"] == "SWE-bench-Live/SWE-bench-Live"
    assert catalog["dataset"]["split"] == "lite"
    assert catalog["dataset"]["row_count"] == 300 == len(rows)
    assert catalog["task_count"] + catalog["excluded_count"] == 300
    parity = catalog["dataset"]["hf_parity"]
    assert parity["instance_set_equal"] is True and parity["field_differences"] == 0
    assert all(row["reason"] for row in catalog["excluded"])
    assert verify_catalog(catalog, rows, templates=template_files(), snapshot_digest=snapshot_sha256()) == []
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert verify_manifest(manifest, catalog, catalog_sha256(CATALOG_PATH)) == []


def test_confirm_heads_each_planned_manifest_by_digest() -> None:
    repo_a = _repo("owner__repo-1")
    repo_b = _repo("Delgan__loguru-2")
    fetch = FakeRegistry({
        repo_a: [(200, {"docker-content-digest": DIGEST_A})],
        repo_b: [(200, {"docker-content-digest": DIGEST_A})],  # served under another digest
    })
    resolver = RegistryResolver(fetch=fetch, sleep=lambda _: None, clock=lambda: 0.0)
    matrix = {"include": [
        {"container_image": repo_a, "container_digest": DIGEST_A},
        {"container_image": repo_a, "container_digest": DIGEST_A},  # duplicate leg, one HEAD
        {"container_image": repo_b, "container_digest": DIGEST_B},
    ]}
    results = catalog_module.confirm_matrix_images(matrix, resolver)
    assert [result.reason for result in results] == ["resolved", "digest_mismatch"]
    heads = [url for method, url in fetch.calls if method == "HEAD"]
    assert heads == [
        f"https://{catalog_module.REGISTRY_HOST}/v2/{repo_a}/manifests/{DIGEST_A}",
        f"https://{catalog_module.REGISTRY_HOST}/v2/{repo_b}/manifests/{DIGEST_B}",
    ]
    assert resolver.token_requests == 1


def test_confirm_types_a_vanished_manifest() -> None:
    repo = _repo("owner__repo-1")
    fetch = FakeRegistry({repo: [(404, {})]})
    resolver = RegistryResolver(fetch=fetch, sleep=lambda _: None, clock=lambda: 0.0)
    assert resolver.confirm(repo, DIGEST_A).reason == "manifest_unavailable"
    assert resolver.confirm(repo, "sha256:nope").reason == "digest_invalid"
