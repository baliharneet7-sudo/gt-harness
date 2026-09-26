"""Build the pinned DeepSWE task catalog (all tasks, not just the smoke 20).

Each row carries what a benchmark job needs to run a task reproducibly: the
task-config digest, the language, the base commit, and the container image
pinned BY DIGEST (resolved anonymously from public ECR, never trusted by tag).
Every task that also appears in the certified product bundle must reproduce
its bundle row exactly, or the catalog is refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from scripts.resolve_harbor_budget import TASK_CONFIG_IDENTITY, canonical_task_config_bytes

SCHEMA = "gt.deepswe_task_catalog.v1"
_MANIFEST_ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
))
_COMPARED_FIELDS = ("task_config_sha256", "language", "base_commit",
                    "container_image", "container_digest")


_TOKENS: dict[str, str] = {}
_MAX_ATTEMPTS = 6


def _open_with_backoff(request: urllib.request.Request | str) -> Any:
    delay = 2.0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(request, timeout=60)  # noqa: S310 - fixed registry host
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == _MAX_ATTEMPTS:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            time.sleep(float(retry_after) if retry_after.isdigit() else delay)
            delay = min(delay * 2, 60.0)
    raise RuntimeError("unreachable")


def resolve_public_ecr_digest(image: str) -> str:
    """``public.ecr.aws/<alias>/<repo>:<tag>`` -> ``sha256:...`` (anonymous)."""
    host, _, rest = image.partition("/")
    if host != "public.ecr.aws" or ":" not in rest:
        raise ValueError(f"unsupported_image_reference:{image}")
    repository, _, tag = rest.rpartition(":")
    if repository not in _TOKENS:
        token_url = f"https://public.ecr.aws/token/?scope=repository:{repository}:pull"
        with _open_with_backoff(token_url) as response:
            _TOKENS[repository] = json.loads(response.read().decode("utf-8"))["token"]
    request = urllib.request.Request(
        f"https://public.ecr.aws/v2/{repository}/manifests/{tag}",
        method="HEAD",
        headers={"Authorization": f"Bearer {_TOKENS[repository]}", "Accept": _MANIFEST_ACCEPT},
    )
    with _open_with_backoff(request) as response:
        digest = response.headers.get("Docker-Content-Digest", "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError(f"registry_digest_missing:{image}")
    return digest


def task_row(task_dir: Path, resolve_digest: Callable[[str], str]) -> dict[str, Any]:
    raw = (task_dir / "task.toml").read_bytes()
    config = tomllib.loads(raw.decode("utf-8"))
    metadata = config.get("metadata") or {}
    image = str((config.get("environment") or {}).get("docker_image") or "")
    if not image:
        raise ValueError(f"task_image_missing:{task_dir.name}")
    return {
        "task_id": task_dir.name,
        "language": str(metadata.get("language") or "unknown"),
        "base_commit": str(metadata.get("base_commit_hash") or ""),
        "task_config_sha256": hashlib.sha256(canonical_task_config_bytes(raw)).hexdigest(),
        "container_image": image,
        "container_digest": resolve_digest(image),
    }


def build_catalog(
    bench: Path,
    *,
    benchmark_sha: str,
    bundle_tasks: list[dict[str, Any]],
    resolve_digest: Callable[[str], str] = resolve_public_ecr_digest,
) -> dict[str, Any]:
    task_dirs = sorted(path for path in (bench / "tasks").iterdir()
                       if (path / "task.toml").is_file())
    rows = [dict(task_row(path, resolve_digest), ordinal=index)
            for index, path in enumerate(task_dirs, start=1)]
    by_id = {row["task_id"]: row for row in rows}
    for pinned in bundle_tasks:
        row = by_id.get(str(pinned.get("task_id")))
        if row is None:
            raise ValueError(f"bundle_task_missing_from_catalog:{pinned.get('task_id')}")
        for field in _COMPARED_FIELDS:
            if row[field] != pinned.get(field):
                raise ValueError(f"bundle_row_mismatch:{row['task_id']}:{field}")
    order = [row["task_id"] for row in rows]
    return {
        "schema": SCHEMA,
        "benchmark_sha": benchmark_sha,
        "task_config_identity": TASK_CONFIG_IDENTITY,
        "task_count": len(rows),
        "task_order_sha256": hashlib.sha256(("\n".join(order) + "\n").encode()).hexdigest(),
        "tasks": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", required=True, help="deep-swe checkout at --benchmark-sha")
    parser.add_argument("--benchmark-sha", required=True)
    parser.add_argument("--bundle", default="config/deepswe_product_bundle_v1.json")
    parser.add_argument("--output", default="config/deepswe_task_catalog_v1.json")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    catalog = build_catalog(Path(args.bench), benchmark_sha=args.benchmark_sha,
                            bundle_tasks=list(bundle.get("tasks") or []))
    Path(args.output).write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
    print(f"{catalog['task_count']} tasks -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
