from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.product_repository_matrix import _percentile

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_real_repository_matrix_covers_required_product_categories() -> None:
    manifest = json.loads(
        (ROOT / "audit" / "real_repository_matrix.v1.json").read_text(encoding="utf-8")
    )

    assert manifest["schema"] == "gt.real_repository_matrix.v1"
    rows = manifest["repositories"]
    assert len(rows) == 10
    assert len({row["id"] for row in rows}) == len(rows)
    categories = {row["category"] for row in rows}
    assert {
        "python_small_conventional",
        "python_large_dynamic_framework",
        "python_heavy_reexports",
        "javascript_conventional_package",
        "typescript_barrel_exports",
        "typescript_monorepo",
        "go_standard_module",
        "go_multi_package_module",
        "rust_workspace",
        "java_multi_package_library",
    } <= categories
    for row in rows:
        assert row["url"].startswith("https://github.com/")
        assert re.fullmatch(r"[0-9a-f]{40}", row["commit"])
        assert row["languages"]
        assert row["smoke_queries"]
        for query in row["smoke_queries"]:
            assert query["mode"] in {
                "definition",
                "callers",
                "imports",
                "reexports",
                "exporters",
            }
            assert query["symbol"]
            assert query["expected_file"]


def test_matrix_percentiles_are_deterministic_and_bounded() -> None:
    assert _percentile([], 0.95) is None
    assert _percentile([30.0, 10.0, 20.0], 0.0) == 10.0
    assert _percentile([30.0, 10.0, 20.0], 0.5) == 20.0
    assert _percentile([30.0, 10.0, 20.0], 0.95) == 30.0
