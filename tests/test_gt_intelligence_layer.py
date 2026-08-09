from __future__ import annotations

import sqlite3
from pathlib import Path

from gt_engine.context_frontier import (
    ContextFrontierKind,
    FrontierDisposition,
    compile_incremental_frontier,
)
from gt_engine.graph_context import build_graph_projection
from gt_engine.indexer import IndexBuildStatus, inspect_source_coverage
from gt_engine.language_registry import (
    INDEXABLE_SOURCE_SUFFIXES,
    VALIDATION_SOURCE_SUFFIXES,
    capability_for_path,
)
from gt_engine.preflight import MutationCertainty, adapt_proposed_action
from gt_engine.repository_intelligence import RepositoryIntelligenceStatus
from gt_engine.task_contract import extract_task_contract


def test_certified_language_registry_exposes_structural_support():
    cobol = capability_for_path("src/main.cob")
    python = capability_for_path("src/main.py")

    assert cobol is not None and cobol.validation_relevant is True
    assert cobol.structural_index is True
    assert python is not None and python.structural_index is True
    assert ".cob" in VALIDATION_SOURCE_SUFFIXES
    assert ".cob" in INDEXABLE_SOURCE_SUFFIXES


def test_structural_registry_matches_the_shipped_gt_index_spec_extensions():
    assert INDEXABLE_SOURCE_SUFFIXES == frozenset(
        {
            ".bash",
            ".ac",
            ".am",
            ".cbl",
            ".c",
            ".cc",
            ".cpp",
            ".cob",
            ".cs",
            ".cls",
            ".cmake",
            ".conf",
            ".css",
            ".cue",
            ".cxx",
            ".dockerfile",
            ".ex",
            ".exs",
            ".elm",
            ".go",
            ".gcode",
            ".gradle",
            ".groovy",
            ".h",
            ".hcl",
            ".hpp",
            ".htm",
            ".html",
            ".hxx",
            ".java",
            ".js",
            ".jsx",
            ".kt",
            ".kts",
            ".lua",
            ".mjs",
            ".ml",
            ".mli",
            ".mk",
            ".nc",
            ".cjs",
            ".md",
            ".php",
            ".proto",
            ".py",
            ".pyi",
            ".pov",
            ".r",
            ".rake",
            ".rb",
            ".red",
            ".rq",
            ".rs",
            ".scm",
            ".sc",
            ".scala",
            ".sh",
            ".sparql",
            ".sql",
            ".stan",
            ".sty",
            ".svelte",
            ".swift",
            ".tf",
            ".toml",
            ".ts",
            ".tsx",
            ".tap",
            ".tex",
            ".ttl",
            ".v",
            ".vim",
            ".yaml",
            ".yml",
            ".cpy",
            ".ss",
        }
    )


def test_index_coverage_reports_certified_cobol_as_indexable(tmp_path: Path):
    (tmp_path / "main.cob").write_text("IDENTIFICATION DIVISION.\nPROGRAM-ID. HELLO.\n")

    coverage = inspect_source_coverage(tmp_path)

    assert coverage.source_files == 1
    assert coverage.indexable_files == 1
    assert coverage.unsupported_suffixes == ()
    assert coverage.status is IndexBuildStatus.AVAILABLE


def test_mixed_python_and_certified_cobol_source_is_complete(tmp_path: Path):
    (tmp_path / "app.py").write_text("def app():\n    return 1\n")
    (tmp_path / "legacy.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. LEGACY.\n"
    )

    coverage = inspect_source_coverage(tmp_path)

    assert coverage.source_files == 2
    assert coverage.indexable_files == 2
    assert coverage.unsupported_suffixes == ()
    assert coverage.status is IndexBuildStatus.AVAILABLE


def test_racket_remains_explicitly_unsupported(tmp_path: Path):
    (tmp_path / "main.rkt").write_text("#lang racket\n(displayln \"hi\")\n")

    coverage = inspect_source_coverage(tmp_path)

    assert coverage.source_files == 1
    assert coverage.indexable_files == 0
    assert coverage.unsupported_suffixes == (".rkt",)
    assert coverage.status is IndexBuildStatus.UNSUPPORTED_LANGUAGE


def test_terminal_bench_code_like_suffixes_are_not_silently_ignored(tmp_path: Path):
    """All Terminal-Bench code-like suffixes are structurally accounted."""
    for suffix in (".r", ".red", ".pov"):
        path = tmp_path / f"fixture{suffix}"
        path.write_text("source fixture\n")
    (tmp_path / "fixture.v").write_text(
        "module fixture(input a, output b); assign b = a; endmodule\n"
    )

    coverage = inspect_source_coverage(tmp_path)

    assert coverage.source_files == 4
    assert coverage.indexable_files == 4
    assert coverage.unsupported_suffixes == ()
    assert coverage.status is IndexBuildStatus.AVAILABLE


def _graph_with_duplicate_fts_surfaces(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE nodes ("
            "id INTEGER PRIMARY KEY,label TEXT,name TEXT,qualified_name TEXT,"
            "file_path TEXT,start_line INTEGER,signature TEXT,language TEXT,is_test INTEGER)"
        )
        connection.execute(
            "INSERT INTO nodes VALUES (1,'function','greet','greet','src/greeter.py',7,"
            "'def greet(name: str) -> str','python',0)"
        )
        connection.execute("CREATE VIRTUAL TABLE nodes_fts USING fts5(name,file_path)")
        connection.execute(
            "INSERT INTO nodes_fts(rowid,name,file_path) VALUES (1,'greet','src/greeter.py')"
        )
        connection.execute("CREATE VIRTUAL TABLE symbol_content_fts USING fts5(content)")
        connection.execute(
            "INSERT INTO symbol_content_fts(rowid,content) VALUES (1,'greet uppercase greeting')"
        )
        connection.commit()
    finally:
        connection.close()


def test_graph_projection_uses_canonical_positive_lines_and_deduplicates_nodes(tmp_path: Path):
    graph = tmp_path / "graph.db"
    _graph_with_duplicate_fts_surfaces(graph)
    contract = extract_task_contract("Ensure greet returns uppercase text.")

    projection = build_graph_projection(str(graph), contract)

    matching = [fact for fact in projection.semantic_facts if fact.node_id == 1]
    assert len(matching) == 1
    assert matching[0].surface == "nodes_fts"
    assert matching[0].line == 7
    assert matching[0].value == "def greet(name: str) -> str"
    assert matching[0].semantic_certainty == 1.0
    # FTS rank is candidate ordering only.  It is not evidence that the hit is
    # decision-relevant; the action/task linker assigns that separately.
    assert matching[0].retrieval_relevance == 0.0


def test_compound_opaque_interpreter_is_never_claimed_read_only():
    proposal = adapt_proposed_action(
        {
            "command": (
                "python3 - <<'PY'\n"
                "from pathlib import Path\n"
                "Path('/app/app.py').write_text('x = 2\\n')\n"
                "PY\n"
                "pytest -q"
            )
        },
        source_revision="s1",
        workspace_revision="w1",
        model_call=1,
        batch_index=0,
        batch_size=1,
    )

    assert proposal.mutation_certainty is MutationCertainty.MAY_MUTATE
    assert proposal.has_opaque_segments is True
    assert proposal.parse_coverage < 1.0


def test_frontier_advances_from_represented_file_to_definition():
    evidence = {
        "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
        "available": True,
        "substrate_ready": True,
        "index_current": True,
        "intelligence_valid": True,
        "source_revision": "s1",
        "graph_revision": "g1",
        "anchors": (
            {
                "path": "src/greeter.py",
                "line": 7,
                "symbol": "greet",
                "retrieval_relevance": 1.0,
                "semantic_certainty": 1.0,
            },
        ),
        "definitions": (
            {
                "path": "src/greeter.py",
                "line": 7,
                "symbol": "greet",
                "signature": "def greet(name: str) -> str",
                "language": "python",
                "semantics": "graph_definition",
                "semantic_certainty": 1.0,
            },
        ),
        "references": (),
        "callers": (),
        "project_checks": ("pytest -q",),
    }
    messages = [
        {"role": "user", "content": "Change the greeting."},
        {
            "role": "assistant",
            "content": "",
            "extra": {"actions": [{"command": "sed -n '1,120p' src/greeter.py"}]},
        },
        {"role": "tool", "content": "def greet(name): ..."},
    ]

    decision = compile_incremental_frontier(evidence, messages, source_revision="s1")

    assert decision.disposition is FrontierDisposition.SELECTED_FRONTIER
    assert decision.facts[0].kind is ContextFrontierKind.DEFINITION
    assert decision.facts[0].language == "python"
    assert decision.accounting[0]["language"] == "python"
    assert "def greet(name: str) -> str" in decision.rendered
    assert "Repository intelligence" in decision.rendered


def test_frontier_delivers_ranked_anchor_when_no_structural_role_exists():
    """A healthy graph anchor is useful even without a CALLS/definition row."""

    evidence = {
        "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
        "available": True,
        "substrate_ready": True,
        "index_current": True,
        "intelligence_valid": True,
        "source_revision": "s1",
        "graph_revision": "g1",
        "anchors": (
            {
                "path": "legacy.cob",
                "line": 42,
                "symbol": "WRITE-RECORD",
                "surface": "nodes_fts",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
        ),
        "definitions": (),
        "references": (),
        "callers": (),
    }

    decision = compile_incremental_frontier(
        evidence,
        [{"role": "user", "content": "Update the record writer in legacy.cob."}],
        source_revision="s1",
    )

    assert decision.disposition is FrontierDisposition.SELECTED_FRONTIER
    assert decision.facts[0].kind is ContextFrontierKind.SYMBOL
    assert decision.facts[0].path == "legacy.cob"
    assert "legacy.cob:42" in decision.rendered


def test_unhealthy_repository_never_fabricates_a_frontier():
    decision = compile_incremental_frontier(
        {
            "status": RepositoryIntelligenceStatus.INDEX_UNAVAILABLE.value,
            "source_revision": "s1",
        },
        [{"role": "user", "content": "Fix it"}],
        source_revision="s1",
    )

    assert decision.disposition is FrontierDisposition.SUBSTRATE_FAILURE
    assert decision.facts == ()
    assert decision.rendered == ""


def test_frontier_budget_omits_complete_fact_instead_of_truncating_it():
    evidence = {
        "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
        "available": True,
        "substrate_ready": True,
        "index_current": True,
        "intelligence_valid": True,
        "source_revision": "s1",
        "graph_revision": "g1",
        "anchors": (
            {
                "path": "src/greeter.py",
                "line": 7,
                "symbol": "greet",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
        ),
        "definitions": (
            {
                "path": "src/greeter.py",
                "line": 7,
                "symbol": "greet",
                "signature": "def greet(name: str) -> str",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
            },
        ),
        "references": (),
        "callers": (),
    }

    decision = compile_incremental_frontier(
        evidence,
        [{"role": "user", "content": "Change greet."}],
        source_revision="s1",
        max_chars=1,
    )

    assert decision.disposition is FrontierDisposition.FRONTIER_BUDGET
    assert decision.rendered == ""
    assert decision.candidate_count == decision.accounted_count == 1
    assert decision.accounting[0]["disposition"] == "frontier_budget"


def test_stale_repository_revision_is_rejected_before_delivery():
    decision = compile_incremental_frontier(
        {
            "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
            "available": True,
            "substrate_ready": True,
            "index_current": True,
            "intelligence_valid": True,
            "graph_revision": "g1",
            "source_revision": "s1",
        },
        [{"role": "user", "content": "Fix it"}],
        source_revision="s2",
    )

    assert decision.disposition is FrontierDisposition.STALE_SOURCE_REVISION
    assert decision.rendered == ""


def test_frontier_claim_identity_is_stable_across_source_revisions():
    def evidence(revision: str):
        return {
            "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
            "available": True,
            "substrate_ready": True,
            "index_current": True,
            "intelligence_valid": True,
            "source_revision": revision,
            "graph_revision": f"g-{revision}",
            "anchors": (
                {
                    "path": "src/greeter.py",
                    "line": 7,
                    "symbol": "greet",
                    "retrieval_relevance": 1.0,
                    "semantic_certainty": 1.0,
                },
            ),
            "definitions": (
                {
                    "path": "src/greeter.py",
                    "line": 7,
                    "symbol": "greet",
                    "signature": "def greet(name: str) -> str",
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                },
            ),
        }

    first = compile_incremental_frontier(
        evidence("s1"), [{"role": "user", "content": "Fix `greet`."}], source_revision="s1"
    )
    second = compile_incremental_frontier(
        evidence("s2"),
        [{"role": "user", "content": "Fix `greet`."}],
        source_revision="s2",
        delivered_claim_ids=frozenset({first.facts[0].claim_id}),
    )

    assert first.facts[0].claim_id
    assert second.disposition is FrontierDisposition.REPRESENTED_MESSAGE
    assert second.accounting[0]["claim_id"] == first.facts[0].claim_id


def test_frontier_claim_identity_is_stable_when_only_line_moves():
    def evidence(line: int):
        return {
            "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
            "available": True,
            "substrate_ready": True,
            "index_current": True,
            "intelligence_valid": True,
            "source_revision": "s1",
            "graph_revision": f"g-{line}",
            "anchors": (
                {
                    "path": "src/module.c",
                    "line": line,
                    "symbol": "PyModuleDef",
                    "retrieval_relevance": 1.0,
                    "semantic_certainty": 1.0,
                },
            ),
            "definitions": (
                {
                    "path": "src/module.c",
                    "line": line,
                    "symbol": "PyModuleDef",
                    "signature": "static struct PyModuleDef module_def",
                    "semantic_certainty": 1.0,
                    "retrieval_relevance": 1.0,
                },
            ),
        }

    messages = [
        {"role": "user", "content": "Update src/module.c."},
        {
            "role": "assistant",
            "content": "",
            "extra": {"actions": [{"command": "sed -n '1,80p' src/module.c"}]},
        },
        {"role": "tool", "content": "source opened"},
    ]
    first = compile_incremental_frontier(evidence(20), messages, source_revision="s1")
    second = compile_incremental_frontier(
        evidence(41),
        messages,
        source_revision="s1",
        delivered_claim_ids=frozenset({first.accounting[0]["claim_id"]}),
    )

    assert second.disposition is FrontierDisposition.REPRESENTED_MESSAGE
    assert second.accounting[0]["claim_id"] == first.accounting[0]["claim_id"]


def test_frontier_abstains_from_generic_task_start_symbol_match():
    evidence = {
        "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
        "available": True,
        "substrate_ready": True,
        "index_current": True,
        "intelligence_valid": True,
        "source_revision": "s1",
        "graph_revision": "g1",
        "anchors": (
            {
                "path": "interpreter.py",
                "line": 14,
                "symbol": "Pair",
                "surface": "nodes_fts",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 1.0,
                "relevance_reason_codes": ["exact_distinctive_subject"],
            },
        ),
        "definitions": (),
        "references": (),
        "callers": (),
    }

    decision = compile_incremental_frontier(
        evidence,
        [{"role": "user", "content": "Implement a Scheme evaluator with pairs."}],
        source_revision="s1",
    )

    assert decision.rendered == ""
    assert decision.disposition is FrontierDisposition.LOW_PRECISION
    assert decision.accounting[0]["disposition"] == "no_decision_anchor"


def test_frontier_rejects_out_of_range_relevance_instead_of_delivering():
    evidence = {
        "status": RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
        "available": True,
        "substrate_ready": True,
        "index_current": True,
        "intelligence_valid": True,
        "source_revision": "s1",
        "graph_revision": "g1",
        "anchors": (
            {
                "path": "bottle.py",
                "line": 10,
                "symbol": "app",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 3.5,
            },
        ),
        "definitions": (
            {
                "path": "bottle.py",
                "line": 10,
                "symbol": "app",
                "signature": "def app(self):",
                "semantic_certainty": 1.0,
                "retrieval_relevance": 3.5,
            },
        ),
    }

    decision = compile_incremental_frontier(
        evidence, [{"role": "user", "content": "Fix header validation."}], source_revision="s1"
    )

    assert decision.disposition is FrontierDisposition.LOW_PRECISION
    assert decision.accounting[0]["disposition"] == "invalid_relevance"
