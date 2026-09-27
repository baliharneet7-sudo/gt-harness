"""Build, verify and materialize the pinned SWE-bench-Live Lite catalog.

The catalog (``config/swelive_lite_catalog_v1.json``) is the single source of
truth for the GT-on SWE-bench-Live Lite cohort: every one of the 300 ``lite``
instances of the Hugging Face dataset ``SWE-bench-Live/SWE-bench-Live``, each
bound to its evaluation image BY REGISTRY DIGEST and to the canonical sha256
of the Pier ``task.toml`` rendered for it. Instances whose image cannot be
resolved are recorded under ``excluded`` with a reason; nothing is dropped
silently.

Three sub-commands:

``resolve``      network. Resolves each instance's ``starryzhang/sweb.eval.x86_64.*``
                 image digest with anonymous registry HEAD requests (HEAD does not
                 count against Docker Hub's pull limit, and nothing is pulled),
                 caching bearer tokens per repository batch and backing off on 429.
                 Writes the catalog and the suite manifest derived from it.
``materialize``  offline. Renders Pier task directories for named tasks from the
                 checked-in dataset snapshot and REFUSES any task whose rendered
                 ``task.toml`` does not hash to the catalog's pin. An existing task
                 directory must match the rendering byte-for-byte (modulo CRLF).
``verify``       offline. Re-renders every catalog task and checks the catalog, the
                 snapshot digest and the manifest binding.

The image name rule is the official evaluator's own
(``swebench.harness.test_spec.TestSpec.instance_image_key``): the instance id
lower-cased, ``__`` replaced by ``_1776_``, under the ``starryzhang`` namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "benchmarks" / "data" / "swebench_live_lite.jsonl"
CATALOG_PATH = ROOT / "config" / "swelive_lite_catalog_v1.json"
MANIFEST_PATH = ROOT / "swelive-bench" / "manifest.json"
TASKS_DIR = ROOT / "swelive-bench" / "tasks"
# Where runs render packages: every task of a run comes from the one renderer,
# and hand-curated committed packages (tasks/cyclotruc__gitingest-94 predates
# the renderer and backs tests/test_swelive_corpus.py) are never compared,
# overwritten or mixed in. Git-ignored (swelive-bench/.gitignore).
RENDERED_TASKS_DIR = ROOT / "swelive-bench" / "rendered"
# The verifier entrypoint and grader are dataset-independent; the first frozen
# smoke package carries the reviewed copies every task reuses.
TEMPLATE_DIR = TASKS_DIR / "aiogram__aiogram-1594" / "tests"

CATALOG_SCHEMA = "gt.swelive_lite_catalog.v1"
MANIFEST_SCHEMA = "swelive-bench.manifest/v1"
TASK_CONFIG_IDENTITY = "sha256_canonical_lf_v1"
DATASET_NAME = "SWE-bench-Live/SWE-bench-Live"
DATASET_SPLIT = "lite"
DATASET_ROW_COUNT = 300
NAMESPACE = "starryzhang"
IMAGE_PREFIX = f"{NAMESPACE}/sweb.eval.x86_64."
IMAGE_TAG = "latest"
IMAGE_RULE = (
    f"{IMAGE_PREFIX}<instance_id lower-cased, '__' -> '_1776_'>:{IMAGE_TAG}"
)
REGISTRY_HOST = "registry-1.docker.io"
AUTH_URL = "https://auth.docker.io/token"
AUTH_SERVICE = "registry.docker.io"
ACCEPTED_MEDIA_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
)
# GitHub refuses a matrix of more than 256 jobs; a cohort above it must shard.
MATRIX_JOB_LIMIT = 256
# The historical smoke cohort: the first five catalog rows, in snapshot order.
SMOKE5_COUNT = 5
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


# --------------------------------------------------------------------------- #
# dataset snapshot
# --------------------------------------------------------------------------- #

def canonical_lf(raw: bytes) -> bytes:
    """Git-blob newline form, so a Windows CRLF checkout hashes like CI."""
    return raw.replace(b"\r\n", b"\n")


def snapshot_sha256(path: Path = DATASET_PATH) -> str:
    return hashlib.sha256(canonical_lf(path.read_bytes())).hexdigest()


def load_rows(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [str(row.get("instance_id") or "") for row in rows]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("dataset snapshot instance ids are empty or not unique")
    return rows


def order_sha256(task_ids: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(task_ids) + "\n").encode("utf-8")).hexdigest()


def image_name(instance_id: str) -> str:
    return IMAGE_PREFIX + instance_id.lower().replace("__", "_1776_")


# --------------------------------------------------------------------------- #
# task rendering (the one renderer; the smoke builder delegates here)
# --------------------------------------------------------------------------- #

def _q(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def template_files(template_dir: Path = TEMPLATE_DIR) -> dict[str, bytes]:
    return {name: (template_dir / name).read_bytes() for name in ("test.sh", "grade.py")}


def render_task(
    row: Mapping[str, Any],
    *,
    image: str,
    digest: str,
    templates: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Every file of one Pier task package, keyed by relative POSIX path."""
    task_id = str(row["instance_id"])
    repo = str(row["repo"])
    base = str(row["base_commit"])
    pull = int(row["pull_number"])
    statement = str(row["problem_statement"]).strip()
    collect = (
        f"cd /testbed && mkdir -p /logs/artifacts && git config --global --add "
        f"safe.directory '*' && {{ [ -d .git ] || {{ g=$(find . -maxdepth 2 "
        f"-mindepth 2 -type d -name .git -print -quit); [ -n \"$g\" ] && cd "
        f"\"${{g%/.git}}\"; }}; }} && {{ git add -N -A 2>/dev/null || true; git "
        f"diff --binary {base} > /logs/artifacts/model.patch; }}"
    )
    task_toml = f'''schema_version = "1.3"
artifacts = ["/logs/artifacts/model.patch"]
[task]
name = "swelive/{task_id}"
description = {_q(f"SWE-bench-Live Lite task {task_id} ({repo} PR {pull})")}
authors = []
keywords = ["swe-bench-live", "lite", "python"]
[metadata]
task_id = {_q(task_id)}
language = "python"
repository_url = {_q("https://github.com/" + repo)}
base_commit_hash = {_q(base)}
pull_number = {pull}
dataset = "SWE-bench-Live/SWE-bench-Live"
dataset_split = "lite"
log_parser = {_q(row.get("log_parser", "pytest"))}
[verifier]
network_mode = "public"
environment_mode = "separate"
timeout_sec = 900.0
[verifier.env]
[verifier.environment]
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 8192
storage_mb = 20480
workdir = "/testbed"
[[verifier.collect]]
command = {_q(collect)}
timeout_sec = 300.0
[agent]
network_mode = "no-network"
timeout_sec = 1800.0
[environment]
build_timeout_sec = 1800.0
docker_image = {_q(image + "@" + digest)}
os = "linux"
cpus = 2
memory_mb = 8192
storage_mb = 20480
gpus = 0
mcp_servers = []
workdir = "/testbed"
[environment.env]
[solution.env]
'''
    docker = f"FROM {image}@{digest}\nWORKDIR /testbed\n"
    commands = row.get("test_cmds") or ["pytest -rA"]
    spec = {
        "instance_id": task_id, "repo": repo, "pull_number": str(pull),
        "base_commit": base, "test_cmds": commands,
        "log_parser": row.get("log_parser", "pytest"),
        "fail_to_pass": row.get("FAIL_TO_PASS", []),
        "pass_to_pass": row.get("PASS_TO_PASS", []),
        "container_image": image, "container_digest": digest,
    }
    lock = {
        "schema": "swelive-bench.image-lock/v1",
        "instance_id": task_id,
        "container_image": image,
        "container_digest": digest,
        "docker_image_ref_used_in_task_toml": image + "@" + digest,
    }
    text = {
        "task.toml": task_toml,
        "instruction.md": statement + "\n",
        "environment/Dockerfile": docker,
        "tests/Dockerfile": docker
        + "COPY test.sh run_tests.sh grade.py spec.json test_patch.diff /tests/\n"
        + "RUN chmod +x /tests/test.sh /tests/run_tests.sh\n",
        "tests/run_tests.sh": "#!/bin/bash\n" + "\n".join(commands) + "\n",
        "tests/test_patch.diff": str(row["test_patch"]),
        "tests/spec.json": json.dumps(spec, indent=2) + "\n",
        "image.lock.json": json.dumps(lock, indent=2) + "\n",
    }
    files = {path: value.encode("utf-8") for path, value in text.items()}
    for name in ("test.sh", "grade.py"):
        files[f"tests/{name}"] = bytes(templates[name])
    return files


def task_config_sha256(files: Mapping[str, bytes]) -> str:
    return hashlib.sha256(canonical_lf(files["task.toml"])).hexdigest()


# --------------------------------------------------------------------------- #
# registry resolution
# --------------------------------------------------------------------------- #

# fetch(method, url, headers) -> (status, headers, body). Injected in tests so
# the resolver is exercised offline against recorded registry behaviour.
Fetch = Callable[[str, str, Mapping[str, str]], tuple[int, Mapping[str, str], bytes]]


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # noqa: PLC0415 - optional, only for stale host stores
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def urllib_fetch(method: str, url: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response:
            body = response.read() if method != "HEAD" else b""
            return response.status, {k.lower(): v for k, v in response.headers.items()}, body
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, b""


@dataclass(frozen=True)
class Resolution:
    image: str
    digest: str | None
    media_type: str | None
    reason: str
    detail: str = ""


class RegistryResolver:
    """Anonymous digest resolution with token caching and 429 backoff."""

    TOKEN_SLACK_SECONDS = 30.0

    def __init__(
        self,
        *,
        fetch: Fetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_attempts: int = 8,
        backoff_cap_seconds: float = 120.0,
    ) -> None:
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._max_attempts = max_attempts
        self._backoff_cap = backoff_cap_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self.token_requests = 0
        self.manifest_requests = 0
        self.throttled = 0

    @staticmethod
    def repository(image: str) -> str:
        return image.split("@", 1)[0].rsplit(":", 1)[0] if ":" in image.split("/")[-1] else image

    def _cached(self, repository: str) -> str | None:
        entry = self._tokens.get(repository)
        if entry and entry[1] - self._clock() > self.TOKEN_SLACK_SECONDS:
            return entry[0]
        return None

    def _backoff(self, attempt: int, headers: Mapping[str, str]) -> None:
        self.throttled += 1
        retry_after = str(headers.get("retry-after") or "").strip()
        delay = min(self._backoff_cap, float(2 ** attempt))
        if retry_after.isdigit():
            delay = min(self._backoff_cap, max(delay, float(retry_after)))
        self._sleep(delay)

    def prefetch(self, repositories: Iterable[str]) -> None:
        """One bearer token for a batch of repositories (one scope each)."""
        pending = [repo for repo in dict.fromkeys(repositories) if self._cached(repo) is None]
        if not pending:
            return
        query = urllib.parse.urlencode(
            [("service", AUTH_SERVICE)]
            + [("scope", f"repository:{repo}:pull") for repo in pending]
        )
        for attempt in range(self._max_attempts):
            self.token_requests += 1
            status, headers, body = self._fetch("GET", f"{AUTH_URL}?{query}", {})
            if status == 200:
                payload = json.loads(body.decode("utf-8"))
                token = str(payload.get("token") or payload.get("access_token") or "")
                if not token:
                    raise RuntimeError("registry token response carried no token")
                expires = self._clock() + float(payload.get("expires_in") or 300)
                for repo in pending:
                    self._tokens[repo] = (token, expires)
                return
            if status == 429 or status >= 500:
                self._backoff(attempt, headers)
                continue
            raise RuntimeError(f"registry token request failed with HTTP {status}")
        raise RuntimeError("registry token request throttled past the retry budget")

    def resolve(self, image: str) -> Resolution:
        repository = self.repository(image)
        url = f"https://{REGISTRY_HOST}/v2/{repository}/manifests/{IMAGE_TAG}"
        refreshed = False
        for attempt in range(self._max_attempts):
            token = self._cached(repository)
            if token is None:
                self.prefetch([repository])
                token = self._cached(repository) or ""
            self.manifest_requests += 1
            status, headers, _ = self._fetch(
                "HEAD",
                url,
                {"Authorization": f"Bearer {token}", "Accept": ", ".join(ACCEPTED_MEDIA_TYPES)},
            )
            if status == 200:
                digest = str(headers.get("docker-content-digest") or "")
                media = str(headers.get("content-type") or "").split(";", 1)[0].strip()
                if not _DIGEST.fullmatch(digest):
                    return Resolution(image, None, media or None, "digest_header_invalid", digest)
                if media not in ACCEPTED_MEDIA_TYPES:
                    return Resolution(image, None, media or None, "manifest_media_type_unsupported", media)
                return Resolution(image, digest, media, "resolved")
            if status == 404:
                return Resolution(image, None, None, "image_tag_not_found", f"{IMAGE_TAG} HTTP 404")
            if status == 401:
                if not refreshed:
                    # An expired or scope-short token: renew once, then judge.
                    self._tokens.pop(repository, None)
                    refreshed = True
                    continue
                # Docker Hub answers 401 (not 404) for a repository that does
                # not exist or is private to anonymous pulls.
                return Resolution(image, None, None, "image_repository_unavailable", "HTTP 401 after token refresh")
            if status == 429 or status >= 500:
                self._backoff(attempt, headers)
                continue
            return Resolution(image, None, None, "registry_http_error", f"HTTP {status}")
        return Resolution(image, None, None, "registry_throttled", "retry budget exhausted")

    def confirm(self, image: str, digest: str) -> Resolution:
        """HEAD the manifest BY DIGEST: present, and served under that digest.

        A registry addresses manifests by content, so a 200 whose
        Docker-Content-Digest equals the requested digest proves the exact
        manifest is still pullable - without a GET, which Docker Hub counts
        against the anonymous pull limit.
        """
        if not _DIGEST.fullmatch(digest):
            return Resolution(image, None, None, "digest_invalid", digest)
        repository = self.repository(image)
        url = f"https://{REGISTRY_HOST}/v2/{repository}/manifests/{digest}"
        refreshed = False
        for attempt in range(self._max_attempts):
            token = self._cached(repository)
            if token is None:
                self.prefetch([repository])
                token = self._cached(repository) or ""
            self.manifest_requests += 1
            status, headers, _ = self._fetch(
                "HEAD",
                url,
                {"Authorization": f"Bearer {token}", "Accept": ", ".join(ACCEPTED_MEDIA_TYPES)},
            )
            if status == 200:
                served = str(headers.get("docker-content-digest") or "")
                if served != digest:
                    return Resolution(image, None, None, "digest_mismatch", served)
                return Resolution(image, digest, None, "resolved")
            if status == 401 and not refreshed:
                self._tokens.pop(repository, None)
                refreshed = True
                continue
            if status == 429 or status >= 500:
                self._backoff(attempt, headers)
                continue
            return Resolution(image, None, None, "manifest_unavailable", f"HTTP {status}")
        return Resolution(image, None, None, "registry_throttled", "retry budget exhausted")


def confirm_matrix_images(
    matrix: Mapping[str, Any], resolver: RegistryResolver, batch: int = 25
) -> list[Resolution]:
    """Confirm every distinct (image, digest) a planned matrix will pull."""
    pairs = list(dict.fromkeys(
        (str(row["container_image"]), str(row["container_digest"]))
        for row in matrix.get("include", [])
    ))
    results: list[Resolution] = []
    for start in range(0, len(pairs), batch):
        chunk = pairs[start : start + batch]
        resolver.prefetch(image for image, _ in chunk)
        results.extend(resolver.confirm(image, digest) for image, digest in chunk)
    return results


# --------------------------------------------------------------------------- #
# catalog and manifest
# --------------------------------------------------------------------------- #

def build_catalog(
    rows: Sequence[Mapping[str, Any]],
    resolutions: Mapping[str, Resolution],
    *,
    templates: Mapping[str, bytes],
    snapshot_digest: str,
    hf_revision: str,
    hf_parity: Mapping[str, Any] | None,
    resolved_at: str,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        task_id = str(row["instance_id"])
        image = image_name(task_id)
        resolution = resolutions.get(task_id)
        if resolution is None or resolution.digest is None:
            excluded.append({
                "task_id": task_id,
                "container_image": image,
                "reason": resolution.reason if resolution else "not_resolved",
                "detail": resolution.detail if resolution else "",
            })
            continue
        files = render_task(row, image=image, digest=resolution.digest, templates=templates)
        tasks.append({
            "ordinal": len(tasks) + 1,
            "task_id": task_id,
            "repo": str(row["repo"]),
            "pull_number": int(row["pull_number"]),
            "language": "python",
            "base_commit": str(row["base_commit"]),
            "container_image": image,
            "container_digest": resolution.digest,
            "manifest_media_type": resolution.media_type,
            "task_config_sha256": task_config_sha256(files),
        })
    task_ids = [row["task_id"] for row in tasks]
    return {
        "schema": CATALOG_SCHEMA,
        "dataset": {
            "name": DATASET_NAME,
            "split": DATASET_SPLIT,
            "hf_revision": hf_revision,
            "row_count": len(rows),
            "snapshot_path": DATASET_PATH.relative_to(ROOT).as_posix(),
            "snapshot_sha256": snapshot_digest,
            "snapshot_identity": "sha256 of the git-blob (LF) bytes",
            "order": "snapshot row order",
            "hf_parity": dict(hf_parity) if hf_parity else None,
        },
        "image_rule": IMAGE_RULE,
        "registry": REGISTRY_HOST,
        "resolution": "anonymous registry HEAD of the tag manifest; nothing pulled",
        "resolved_at": resolved_at,
        "task_config_identity": TASK_CONFIG_IDENTITY,
        "task_count": len(tasks),
        "excluded_count": len(excluded),
        "task_order_sha256": order_sha256(task_ids),
        "tasks": tasks,
        "excluded": excluded,
    }


def catalog_bytes(catalog: Mapping[str, Any]) -> bytes:
    return (json.dumps(catalog, indent=2) + "\n").encode("utf-8")


def catalog_sha256(path: Path = CATALOG_PATH) -> str:
    return hashlib.sha256(canonical_lf(path.read_bytes())).hexdigest()


def build_manifest(catalog: Mapping[str, Any], catalog_digest: str) -> dict[str, Any]:
    """The suite manifest scripts/benchmark_suites.py binds: the runnable rows."""
    return {
        "schema": MANIFEST_SCHEMA,
        "adapter": "swe-bench-live-lite",
        "pier_version_target": "0.3.1",
        "task_toml_schema_version": "1.3",
        "task_config_identity": TASK_CONFIG_IDENTITY,
        "dataset": {
            "name": DATASET_NAME,
            "split": DATASET_SPLIT,
            "source_snapshot": (
                "benchmarks/data/swebench_live_lite.jsonl, every row with a "
                "resolved image, in source order"
            ),
            "image_name_rule": IMAGE_RULE,
        },
        "catalog": {
            "path": CATALOG_PATH.relative_to(ROOT).as_posix(),
            "sha256": catalog_digest,
            "excluded_count": int(catalog["excluded_count"]),
        },
        "tasks": [
            {
                "ordinal": row["ordinal"],
                "task_id": row["task_id"],
                "language": row["language"],
                "base_commit": row["base_commit"],
                "task_config_sha256": row["task_config_sha256"],
                "container_image": row["container_image"],
                "container_digest": row["container_digest"],
            }
            for row in catalog["tasks"]
        ],
    }


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise ValueError("invalid SWE-bench-Live catalog schema")
    return catalog


def verify_catalog(
    catalog: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    templates: Mapping[str, bytes],
    snapshot_digest: str,
) -> list[str]:
    """Every reason the catalog does not describe the checked-in snapshot."""
    errors: list[str] = []
    if catalog.get("schema") != CATALOG_SCHEMA:
        errors.append("catalog_schema_mismatch")
    dataset = catalog.get("dataset") or {}
    if dataset.get("snapshot_sha256") != snapshot_digest:
        errors.append("catalog_snapshot_digest_mismatch")
    if dataset.get("name") != DATASET_NAME or dataset.get("split") != DATASET_SPLIT:
        errors.append("catalog_dataset_identity_mismatch")
    if catalog.get("task_config_identity") != TASK_CONFIG_IDENTITY:
        errors.append("catalog_task_config_identity_mismatch")
    by_id = {str(row["instance_id"]): row for row in rows}
    tasks = list(catalog.get("tasks") or [])
    excluded = list(catalog.get("excluded") or [])
    task_ids = [str(row.get("task_id")) for row in tasks]
    covered = task_ids + [str(row.get("task_id")) for row in excluded]
    snapshot_ids = [str(row["instance_id"]) for row in rows]
    if sorted(covered) != sorted(snapshot_ids) or len(covered) != len(set(covered)):
        errors.append("catalog_does_not_partition_the_snapshot")
    if [tid for tid in snapshot_ids if tid in set(task_ids)] != task_ids:
        errors.append("catalog_task_order_is_not_snapshot_order")
    if catalog.get("task_count") != len(tasks) or catalog.get("excluded_count") != len(excluded):
        errors.append("catalog_counts_mismatch")
    if catalog.get("task_order_sha256") != order_sha256(task_ids):
        errors.append("catalog_task_order_digest_mismatch")
    for ordinal, entry in enumerate(tasks, start=1):
        task_id = str(entry.get("task_id"))
        row = by_id.get(task_id)
        if row is None:
            continue
        image = image_name(task_id)
        digest = str(entry.get("container_digest") or "")
        if (
            entry.get("ordinal") != ordinal
            or entry.get("container_image") != image
            or not _DIGEST.fullmatch(digest)
            or entry.get("base_commit") != row.get("base_commit")
        ):
            errors.append(f"catalog_task_identity_mismatch:{task_id}")
            continue
        files = render_task(row, image=image, digest=digest, templates=templates)
        if task_config_sha256(files) != entry.get("task_config_sha256"):
            errors.append(f"catalog_task_config_digest_mismatch:{task_id}")
    for entry in excluded:
        if not str(entry.get("reason") or ""):
            errors.append(f"catalog_exclusion_without_reason:{entry.get('task_id')}")
    return errors


def verify_manifest(manifest: Mapping[str, Any], catalog: Mapping[str, Any], catalog_digest: str) -> list[str]:
    expected = build_manifest(catalog, catalog_digest)
    return [] if manifest == expected else ["manifest_does_not_derive_from_catalog"]


# --------------------------------------------------------------------------- #
# cohort selection
# --------------------------------------------------------------------------- #

def smoke5_task_ids(catalog: Mapping[str, Any]) -> list[str]:
    return [str(row["task_id"]) for row in list(catalog["tasks"])[:SMOKE5_COUNT]]


def shard_tasks(tasks: Sequence[str], index: int, count: int) -> list[str]:
    """Shard ``index`` (1-based) of ``count``: every count-th task, strided.

    Striding rather than slicing spreads each repository's tasks across the
    shards (the snapshot is grouped by repository), and is deterministic, so
    the attestation re-derives the exact shard from the plan's two integers.
    """
    if type(index) is not int or type(count) is not int or count < 1 or not 1 <= index <= count:
        raise ValueError(f"shard {index}/{count} is out of range")
    shard = list(tasks)[index - 1 :: count]
    if not shard:
        raise ValueError(f"shard {index}/{count} of {len(tasks)} task(s) is empty")
    return shard


# --------------------------------------------------------------------------- #
# materialization
# --------------------------------------------------------------------------- #

def materialize(
    catalog: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    output: Path,
    task_ids: Iterable[str],
    *,
    templates: Mapping[str, bytes],
) -> list[Path]:
    """Write (or confirm) each named task package; refuse any digest drift."""
    entries = {str(row["task_id"]): row for row in catalog["tasks"]}
    by_id = {str(row["instance_id"]): row for row in rows}
    written: list[Path] = []
    for task_id in task_ids:
        entry = entries.get(task_id)
        if entry is None:
            raise ValueError(f"task is not in the catalog: {task_id}")
        row = by_id.get(task_id)
        if row is None:
            raise ValueError(f"task is not in the dataset snapshot: {task_id}")
        files = render_task(
            row, image=entry["container_image"], digest=entry["container_digest"],
            templates=templates,
        )
        if task_config_sha256(files) != entry["task_config_sha256"]:
            raise ValueError(f"rendered task.toml digest differs from the catalog: {task_id}")
        task_dir = output / task_id
        if task_dir.exists():
            for relative, content in files.items():
                target = task_dir / relative
                if not target.is_file() or canonical_lf(target.read_bytes()) != canonical_lf(content):
                    raise ValueError(f"existing task package drifted from the catalog: {task_id}/{relative}")
        else:
            for relative, content in files.items():
                target = task_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        written.append(task_dir)
    return written


# --------------------------------------------------------------------------- #
# hugging face parity (optional, from a downloaded split parquet)
# --------------------------------------------------------------------------- #

_PARITY_FIELDS = (
    "base_commit", "test_patch", "problem_statement", "repo", "pull_number",
    "FAIL_TO_PASS", "PASS_TO_PASS", "test_cmds", "log_parser",
)


def hf_parity(rows: Sequence[Mapping[str, Any]], parquet: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq  # noqa: PLC0415 - only for the optional check

    remote = {str(row["instance_id"]): row for row in pq.read_table(parquet).to_pylist()}
    local = {str(row["instance_id"]): row for row in rows}
    diffs = 0
    for task_id, row in local.items():
        other = remote.get(task_id) or {}
        for key in _PARITY_FIELDS:
            value = other.get(key)
            if isinstance(value, str) and key in ("FAIL_TO_PASS", "PASS_TO_PASS", "test_cmds"):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            if row.get(key) != value:
                diffs += 1
    return {
        "checked": True,
        "remote_row_count": len(remote),
        "instance_set_equal": set(remote) == set(local),
        "field_differences": diffs,
        "fields": list(_PARITY_FIELDS),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _resolve_all(
    rows: Sequence[Mapping[str, Any]],
    resolver: RegistryResolver,
    cache_path: Path | None,
    batch: int,
) -> dict[str, Resolution]:
    cache: dict[str, dict[str, Any]] = {}
    if cache_path and cache_path.is_file():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    results: dict[str, Resolution] = {
        task_id: Resolution(**value) for task_id, value in cache.items()
        if value.get("reason") == "resolved"
    }
    pending = [str(row["instance_id"]) for row in rows if str(row["instance_id"]) not in results]
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        resolver.prefetch(image_name(task_id) for task_id in chunk)
        for task_id in chunk:
            results[task_id] = resolver.resolve(image_name(task_id))
        if cache_path:
            cache_path.write_text(
                json.dumps({k: vars(v) for k, v in results.items()}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        print(
            f"resolved {len(results)}/{len(rows)} (token requests "
            f"{resolver.token_requests}, throttled {resolver.throttled})",
            file=sys.stderr,
        )
    return results


def _write_catalog_and_manifest(catalog: Mapping[str, Any], catalog_path: Path, manifest_path: Path) -> str:
    data = catalog_bytes(catalog)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    manifest = build_manifest(catalog, digest)
    manifest_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    resolve.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    resolve.add_argument("--hf-revision", required=True)
    resolve.add_argument("--hf-parquet", type=Path)
    resolve.add_argument("--cache", type=Path)
    resolve.add_argument("--batch", type=int, default=25)
    mat = sub.add_parser("materialize")
    mat.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    mat.add_argument("--output", type=Path, default=RENDERED_TASKS_DIR)
    mat.add_argument("--tasks", required=True, help="'all' or a comma-separated list")
    ver = sub.add_parser("verify")
    ver.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    ver.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    images = sub.add_parser("confirm-images")
    images.add_argument("--plan", type=Path, required=True, help="the planned swelive-plan.json")
    args = parser.parse_args(argv)

    if args.command == "confirm-images":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        results = confirm_matrix_images({"include": plan["matrix"]}, RegistryResolver())
        failed = [result for result in results if result.digest is None]
        for result in results:
            print(f"{result.reason:<22} {result.image}@{result.digest or '-'} {result.detail}")
        print(f"confirmed {len(results) - len(failed)}/{len(results)} task image manifest(s)")
        return 1 if failed or not results else 0

    rows = load_rows()
    templates = template_files()
    if args.command == "resolve":
        if len(rows) != DATASET_ROW_COUNT:
            raise SystemExit(f"snapshot has {len(rows)} rows, expected {DATASET_ROW_COUNT}")
        parity = hf_parity(rows, args.hf_parquet) if args.hf_parquet else None
        if parity and (not parity["instance_set_equal"] or parity["field_differences"]):
            raise SystemExit(f"snapshot differs from the Hugging Face split: {parity}")
        resolutions = _resolve_all(rows, RegistryResolver(), args.cache, args.batch)
        catalog = build_catalog(
            rows, resolutions, templates=templates, snapshot_digest=snapshot_sha256(),
            hf_revision=args.hf_revision, hf_parity=parity,
            resolved_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        digest = _write_catalog_and_manifest(catalog, args.catalog, args.manifest)
        print(json.dumps({
            "catalog_sha256": digest, "task_count": catalog["task_count"],
            "excluded": catalog["excluded"],
        }, indent=2))
        return 0
    catalog = load_catalog(args.catalog)
    if args.command == "materialize":
        wanted = (
            [row["task_id"] for row in catalog["tasks"]]
            if args.tasks.strip() == "all"
            else [item.strip() for item in args.tasks.split(",") if item.strip()]
        )
        written = materialize(catalog, rows, args.output, wanted, templates=templates)
        print(f"materialized {len(written)} task package(s) under {args.output}")
        return 0
    digest = catalog_sha256(args.catalog)
    errors = verify_catalog(catalog, rows, templates=templates, snapshot_digest=snapshot_sha256())
    errors += verify_manifest(json.loads(args.manifest.read_text(encoding="utf-8")), catalog, digest)
    print(json.dumps({"catalog_sha256": digest, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
