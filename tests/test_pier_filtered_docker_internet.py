"""The filtered environment must run each task on the network it declares.

TB2 proof runs 35545356695 and 35557511581 graded every task 0 while the
agents submitted work the GT-off baseline scored 1.0 on.  The verifier
stdout said why: `Temporary failure resolving 'deb.debian.org'`, then
`/tests/test.sh: line 14: pytest: command not found`.  TB2 task files
declare no network mode, so Pier's default `allow_internet=True` applies and
the baseline verifier installed its dependencies over the network.  This
environment rewrote that to `allow_internet=False` for every task, on the
premise that Pier 0.3.1 ignores `[agent].network_mode` and needed the help;
Pier 0.3.1 resolves `network_mode` itself (`TaskConfig.resolve_network_modes`),
so the rewrite only ever changed tasks that had asked for the internet.
"""

from __future__ import annotations

import pytest

pier = pytest.importorskip("pier", reason="datacurve-pier is not installed")

from pier.environments.docker.docker import DockerEnvironment  # noqa: E402
from pier.models.task.config import EnvironmentConfig  # noqa: E402

from eval.pier_filtered_docker import PierFilteredDockerEnvironment  # noqa: E402


@pytest.fixture
def captured_config(monkeypatch):
    seen: list[EnvironmentConfig] = []

    def record(self, *, task_env_config, **kwargs):
        seen.append(task_env_config)

    monkeypatch.setattr(DockerEnvironment, "__init__", record, raising=True)
    return seen


@pytest.mark.parametrize("allow_internet", [True, False])
def test_the_task_keeps_the_network_it_declares(captured_config, allow_internet):
    declared = EnvironmentConfig(allow_internet=allow_internet)

    PierFilteredDockerEnvironment(task_env_config=declared)

    assert [config.allow_internet for config in captured_config] == [allow_internet]


def test_the_task_model_is_passed_through_unchanged(captured_config):
    declared = EnvironmentConfig(allow_internet=True)

    PierFilteredDockerEnvironment(task_env_config=declared)

    assert captured_config[0] is declared
