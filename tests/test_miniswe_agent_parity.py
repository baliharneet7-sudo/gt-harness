from __future__ import annotations

from eval.miniswe_agent import (
    _PYTHON_VERSION,
    _UV_INSTALL,
    _UV_VERSION,
    MiniSweAgent,
    MiniSweGtAgent,
)


def test_gt_off_and_gt_on_share_the_exact_installer_implementation():
    assert MiniSweGtAgent.install is MiniSweAgent.install


def test_installer_runtime_versions_are_exact_not_floating():
    assert _UV_INSTALL == f"https://astral.sh/uv/{_UV_VERSION}/install.sh"
    assert _UV_VERSION == "0.11.32"
    assert _PYTHON_VERSION == "3.12.13"
