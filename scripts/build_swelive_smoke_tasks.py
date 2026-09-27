"""Build the five-task SWE-bench-Live Lite smoke package (cohort ``smoke5``).

The smoke cohort is the first five rows of the pinned catalog
(``config/swelive_lite_catalog_v1.json``), in dataset-snapshot order. Image
digests and task-config digests come from the catalog, never from constants in
this file, and the packages are rendered by the catalog's own renderer
(``scripts.build_swelive_catalog.render_task``), so the smoke packages and the
full-cohort packages cannot drift apart.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.build_swelive_catalog import (
    CATALOG_PATH,
    MANIFEST_SCHEMA,
    ROOT,
    TASK_CONFIG_IDENTITY,
    load_catalog,
    load_rows,
    materialize,
    smoke5_task_ids,
    template_files,
)


def build(output: Path, catalog_path: Path = CATALOG_PATH) -> dict[str, Any]:
    """Materialize the five smoke packages under ``output/tasks``.

    Returns the smoke manifest (the catalog's first five rows). Existing
    packages are verified byte-for-byte rather than overwritten.
    """
    catalog = load_catalog(catalog_path)
    task_ids = smoke5_task_ids(catalog)
    materialize(catalog, load_rows(), output / "tasks", task_ids, templates=template_files())
    rows = {row["task_id"]: row for row in catalog["tasks"]}
    return {
        "schema": MANIFEST_SCHEMA,
        "cohort": "smoke5",
        "task_config_identity": TASK_CONFIG_IDENTITY,
        "tasks": [
            {
                key: rows[task_id][key]
                for key in (
                    "ordinal", "task_id", "language", "base_commit",
                    "task_config_sha256", "container_image", "container_digest",
                )
            }
            for task_id in task_ids
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "swelive-bench")
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
