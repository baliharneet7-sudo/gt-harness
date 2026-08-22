import os
import sqlite3

from gt_engine.graph_context import graph_revision
from gt_engine.graph_identity import stable_symbol_id


def test_graph_revision_reads_logical_post_revision_not_file_metadata(tmp_path) -> None:
    graph = tmp_path / "graph.db"
    connection = sqlite3.connect(graph)
    connection.execute("CREATE TABLE project_meta(key TEXT PRIMARY KEY,value TEXT)")
    connection.execute("INSERT INTO project_meta VALUES ('post_revision', ?)", ("a" * 64,))
    connection.commit()
    connection.close()

    before = graph_revision(str(graph))
    stat = graph.stat()
    os.utime(graph, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert before == "a" * 64
    assert graph_revision(str(graph)) == before


def test_stable_symbol_identity_is_independent_of_database_row_order() -> None:
    fields = {
        "language": "python",
        "file_path": "src/service.py",
        "qualified_name": "service.save_user",
        "kind": "Function",
        "signature": "def save_user(user: User) -> None",
    }

    first = stable_symbol_id(**fields)
    unrelated = stable_symbol_id(
        language="python",
        file_path="src/unrelated.py",
        qualified_name="unrelated.work",
        kind="Function",
        signature="def work() -> None",
    )
    rebuilt = stable_symbol_id(**fields)

    assert first.startswith("gt-symbol-")
    assert first == rebuilt
    assert first != unrelated
