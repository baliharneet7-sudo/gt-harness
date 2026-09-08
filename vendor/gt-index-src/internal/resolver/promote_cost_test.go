package resolver

import (
	"os"
	"testing"
	"time"

	"github.com/harneet2512/groundtruth/gt-index/internal/store"
)

// Where does the per-file amend actually spend its time?
//
// runIncremental calls PromotePropertyEdges whole-graph after every single-file
// amend, and the pass's own registration note names a file-scoped variant as the
// pending optimisation. Before scoping it, measure it: on the 2026-09-08 run a
// one-file amend cost ~20s of producer time and that number is what forces
// INCREMENTAL_MAX_DIRTY_PATHS down to 3.
//
// Point GT_PROMOTE_COST_GRAPH at a real graph.db to run. Skipped otherwise, so
// this never blocks a normal suite.
func TestPromoteCostBreakdown(t *testing.T) {
	path := os.Getenv("GT_PROMOTE_COST_GRAPH")
	if path == "" {
		t.Skip("set GT_PROMOTE_COST_GRAPH to a real graph.db to measure")
	}
	db, err := store.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	started := time.Now()
	if err := deletePromotedEdges(db); err != nil {
		t.Fatalf("delete promoted edges: %v", err)
	}
	deleteFor := time.Since(started)

	started = time.Now()
	idx, err := buildPromoteIndexes(db)
	if err != nil {
		t.Fatalf("build indexes: %v", err)
	}
	indexFor := time.Since(started)

	started = time.Now()
	emitted, err := PromotePropertyEdges(db)
	if err != nil {
		t.Fatalf("promote: %v", err)
	}
	wholeFor := time.Since(started)

	t.Logf("nodes indexed          %d", len(idx.byID))
	t.Logf("edges emitted          %d", emitted)
	t.Logf("deletePromotedEdges    %.1fs", deleteFor.Seconds())
	t.Logf("buildPromoteIndexes    %.1fs", indexFor.Seconds())
	t.Logf("PromotePropertyEdges   %.1fs  (delete + index + emit + insert)", wholeFor.Seconds())
	t.Logf("emit+insert remainder  %.1fs", (wholeFor - deleteFor - indexFor).Seconds())
}
