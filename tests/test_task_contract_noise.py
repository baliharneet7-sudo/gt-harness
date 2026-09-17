from __future__ import annotations

import gt_engine.task_contract as tc


def test_workflow_noise_is_filtered():
    assert tc._is_workflow_noise("read and analyze the repository carefully")
    assert tc._is_workflow_noise(
        "learn or recall the knowledge regarding the common weakness enumeration (CWE)"
    )
    assert tc._is_workflow_noise("Input Validation & Injection")
    assert tc._is_workflow_noise(
        "CWE-116: Improper Encoding or Escaping of Output - Leads to injection issues"
    )


def test_real_requirements_survive_noise_filter():
    assert not tc._is_workflow_noise(
        "create a /app/report.jsonl file in /app folder and report the code vulnerability"
    )
    assert not tc._is_workflow_noise("Make all test cases pass")
    assert not tc._is_workflow_noise(
        "fix the code vulnerability by modify the code file accordingly"
    )


def test_markdown_candidates_skip_catalog_and_workflow_rows():
    text = (
        "You need to identify and fix the vulnerability according to CWE.\n"
        "1. read and analyze the repository carefully\n"
        "2. learn or recall the knowledge regarding CWE\n"
        "3. identify the code vulnerability in /app/bottle.py\n"
        "create a /app/report.jsonl file in /app folder and report it.\n"
        "It should contain vulnerable items.\n"
        "1. Input Validation & Injection\n"
        "CWE-116: Improper Encoding or Escaping of Output\n"
    )
    candidates = tc._markdown_candidates(text)
    joined = "\n".join(t for _, t in candidates).lower()
    assert "read and analyze the repository" not in joined
    assert "learn or recall" not in joined
    assert "input validation & injection" not in joined
    assert "cwe-116" not in joined
    assert "create a /app/report.jsonl file" in joined
    assert "vulnerable items" in joined


def test_extract_task_contract_prefers_engine_rows_over_noise():
    text = (
        "You must fix the compute() bug in src/mod.py.\n"
        "1. read and analyze the repository carefully\n"
        "create a /app/report.jsonl file in /app folder.\n"
    )
    contract = tc.extract_task_contract(text)
    texts = " ".join(o.text for o in contract.obligations).lower()
    assert "read and analyze the repository carefully" not in texts
    assert "report.jsonl" in texts
