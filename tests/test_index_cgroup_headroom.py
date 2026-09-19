"""The index memory guard must read the cgroup the process is actually in.

Run 35262214538 journaled nine ``GT_INDEX_MEMORY_HEADROOM_INSUFFICIENT``
refusals carrying ``limit=0, 2326528, 7020544, 12804096`` against
``need=178438144``. Two defects produced those numbers and this module pins
both fixes with mocked ``/proc`` and ``/sys/fs/cgroup`` trees - no live host
is read, so the evidence is the same on Windows, on a v1 host and in CI.

1. ``_cgroup_snapshot`` opened ``/sys/fs/cgroup/memory.*`` directly. That is
   the unified hierarchy's ROOT, not the task's cgroup: on a v2 host its
   ``memory.max`` is the literal ``max`` (unlimited by construction) and on a
   v1 host the file does not exist at all. Neither reading is the ceiling the
   producer would actually die against.
2. ``_read_integer`` collapsed three different facts - "unlimited", "file
   absent" and "file would not parse" - into one ``None``, and the limit
   formula then priced a *missing file* as *zero available memory*.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gt_engine import indexer
from gt_harness.cgroup import memory_snapshot

MIB = 1024 * 1024


def _mock_roots(
    tmp_path: Path,
    *,
    version: int,
    limit: str,
    current: str = "12",
    pid: int = 42,
    member: str = "/docker/task",
) -> tuple[Path, Path, Path]:
    """Build a /proc + controller-mount pair the way tests/test_cgroup.py does.

    Returns ``(proc_root, sys_root, controller_dir)``. ``sys_root`` is a DECOY
    unified root carrying an unlimited ceiling: a reader that still opens
    ``/sys/fs/cgroup/memory.max`` will report "no limit" and be caught.
    """
    proc = tmp_path / "proc"
    (proc / str(pid)).mkdir(parents=True)
    (proc / "self").mkdir()
    mount = tmp_path / "controller"
    directory = mount / member.lstrip("/").split("/", 1)[1]
    directory.mkdir(parents=True)
    lines = f"0::{member}\n" if version == 2 else f"0::{member}\n5:memory:{member}\n"
    (proc / str(pid) / "cgroup").write_text(lines, encoding="ascii")
    filesystem = "cgroup2 cgroup2 rw" if version == 2 else "cgroup cgroup rw,memory"
    (proc / "self" / "mountinfo").write_text(
        f"1 0 0:1 /docker {mount.as_posix()} rw - {filesystem}\n", encoding="ascii"
    )
    fields = (
        {
            "memory.current": current,
            "memory.max": limit,
            "memory.peak": "24",
            "memory.events": "oom 2\noom_kill 1\n",
        }
        if version == 2
        else {
            "memory.usage_in_bytes": current,
            "memory.limit_in_bytes": limit,
            "memory.max_usage_in_bytes": "24",
            "memory.oom_control": "under_oom 0\noom_kill 1\n",
        }
    )
    for name, value in fields.items():
        (directory / name).write_text(value, encoding="ascii")

    sys_root = tmp_path / "sys-fs-cgroup"
    sys_root.mkdir()
    (sys_root / "memory.current").write_text("1", encoding="ascii")
    (sys_root / "memory.max").write_text("max", encoding="ascii")
    return proc, sys_root, directory


@pytest.mark.parametrize("version", [1, 2])
def test_snapshot_reads_the_processes_own_cgroup_not_the_unified_root(
    tmp_path: Path, version: int
) -> None:
    """The decoy root says "unlimited"; the task cgroup says 512 MiB."""
    proc, sys_root, _directory = _mock_roots(
        tmp_path, version=version, limit=str(512 * MIB), current=str(400 * MIB)
    )

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["max"] == 512 * MIB
    assert snapshot["current"] == 400 * MIB
    assert snapshot["cgroup_version"] == version
    assert snapshot["limit_state"] == "limited"
    assert snapshot["headroom_basis"] == "max_and_current"
    assert snapshot["peak"] == 24
    assert snapshot["oom_kill"] == 1


def test_v2_literal_max_is_unlimited_not_unreadable(tmp_path: Path) -> None:
    proc, sys_root, _directory = _mock_roots(tmp_path, version=2, limit="max")

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["max"] is None
    assert snapshot["limit_state"] == "unlimited"
    assert snapshot["headroom_basis"] == "uncapped"
    assert snapshot["current"] == 12


def test_v1_page_counter_sentinel_is_unlimited(tmp_path: Path) -> None:
    """v1 has no literal "max": an unlimited controller reads as the sentinel.

    ``memory.limit_in_bytes`` reports PAGE_COUNTER_MAX pages scaled to bytes,
    0x7FFFFFFFFFFFF000 on a 64-bit kernel. Read as a ceiling it would hand the
    guard an ~8 EiB budget, which is the mirror image of the limit=0 defect.
    """
    proc, sys_root, _directory = _mock_roots(
        tmp_path, version=1, limit=str(0x7FFFFFFFFFFFF000)
    )

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["max"] is None
    assert snapshot["limit_state"] == "unlimited"
    assert snapshot["cgroup_version"] == 1


def test_unparseable_limit_is_unreadable_not_a_limit_of_zero(tmp_path: Path) -> None:
    proc, sys_root, directory = _mock_roots(tmp_path, version=2, limit="max")
    (directory / "memory.max").write_text("not-a-number\n", encoding="ascii")

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["max"] is None
    assert snapshot["limit_state"] == "unreadable"
    assert snapshot["headroom_basis"] == "no_ceiling_evidence"
    # The controller was LOCATED - only its ceiling would not parse. Saying
    # "unified_root" here would credit the reading to a cgroup nobody read.
    assert snapshot["source"] == "proc_self_cgroup"
    assert snapshot["cgroup_version"] == 2


def test_no_controller_falls_back_to_the_unified_root(tmp_path: Path) -> None:
    """A cgroup-namespaced container sees its own ceiling at the v2 root.

    When /proc cannot be walked (no membership file, a non-Linux host) the
    root read is still the best available evidence, so it stays as a fallback
    rather than being deleted with the defect.
    """
    proc = tmp_path / "proc"
    proc.mkdir()
    sys_root = tmp_path / "sys-fs-cgroup"
    sys_root.mkdir()
    (sys_root / "memory.current").write_text(str(200 * MIB), encoding="ascii")
    (sys_root / "memory.max").write_text(str(900 * MIB), encoding="ascii")
    (sys_root / "memory.peak").write_text(str(300 * MIB), encoding="ascii")
    (sys_root / "memory.events").write_text("oom 0\noom_kill 3\n", encoding="ascii")

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["max"] == 900 * MIB
    assert snapshot["current"] == 200 * MIB
    assert snapshot["peak"] == 300 * MIB
    assert snapshot["oom_kill"] == 3
    assert snapshot["limit_state"] == "limited"
    assert snapshot["source"] == "unified_root"


def test_no_cgroup_anywhere_reports_unreadable_without_raising(
    tmp_path: Path,
) -> None:
    """A Windows or macOS developer box has neither tree. It must not raise."""
    snapshot = indexer._cgroup_snapshot(
        proc_root=tmp_path / "absent-proc",
        sys_root=tmp_path / "absent-sys",
        pid=42,
    )

    assert snapshot["max"] is None
    assert snapshot["current"] is None
    assert snapshot["limit_state"] == "unreadable"
    assert snapshot["headroom_basis"] == "no_ceiling_evidence"
    assert snapshot["cgroup_version"] is None
    assert snapshot["oom"] is None and snapshot["oom_kill"] is None


def test_default_roots_are_the_real_ones_and_need_no_arguments() -> None:
    """The production call sites pass nothing; the defaults must be real paths.

    Pinned because the injection points exist for tests only - a default that
    drifted to a fixture path would silently blind the guard in production.
    """
    import inspect

    parameters = inspect.signature(indexer._cgroup_snapshot).parameters
    assert parameters["proc_root"].default == Path("/proc")
    assert parameters["sys_root"].default == Path("/sys/fs/cgroup")
    assert parameters["pid"].default is None
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    )
    assert indexer._cgroup_snapshot()["limit_state"] in {
        "limited",
        "unlimited",
        "unreadable",
    }


def test_unreadable_current_estimates_from_max_instead_of_refusing() -> None:
    """A diagnostic gap must not be spent as a refusal.

    ``current=None`` means the usage file could not be read. The old formula
    returned 0 for it, and 0 is below the 64 MiB launch floor, so a graph
    refresh was refused on a MISSING FILE rather than on missing memory - run
    35262214538, nine refusals, ``lsp_promotion`` left non-WORKING. With the
    ceiling readable the honest estimate is the half-of-cgroup rule alone,
    reported as ``max_only`` so nobody reads it as a measurement.
    """
    assert indexer._effective_index_memory_limit(
        {"max": 1024 * MIB, "current": None, "limit_state": "limited",
         "headroom_basis": "max_only"}
    ) == 512 * MIB


def test_max_only_estimate_still_respects_the_four_gib_cap() -> None:
    assert indexer._effective_index_memory_limit(
        {"max": 16 * 1024 * MIB, "current": None, "limit_state": "limited",
         "headroom_basis": "max_only"}
    ) == indexer._INDEX_RSS_LIMIT_BYTES


def test_readable_current_keeps_the_reserve_arithmetic_unchanged() -> None:
    """The 128 MiB reserve and the half-of-cgroup rule are NOT being changed."""
    snapshot = {"max": 1024 * MIB, "current": 200 * MIB,
                "limit_state": "limited", "headroom_basis": "max_and_current"}
    headroom = (1024 - 200) * MIB - 128 * MIB
    assert indexer._effective_index_memory_limit(snapshot) == min(
        indexer._INDEX_RSS_LIMIT_BYTES, 512 * MIB, headroom)


def test_no_readable_ceiling_still_gets_the_flat_cap() -> None:
    """Both states keep the 4 GiB cap - and both must SAY which one they are.

    Deliberate: a Windows developer box and a host with no cgroup at all read
    as ``unreadable``, and lowering their budget would refuse legitimate local
    amends over a fact about the HOST rather than about memory; the in-flight
    RSS guard is the backstop. What the two must not share is the WORD. Only
    ``unlimited`` is evidence of no ceiling; ``unreadable`` is no evidence.
    """
    for state, basis in (("unlimited", "uncapped"),
                         ("unreadable", "no_ceiling_evidence")):
        assert indexer._headroom_basis(state, None) == basis
        snapshot = {"max": None, "current": None, "limit_state": state,
                    "headroom_basis": basis}
        assert (indexer._effective_index_memory_limit(snapshot)
                == indexer._INDEX_RSS_LIMIT_BYTES)


def test_headroom_basis_names_the_four_readings_apart() -> None:
    assert indexer._headroom_basis("limited", 1) == "max_and_current"
    assert indexer._headroom_basis("limited", None) == "max_only"
    assert indexer._headroom_basis("unlimited", None) == "uncapped"
    assert indexer._headroom_basis("unreadable", None) == "no_ceiling_evidence"


def test_a_pressured_cgroup_still_refuses() -> None:
    """The fix must not turn the guard off: real pressure still reads as 0."""
    assert indexer._effective_index_memory_limit(
        {"max": 200 * MIB, "current": 190 * MIB, "limit_state": "limited",
         "headroom_basis": "max_and_current"}
    ) == 0


def test_launch_floor_receipt_carries_the_cgroup_reading(
    tmp_path: Path, monkeypatch
) -> None:
    """The initial-build refusal records WHICH cgroup it read and how.

    It already carried current/max. Version, limit state and headroom basis
    are what make those two numbers interpretable after the run: a 0 that came
    from a full cgroup and a 0 that came from an unreadable one are the same
    integer and call for opposite remedies.
    """
    monkeypatch.setattr(
        indexer, "_has_verified_index_process_tree_guard", lambda: True)
    monkeypatch.setattr(
        indexer, "_cgroup_snapshot",
        lambda **_kwargs: {
            "current": None, "max": 100 * MIB, "peak": None,
            "oom": None, "oom_kill": None, "cgroup_version": 1,
            "limit_state": "limited", "headroom_basis": "max_only",
            "source": "proc_self_cgroup",
        },
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("a refused build spawned a producer")
    monkeypatch.setattr(indexer, "_resolved_binary_path", forbidden)

    result = indexer._run_index_bounded(
        str(tmp_path), tmp_path / "graph.db", tmp_path)

    assert result.error_code == "GT_INDEX_MEMORY_HEADROOM_INSUFFICIENT"
    assert result.memory_limit_bytes == 50 * MIB  # max // 2, below the floor
    assert result.cgroup_memory_max == 100 * MIB
    assert result.cgroup_memory_current_before is None
    assert result.cgroup_version == 1
    assert result.cgroup_limit_state == "limited"
    assert result.cgroup_headroom_basis == "max_only"


@pytest.mark.parametrize("absent", ["memory.peak", "memory.events"])
def test_optional_v2_files_no_longer_cost_the_ceiling(
    tmp_path: Path, absent: str
) -> None:
    """``memory.peak`` arrived in Linux 5.19. It must not decide the BUDGET.

    ``gt_harness.cgroup.memory_snapshot`` reads ``memory.peak`` and
    ``memory.events`` eagerly, so consuming it whole made an absent OPTIONAL
    file raise ``FileNotFoundError`` - an ``OSError``, indistinguishable from
    "no cgroup here" - and drop the snapshot back to the unified root. On an
    older v2 kernel the guard then reported ``unlimited`` for a 256 MiB cgroup
    whose ``memory.max`` it had opened successfully a syscall earlier, and
    handed the producer the 4 GiB flat cap. Resolving the controller here
    keeps the two apart: the ceiling is mandatory, peak and the event counters
    are best effort.
    """
    proc, sys_root, directory = _mock_roots(
        tmp_path, version=2, limit=str(256 * MIB), current=str(100 * MIB)
    )
    (directory / absent).unlink()

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["source"] == "proc_self_cgroup"
    assert snapshot["max"] == 256 * MIB
    assert snapshot["current"] == 100 * MIB
    assert snapshot["cgroup_version"] == 2
    assert snapshot["limit_state"] == "limited"
    assert snapshot["headroom_basis"] == "max_and_current"
    if absent == "memory.peak":
        assert snapshot["peak"] is None
        assert snapshot["oom"] == 2 and snapshot["oom_kill"] == 1
    else:
        assert snapshot["peak"] == 24
        assert snapshot["oom"] is None and snapshot["oom_kill"] is None
    # The reproduction, in one number: a 256 MiB ceiling with 100 MiB resident
    # is 156 MiB of headroom less the 128 MiB reserve -- not the 4 GiB cap.
    assert indexer._effective_index_memory_limit(snapshot) == 28 * MIB


@pytest.mark.parametrize("version", [1, 2])
def test_the_indexer_resolver_agrees_with_gt_harness_cgroup(
    tmp_path: Path, version: int
) -> None:
    """Two resolvers, one controller: pin the agreement so the copy cannot rot.

    ``gt_harness/cgroup.py`` keeps its /proc walk INLINE in ``memory_snapshot``
    and exports no resolution helper, and that module is out of scope for this
    change, so the walk is replicated in ``indexer._resolve_memory_controller``
    with cgroup.py as the reference. A replica can drift; this is the test that
    fails when it does. The fixtures are the ones ``tests/test_cgroup.py``
    builds, so both readers are judged on the same host.
    """
    proc, sys_root, directory = _mock_roots(
        tmp_path, version=version, limit=str(512 * MIB), current=str(400 * MIB)
    )

    resolved = indexer._resolve_memory_controller(42, proc_root=proc)
    reference = memory_snapshot(42, proc_root=proc)

    assert resolved is not None
    resolved_version, resolved_directory = resolved
    assert resolved_version == reference["cgroup_version"] == version
    assert resolved_directory == directory.resolve()
    assert (hashlib.sha256(str(resolved_directory).encode()).hexdigest()
            == reference["cgroup_path_sha256"])

    # ...and the values read out of that directory agree too.
    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)
    for field in ("current", "max", "peak", "oom", "oom_kill", "cgroup_version"):
        assert snapshot[field] == reference[field], field


def test_a_controller_it_could_not_read_is_never_reported_unlimited(
    tmp_path: Path,
) -> None:
    """The last-resort path: located, unreadable, and honest about both."""
    proc, sys_root, directory = _mock_roots(
        tmp_path, version=2, limit=str(256 * MIB), current=str(100 * MIB)
    )
    (directory / "memory.max").unlink()

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["source"] == "proc_self_cgroup"
    assert snapshot["limit_state"] == "unreadable"
    assert snapshot["headroom_basis"] == "no_ceiling_evidence"
    assert snapshot["max"] is None
    assert snapshot["current"] == 100 * MIB
    assert snapshot["cgroup_version"] == 2


@pytest.mark.parametrize("limit", ["-1", "-268435456"])
def test_a_negative_ceiling_still_fails_closed(tmp_path: Path, limit: str) -> None:
    """A ceiling below zero is not a budget. It must refuse, never expand."""
    proc, sys_root, _directory = _mock_roots(
        tmp_path, version=2, limit=limit, current="12"
    )

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["limit_state"] == "limited"
    assert indexer._effective_index_memory_limit(snapshot) <= 0


def test_usage_above_the_ceiling_leaves_no_headroom(tmp_path: Path) -> None:
    """Real pressure still reads as zero - the fix must not switch the guard off."""
    proc, sys_root, _directory = _mock_roots(
        tmp_path, version=2, limit=str(256 * MIB), current=str(300 * MIB)
    )

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["headroom_basis"] == "max_and_current"
    assert indexer._effective_index_memory_limit(snapshot) == 0


def test_a_bind_mounted_controller_root_resolves_to_the_task_cgroup(
    tmp_path: Path,
) -> None:
    """mountinfo field 4 is the SUBTREE mounted, and it is not always "/".

    A bind of the task's own directory reports root ``/docker/task`` with the
    mountpoint elsewhere. The membership path has to be taken RELATIVE to that
    root; appending it whole would look under ``<mount>/docker/task`` and find
    nothing, which is a fallback to the unified root all over again.
    """
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "self").mkdir()
    mount = tmp_path / "bind"
    mount.mkdir()
    (proc / "42" / "cgroup").write_text("0::/docker/task\n", encoding="ascii")
    (proc / "self" / "mountinfo").write_text(
        f"1 0 0:1 /docker/task {mount.as_posix()} rw - cgroup2 cgroup2 rw\n",
        encoding="ascii",
    )
    (mount / "memory.current").write_text(str(100 * MIB), encoding="ascii")
    (mount / "memory.max").write_text(str(256 * MIB), encoding="ascii")
    sys_root = tmp_path / "sys-fs-cgroup"
    sys_root.mkdir()
    (sys_root / "memory.max").write_text("max", encoding="ascii")

    assert indexer._resolve_memory_controller(42, proc_root=proc) == (
        2, mount.resolve())
    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)
    assert snapshot["source"] == "proc_self_cgroup"
    assert snapshot["max"] == 256 * MIB
    assert snapshot["current"] == 100 * MIB


def test_a_hybrid_cgroup_file_picks_the_memory_controller_line(
    tmp_path: Path,
) -> None:
    """A v1 hybrid host lists one line per hierarchy and they disagree.

    ``/proc/<pid>/cgroup`` carries a unified line plus one line per v1
    controller group, on DIFFERENT paths. Taking the first line, or the
    unified one when no cgroup2 is mounted, reads a cgroup this process's
    memory is not accounted against - here an 8 MiB decoy instead of the
    256 MiB ceiling the producer would actually die at.
    """
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "self").mkdir()
    mount = tmp_path / "controller"
    decoy = mount / "cpu-only"
    memory_dir = mount / "task"
    decoy.mkdir(parents=True)
    memory_dir.mkdir(parents=True)
    (proc / "42" / "cgroup").write_text(
        "0::/docker/unified-only\n"
        "7:cpu,cpuacct:/docker/cpu-only\n"
        "5:devices:/docker/cpu-only\n"
        "4:memory,hugetlb:/docker/task\n",
        encoding="ascii",
    )
    (proc / "self" / "mountinfo").write_text(
        f"1 0 0:1 /docker {mount.as_posix()} rw - cgroup cgroup rw,memory\n",
        encoding="ascii",
    )
    for name, value in {"memory.usage_in_bytes": str(100 * MIB),
                        "memory.limit_in_bytes": str(256 * MIB)}.items():
        (memory_dir / name).write_text(value, encoding="ascii")
    for name, value in {"memory.usage_in_bytes": "1",
                        "memory.limit_in_bytes": str(8 * MIB)}.items():
        (decoy / name).write_text(value, encoding="ascii")
    sys_root = tmp_path / "sys-fs-cgroup"
    sys_root.mkdir()
    (sys_root / "memory.max").write_text("max", encoding="ascii")

    assert indexer._resolve_memory_controller(42, proc_root=proc) == (
        1, memory_dir.resolve())
    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)
    assert snapshot["cgroup_version"] == 1
    assert snapshot["max"] == 256 * MIB
    assert snapshot["current"] == 100 * MIB


def test_a_controller_path_that_escapes_its_mount_is_a_gap_not_a_root_read(
    tmp_path: Path,
) -> None:
    """The one ValueError left, and the last-resort branch it feeds.

    Now that the ceiling is parsed here, a ``ValueError`` out of the resolver
    can only mean the membership path resolved OUTSIDE its mount - a located
    but untrustworthy controller. Answering that with the unified root would
    publish some other cgroup's ceiling, usually ``unlimited``, so it reports
    the gap: the flat cap is still spent, but as ``no_ceiling_evidence``.
    """
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "self").mkdir()
    mount = tmp_path / "controller"
    (mount / "task").mkdir(parents=True)
    (proc / "42" / "cgroup").write_text("0::/docker/../../escape\n", encoding="ascii")
    (proc / "self" / "mountinfo").write_text(
        f"1 0 0:1 /docker {mount.as_posix()} rw - cgroup2 cgroup2 rw\n",
        encoding="ascii",
    )
    sys_root = tmp_path / "sys-fs-cgroup"
    sys_root.mkdir()
    (sys_root / "memory.current").write_text("1", encoding="ascii")
    (sys_root / "memory.max").write_text("max", encoding="ascii")

    with pytest.raises(ValueError, match="escaped mount"):
        indexer._resolve_memory_controller(42, proc_root=proc)

    snapshot = indexer._cgroup_snapshot(proc_root=proc, sys_root=sys_root, pid=42)

    assert snapshot["source"] == "controller_unreadable"
    assert snapshot["limit_state"] == "unreadable"
    assert snapshot["headroom_basis"] == "no_ceiling_evidence"
    assert snapshot["cgroup_version"] is None
    assert (indexer._effective_index_memory_limit(snapshot)
            == indexer._INDEX_RSS_LIMIT_BYTES)


def _v2_controller(directory: Path, *, limit: int, current: int) -> None:
    """One COMPLETE cgroup2 memory controller directory.

    Every optional file is written in every candidate directory on purpose.
    ``gt_harness.cgroup.memory_snapshot`` reads ``memory.peak`` and
    ``memory.events`` eagerly, so an absent optional file would make the
    reference raise where the replica merely reports ``peak=None`` - and these
    tests would then be measuring THAT difference instead of the mount
    ordering they exist to pin.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in {
        "memory.current": str(current),
        "memory.max": str(limit),
        "memory.peak": str(current),
        "memory.events": "oom 0\noom_kill 0\n",
    }.items():
        (directory / name).write_text(value, encoding="ascii")


def _two_cgroup2_mounts(
    tmp_path: Path,
    *,
    ids: tuple[str, str],
    host_first: bool = True,
    host_contains_member: bool = True,
) -> tuple[Path, Path, Path]:
    """A container that can see BOTH its own cgroup2 mount and the host tree.

    The benchmark image bind-mounts the host hierarchy at
    ``/host/sys/fs/cgroup`` for the resource evidence collector, so
    ``/proc/self/mountinfo`` carries two ``cgroup2`` lines while
    ``/proc/<pid>/cgroup`` carries one membership, ``0::/docker/task``, that
    resolves under EITHER. Which one a resolver returns is then decided
    entirely by how it orders the candidates.

    The two directories are given deliberately different ceilings so the pick
    is observable: ``ids[0]`` (the host bind) reports 4 GiB, ``ids[1]`` (the
    namespaced mount) reports 256 MiB. Returns
    ``(proc_root, host_task_dir, namespaced_task_dir)``.
    """
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "self").mkdir()
    (proc / "42" / "cgroup").write_text("0::/docker/task\n", encoding="ascii")

    host = tmp_path / "host-sys-fs-cgroup"
    namespaced = tmp_path / "sys-fs-cgroup"
    host.mkdir()
    namespaced.mkdir()
    host_task = host / "docker" / "task"
    namespaced_task = namespaced / "docker" / "task"
    if host_contains_member:
        _v2_controller(host_task, limit=4096 * MIB, current=64 * MIB)
    _v2_controller(namespaced_task, limit=256 * MIB, current=144 * MIB)

    lines = {
        ids[0]: f"{ids[0]} 25 0:26 / {host.as_posix()} rw - cgroup2 cgroup2 rw",
        ids[1]: f"{ids[1]} 24 0:26 / {namespaced.as_posix()} rw - cgroup2 cgroup2 rw",
    }
    order = [ids[0], ids[1]] if host_first else [ids[1], ids[0]]
    (proc / "self" / "mountinfo").write_text(
        "".join(lines[key] + "\n" for key in order), encoding="ascii"
    )
    return proc, host_task, namespaced_task


@pytest.mark.parametrize("ids", [("31", "9"), ("31", "90")])
@pytest.mark.parametrize("host_first", [True, False])
def test_two_cgroup2_mounts_resolve_the_same_way_as_the_reference(
    tmp_path: Path, ids: tuple[str, str], host_first: bool
) -> None:
    """Two mounts, one membership: the replica must pick what cgroup.py picks.

    ``gt_harness/cgroup.py:29`` sorts the WHOLE candidate tuple -
    ``sorted(candidates, reverse=True)`` over ``(version, fields, member)`` -
    so after the version it tie-breaks on ``fields`` lexicographically, and
    ``fields[0]`` is the mountinfo mount id AS A STRING. String order, not
    numeric: ``"9" > "31"`` and ``"90" > "31"``, so the reference picks mount
    ``9`` in the first fixture and ``90`` in the second, and its answer does
    not depend on the order of the lines in mountinfo.

    ``_resolve_memory_controller`` sorted on ``key=lambda row: -row[0]``, which
    is stable on the VERSION alone, so it returned whichever cgroup2 line came
    first in the file. On this host that is a 4 GiB ceiling against the
    reference's 256 MiB - two numbers for the same cgroup in the same run, one
    in the index guard and one in the resource evidence receipt.

    Agreement is the invariant, and it is asserted BOTH ways: same directory,
    and same answer whichever order mountinfo lists the mounts in.
    """
    proc, host_task, namespaced_task = _two_cgroup2_mounts(
        tmp_path, ids=ids, host_first=host_first
    )

    resolved = indexer._resolve_memory_controller(42, proc_root=proc)
    reference = memory_snapshot(42, proc_root=proc)

    assert resolved is not None
    resolved_version, resolved_directory = resolved
    assert resolved_version == reference["cgroup_version"] == 2
    assert (hashlib.sha256(str(resolved_directory).encode()).hexdigest()
            == reference["cgroup_path_sha256"]), (
        "the two resolvers picked different cgroup2 mounts")
    # The reference's tie-break is the string-max mount id, which here is the
    # namespaced mount in both fixtures - not the first line in the file.
    assert resolved_directory == namespaced_task.resolve()
    assert resolved_directory != host_task.resolve()
    assert reference["max"] == 256 * MIB

    snapshot = indexer._cgroup_snapshot(
        proc_root=proc, sys_root=tmp_path / "absent-sys", pid=42)
    for field in ("current", "max", "peak", "oom", "oom_kill", "cgroup_version"):
        assert snapshot[field] == reference[field], field


@pytest.mark.parametrize("host_first", [True, False])
def test_only_one_mount_contains_the_membership_path(
    tmp_path: Path, host_first: bool
) -> None:
    """A mount that does not contain the membership path is fallen through.

    Same two-mount host, except the host bind carries no ``/docker/task`` at
    all. Stated explicitly, because the replica must COPY the reference rather
    than improve on it: when a better-sorted mount does not contain the
    membership path, ``gt_harness/cgroup.py`` falls through it - either
    ``relative_to`` raises or the usage file is not a file, and it
    ``continue``s - and keeps looking, so it never RETURNS a mount that does
    not contain the path. Here the string-max mount id is the namespaced mount
    and that is also the only one carrying the path, so both resolvers land on
    it; reverse the mountinfo order and the answer is unchanged, which is the
    point - the ordering is total, not positional.

    Agreement is the invariant either way: if the reference ever did return a
    mount that did not contain the path, this test would pin the replica to
    that same choice and not to the "better" one.
    """
    proc, host_task, namespaced_task = _two_cgroup2_mounts(
        tmp_path, ids=("31", "9"), host_first=host_first,
        host_contains_member=False,
    )
    assert not host_task.exists()

    resolved = indexer._resolve_memory_controller(42, proc_root=proc)
    reference = memory_snapshot(42, proc_root=proc)

    assert resolved is not None
    assert resolved[1] == namespaced_task.resolve()
    assert (hashlib.sha256(str(resolved[1]).encode()).hexdigest()
            == reference["cgroup_path_sha256"])
    assert reference["max"] == 256 * MIB


def test_inside_a_cgroup_namespace_the_resolver_reads_what_head_read(
    tmp_path: Path,
) -> None:
    """M-6: no live flip in a container. HEAD already read the task ceiling.

    The claim under review was that HEAD read the unified hierarchy ROOT, whose
    ``memory.max`` is the literal ``max``, so the guard was "always permitted"
    on Linux and resolving the controller is a behaviour change in production.
    It is not, for the benchmark's case. Inside a Docker container with cgroup
    namespaces ``/sys/fs/cgroup`` IS the task cgroup and ``/proc/self/cgroup``
    reads ``0::/`` - the membership path is the mount root, so the new resolver
    resolves to the mountpoint itself and opens the SAME two files
    ``_unified_root_snapshot`` opened. That is why run 35262214538 journaled
    ``limit=0..12804096`` refusals at HEAD rather than a permitted build.

    The change only affects a process whose membership path is a STRICT
    subpath of the mount root - i.e. no cgroup namespace - and there HEAD read
    the wrong (root) cgroup.

    The numbers below are the reviewer's own fixture A: a 256 MiB ceiling with
    144 MiB resident is 112 MiB of headroom, less than the 128 MiB reserve, so
    the effective limit is 0 and every amend is refused. That is the guard
    working on real pressure, identically before and after. The remedy is more
    container memory or a smaller reserve; this campaign changes neither.
    """
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "self").mkdir()
    (proc / "42" / "cgroup").write_text("0::/\n", encoding="ascii")
    sys_root = tmp_path / "sys-fs-cgroup"
    sys_root.mkdir()
    _v2_controller(sys_root, limit=256 * MIB, current=144 * MIB)
    (proc / "self" / "mountinfo").write_text(
        f"31 25 0:26 / {sys_root.as_posix()} rw - cgroup2 cgroup2 rw\n",
        encoding="ascii",
    )

    assert indexer._resolve_memory_controller(42, proc_root=proc) == (
        2, sys_root.resolve())

    resolved_snapshot = indexer._cgroup_snapshot(
        proc_root=proc, sys_root=sys_root, pid=42)
    head_snapshot = indexer._unified_root_snapshot(sys_root)

    for field in ("max", "current", "limit_state", "headroom_basis",
                  "cgroup_version"):
        assert resolved_snapshot[field] == head_snapshot[field], field
    assert resolved_snapshot["max"] == 256 * MIB
    assert resolved_snapshot["current"] == 144 * MIB
    # Reviewer fixture A, in one number: 112 MiB of headroom under a 128 MiB
    # reserve is 0 - every amend refused, before and after the change alike.
    assert (indexer._effective_index_memory_limit(resolved_snapshot)
            == indexer._effective_index_memory_limit(head_snapshot)
            == 0)


def test_the_indexer_does_not_import_gt_harness_at_module_scope() -> None:
    """L-4: ``gt_engine.indexer`` must import with ``gt_harness`` absent.

    ``gt_harness.cgroup._unescape`` is still CONSUMED rather than copied - the
    octal-escape rule for mountinfo fields has to be one implementation or the
    two resolvers can disagree about a mountpoint with a space in it - but the
    import belongs inside the resolver, the way every other ``gt_engine`` ->
    ``gt_harness`` reach in this package is function-local, so the engine
    module still imports on a checkout where the harness package is absent.
    """
    import ast

    tree = ast.parse(Path(indexer.__file__).read_text(encoding="utf-8"))
    offenders = [
        name
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [alias.name for alias in node.names]
        )
        if name.startswith("gt_harness")
    ]
    assert offenders == [], offenders
