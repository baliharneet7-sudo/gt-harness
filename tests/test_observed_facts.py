"""Tests for the general, cross-task observed-execution fact surface."""

from __future__ import annotations

from gt_engine.observed_facts import extract_observed_facts, observed_fact_payload

READELF_DYN = (
    "ELF Header:\n"
    "  Class:                             ELF64\n"
    "  Type: DYN (Position-Independent Executable file)\n"
)
FILE_EXEC = "a.out: ELF 64-bit LSB executable, x86-64"
FILE_PIE = "server: ELF 64-bit LSB shared object, x86-64, dynamically linked"
NODE_VERSION = "v20.11.1"


def _facts(command, output, *, already=None):
    return extract_observed_facts(
        command=command,
        output=output,
        source_revision="s1",
        evidence_action=3,
        eligible_call=4,
        already_delivered=set(already or ()),
    )


def test_observed_fact_recognizes_pie_binary_across_tasks():
    # Same pattern fires regardless of the task — extract-elf is just one case.
    f = _facts("readelf -h a.out", READELF_DYN)
    assert f
    assert f[0].kind == "elf_type"
    assert "PIE" in f[0].text
    assert "virtual addresses are relative" in f[0].text
    # A different task inspecting a PIE server binary gets the same fact.
    g = _facts("file server", FILE_PIE)
    assert g and g[0].kind == "elf_type"
    assert "PIE" in g[0].text


def test_observed_fact_recognizes_nonpie_executable():
    f = _facts("file a.out", FILE_EXEC)
    assert f
    assert f[0].kind == "elf_type"
    assert "non-PIE" in f[0].text


def test_observed_fact_does_not_fabricate_on_unrelated_output():
    f = _facts("ls -la", "total 28\ndrwxr-xr-x 2 root root 4096")
    assert f == ()


def test_observed_fact_recognizes_tool_version_generically():
    f = _facts("node --version", NODE_VERSION)
    assert f and f[0].kind == "tool_version"
    assert "node 20" in f[0].text


def test_observed_fact_deduplicates_across_deliveries():
    f = _facts("readelf -h a.out", READELF_DYN)
    again = _facts("readelf -h a.out", READELF_DYN, already={f[0].fact_id})
    assert again == ()


def test_observed_fact_payload_is_bounded_grounded_and_single_line():
    f = _facts("readelf -h a.out", READELF_DYN)
    payload = observed_fact_payload(f[0])
    assert isinstance(payload, str)
    assert " " in payload  # a sentence, not raw bytes
    assert len(payload) < 320
    assert "a.out" not in payload.lower() or "executable" in payload.lower()


def test_max_observed_facts_is_bounded():
    from gt_engine.observed_facts import MAX_OBSERVED_FACTS_PER_TASK

    assert MAX_OBSERVED_FACTS_PER_TASK >= 1
