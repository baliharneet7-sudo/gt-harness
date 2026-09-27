"""Re-pin the product source identity in config/tb2_gt_import_manifest.json.

The readiness workflows refuse a checkout whose product trees (gt_engine,
gt_harness, eval, vendor, ...) differ from the manifest's ``source_object_ids``
- the invariant that the code graded is the code declared. The manifest was
pinned to the UNION import (921bec20); canonical and every branch after it
fail that check. This re-derives the pin from a named product commit.

Only paths outside the pinned set (config/, tests/, workflows) may change in
the commit that records the new pin, so the pin stays valid at that commit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MANIFEST = Path("config/tb2_gt_import_manifest.json")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def rederive(manifest: dict, commit: str) -> dict:
    resolved = git("rev-parse", f"{commit}^{{commit}}")
    updated = dict(manifest)
    updated["gt_source_commit"] = resolved
    updated["gt_source_parent"] = git("rev-parse", f"{resolved}^")
    updated["source_object_ids"] = {
        path: git("rev-parse", f"{resolved}:{path}") for path in manifest["source_object_ids"]
    }
    return updated


def verify(manifest: dict, ref: str = "HEAD") -> list[str]:
    """Pinned paths whose tree at ``ref`` differs from the manifest."""
    return [path for path, expected in manifest["source_object_ids"].items()
            if git("rev-parse", f"{ref}:{path}") != expected]


def _replace_values(raw: str, before: dict, after: dict) -> str:
    """Swap each pinned object id in place so the file keeps its layout."""
    pairs = [(before[k], after[k]) for k in ("gt_source_commit", "gt_source_parent")]
    pairs += [(before["source_object_ids"][k], after["source_object_ids"][k])
              for k in before["source_object_ids"]]
    out = raw
    for old, new in pairs:
        if old == new:
            continue
        if out.count(f'"{old}"') != 1:
            raise SystemExit(f"pinned value {old} is not unique in {MANIFEST}")
        out = out.replace(f'"{old}"', f'"{new}"')
    if json.loads(out.lstrip("﻿")) != after:
        raise SystemExit("in-place rewrite does not reproduce the re-derived manifest")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="product commit to pin")
    parser.add_argument("--check", action="store_true", help="only verify HEAD against the pin")
    args = parser.parse_args(argv)
    raw = MANIFEST.read_text(encoding="utf-8-sig")
    manifest = json.loads(raw)
    if args.check:
        drift = verify(manifest)
        print(json.dumps({"gt_source_commit": manifest["gt_source_commit"], "drift": drift}))
        return 1 if drift else 0
    updated = rederive(manifest, args.commit)
    MANIFEST.write_bytes(_replace_values(raw, manifest, updated).encode("utf-8"))
    print(json.dumps({"gt_source_commit": updated["gt_source_commit"], "paths": len(updated["source_object_ids"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
