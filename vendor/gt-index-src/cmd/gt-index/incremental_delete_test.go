package main

import (
	"database/sql"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"

	_ "github.com/mattn/go-sqlite3"
)

// A deleted file is an edit like any other and the graph has to follow it.
//
// runIncremental used to error on a missing file, which forced the caller into
// a full rebuild. On the 2026-09-08 arktype run that was FIVE of eleven
// rebuilds -- the single largest cause -- because the agent repeatedly created
// scratch test files and removed them. A rename presents identically (delete of
// the old path, create of the new), so refusing also refused half of every
// rename.
//
// What must hold is that the deletion is SCOPED: the deleted file's nodes,
// edges, symbols and file_hashes row go, and nothing else moves. That is the
// same property the amend has, and the same one whose absence once discarded
// 177,390 of 181,200 nodes.
func TestIncrementalDeleteRemovesOnlyTheDeletedFile(t *testing.T) {
	if testing.Short() {
		t.Skip("builds the gt-index binary; skipped under -short")
	}

	tmp := t.TempDir()
	repo := filepath.Join(tmp, "repo")
	if err := os.MkdirAll(filepath.Join(repo, "pkg"), 0o755); err != nil {
		t.Fatal(err)
	}
	keepRel := "pkg/keep.py"
	dropRel := "pkg/drop.py"
	if err := os.WriteFile(filepath.Join(repo, keepRel),
		[]byte("def kept_one():\n    return 1\n\n\ndef kept_two():\n    return 2\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repo, dropRel),
		[]byte("def doomed():\n    return 3\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	bin := filepath.Join(tmp, "gt-index")
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}
	build := exec.Command("go", "build", "-tags", "sqlite_fts5", "-ldflags", testBuildLDFlags, "-o", bin, ".")
	build.Env = append(os.Environ(), "CGO_ENABLED=1")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build gt-index: %v\n%s", err, out)
	}

	dbPath := filepath.Join(tmp, "graph.db")
	if out, err := exec.Command(bin, "-root", repo, "-output", dbPath).CombinedOutput(); err != nil {
		t.Fatalf("full index: %v\n%s", err, out)
	}

	keptBefore := countRows(t, dbPath, "nodes WHERE file_path = '"+keepRel+"'")
	droppedBefore := countRows(t, dbPath, "nodes WHERE file_path = '"+dropRel+"'")
	if keptBefore == 0 || droppedBefore == 0 {
		t.Fatalf("fixture invalid: kept=%d dropped=%d", keptBefore, droppedBefore)
	}

	// Delete the file, then reindex that path.
	if err := os.Remove(filepath.Join(repo, dropRel)); err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command(bin, "-root", repo, "-output", dbPath, "-file", dropRel).CombinedOutput()
	if err != nil {
		t.Fatalf("incremental delete: %v\n%s", err, out)
	}

	if got := countRows(t, dbPath, "nodes WHERE file_path = '"+dropRel+"'"); got != 0 {
		t.Fatalf("deleted file still has %d nodes", got)
	}
	if got := countRows(t, dbPath, "nodes WHERE file_path = '"+keepRel+"'"); got != keptBefore {
		t.Fatalf("deletion disturbed an untouched file: kept %d -> %d", keptBefore, got)
	}
	if got := countRows(t, dbPath, "resolution_symbols WHERE path = '"+dropRel+"'"); got != 0 {
		t.Fatalf("deleted file still has %d resolution_symbols rows", got)
	}
	if got := countRows(t, dbPath, "resolution_symbols WHERE path = '"+keepRel+"'"); got == 0 {
		t.Fatal("deletion cleared the surviving file's symbol identity")
	}
	if got := countRows(t, dbPath, "file_hashes WHERE file_path = '"+dropRel+"'"); got != 0 {
		t.Fatal("deleted file kept its file_hashes row; a later full index would " +
			"believe it was still indexed at that content")
	}
	if got := countRows(t, dbPath, "edges WHERE source_file = '"+dropRel+"'"); got != 0 {
		t.Fatalf("deleted file still has %d outgoing edges", got)
	}

	// Fail-closed authority, exactly as the amend leaves it.
	assertGraphResolutionIncomplete(t, dbPath)

	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var dangling int
	if err := db.QueryRow(
		`SELECT count(*) FROM resolution_symbols rs
		  WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE CAST(n.id AS TEXT) = rs.native_id)`,
	).Scan(&dangling); err != nil {
		t.Fatal(err)
	}
	if dangling != 0 {
		t.Fatalf("deletion left %d resolution_symbols rows pointing at missing nodes", dangling)
	}
}
