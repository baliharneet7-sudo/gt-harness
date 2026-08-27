"""Derive the implementation language for Live-Lite task records.

Live-Lite records do not carry ``repo_language``.  Patch extensions are the
strongest task-local signal, but configuration-only changes can have no source
file in the patch, so the manifest's repository set is used as a conservative
metadata fallback for the known Python repositories.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


_EXTENSION_LANGUAGE = {
    ".go": "go",
    ".js": "js",
    ".jsx": "js",
    ".mjs": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".py": "python",
    ".pyi": "python",
}

# The current Live-Lite 300-task selection is drawn from these Python
# repositories.  This explicit allow-list keeps unknown future repositories
# fail-closed instead of silently assigning a language.
_PYTHON_REPOS = {
    "Delgan/loguru", "Flexget/Flexget", "Kozea/WeasyPrint", "PyPSA/PyPSA",
    "aiogram/aiogram", "amoffat/sh", "arviz-devs/arviz",
    "aws-cloudformation/cfn-lint", "beancount/beancount", "beetbox/beets",
    "beeware/briefcase", "bridgecrewio/checkov", "conan-io/conan",
    "cyclotruc/gitingest", "deepset-ai/haystack", "dynaconf/dynaconf",
    "encode/starlette", "facebookresearch/hydra", "falconry/falcon",
    "feast-dev/feast", "fonttools/fonttools", "geopandas/geopandas",
    "hiyouga/LLaMA-Factory", "huggingface/smolagents",
    "icloud-photos-downloader/icloud_photos_downloader", "instructlab/instructlab",
    "ipython/ipython", "iterative/dvc", "jazzband/tablib", "joke2k/faker",
    "jupyterlab/jupyter-ai", "kedro-org/kedro", "keras-team/keras",
    "koxudaxi/datamodel-code-generator", "kubernetes-client/python",
    "matplotlib/matplotlib", "mikedh/trimesh", "modelcontextprotocol/python-sdk",
    "pallets/flask", "patroni/patroni", "pdm-project/pdm",
    "privacyidea/privacyidea", "projectmesa/mesa", "pvlib/pvlib-python",
    "pybamm-team/PyBaMM", "pydata/xarray", "pylint-dev/pylint", "pypa/twine",
    "python-babel/babel", "python-control/python-control", "python-telegram-bot/python-telegram-bot",
    "pytorch/torchtune", "qtile/qtile", "reata/sqllineage", "reflex-dev/reflex",
    "run-llama/llama_deploy", "scrapy-plugins/scrapy-splash", "shapely/shapely",
    "sissbruecker/linkding", "sphinx-doc/sphinx", "stanford-crfm/helm",
    "stanfordnlp/dspy", "streamlink/streamlink", "sympy/sympy",
    "theOehrly/Fast-F1", "tox-dev/tox", "urllib3/urllib3",
    "wemake-services/wemake-python-styleguide", "wireservice/csvkit", "yt-dlp/yt-dlp",
}


def _changed_paths(patch: str) -> list[str]:
    return re.findall(r"^diff --git a/(\S+) b/\S+$", patch or "", flags=re.MULTILINE)


def derive_task_language(record: dict[str, Any]) -> str | None:
    """Return the short Pro language code, or ``None`` when unknowable."""
    # Repository metadata wins over incidental frontend/configuration files in
    # a Python project (for example, JupyterLab and Reflex contain JS/TS assets).
    if record.get("repo") in _PYTHON_REPOS:
        return "python"
    paths = _changed_paths(record.get("patch", "")) + _changed_paths(record.get("test_patch", ""))
    languages = {
        _EXTENSION_LANGUAGE[PurePosixPath(path).suffix.lower()]
        for path in paths
        if PurePosixPath(path).suffix.lower() in _EXTENSION_LANGUAGE
    }
    if len(languages) == 1:
        return languages.pop()
    if len(languages) > 1:
        # Python tests/config often accompany a non-Python implementation;
        # prefer an implementation language when one is unambiguous.
        non_python = languages - {"python"}
        if len(non_python) == 1:
            return non_python.pop()
        return None
    return None
