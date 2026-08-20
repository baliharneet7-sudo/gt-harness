#!/usr/bin/env python3
"""Fail-closed audit of the authoritative GT release documentation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_DEFAULT_DOCUMENTS = (
    Path("docs/GT_MECHANICAL_COMPLETENESS_CONTRACT.md"),
    Path("docs/GT_RELEASE_DOSSIER.md"),
)
_REQUIRED_TERMS = {
    "GT_MECHANICAL_COMPLETENESS_CONTRACT.md": (
        "gt.task_execution_certificate.v1",
        "PROVEN_NOT_APPLICABLE",
        "MechanicalCompletenessBlocked",
        "hidden_reasoning_inferred",
        "repair20-v1",
        "gt.provider_value.v1",
    ),
    "GT_RELEASE_DOSSIER.md": (
        "active_release.json",
        "GT_MECHANICAL_COMPLETENESS=PASS",
        "central_relational_v2",
        "central_provider_free.yml",
        "mechanical_completeness: PASS",
        "does not embed a mutable latest-run ID",
        "scripts.harbor_results",
    ),
}
_FORBIDDEN_OUTCOME_CLAIMS = (
    "100% solve guaranteed",
    "all tasks will solve",
    "18/18 fired",
)
_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def audit_documentation(
    root: Path,
    *,
    documents: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    paths = tuple(
        path if path.is_absolute() else root / path
        for path in (documents or _DEFAULT_DOCUMENTS)
    )
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"missing_document:{path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in _FORBIDDEN_OUTCOME_CLAIMS:
            if phrase.lower() in text.lower():
                failures.append(f"unearned_outcome_claim:{path.name}:{phrase}")
        for term in _REQUIRED_TERMS.get(path.name, ()):
            if term not in text:
                failures.append(f"missing_required_term:{path.name}:{term}")
        for target in _LINK.findall(text):
            if target.startswith(("http://", "https://", "#")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (path.parent / relative).resolve().exists():
                failures.append(f"broken_link:{path.name}:{target}")
    return {
        "schema": "gt.documentation_consistency.v1",
        "status": "PASS" if not failures else "BLOCKED",
        "checked_documents": len(paths),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_documentation(args.root)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
