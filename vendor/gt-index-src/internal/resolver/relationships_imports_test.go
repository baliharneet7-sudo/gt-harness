package resolver

import "testing"

func TestImportedExternalBaseDoesNotBindUniqueLocalName(t *testing.T) {
	classes := map[string][]classNodeEntry{
		"Component": {{ID: 7, FilePath: "tests/types.ts"}},
	}
	declarations := map[string]map[string]bool{
		"src/App.ts": {"Component": true},
	}

	got := resolveClassNodeImportAware(
		"Component",
		"src/App.ts",
		classes,
		map[string]map[string][]string{},
		declarations,
	)

	if got != 0 {
		t.Fatalf("unresolved external base must abstain, got node %d", got)
	}
}

func TestImportedInternalBaseResolvesOnlyProvenTargetFile(t *testing.T) {
	classes := map[string][]classNodeEntry{
		"Component": {
			{ID: 7, FilePath: "tests/types.ts"},
			{ID: 9, FilePath: "src/Component.ts"},
		},
	}
	declarations := map[string]map[string]bool{
		"src/App.ts": {"Component": true},
	}
	imports := map[string]map[string][]string{
		"src/App.ts": {"Component": {"src/Component.ts"}},
	}

	got := resolveClassNodeImportAware(
		"Component", "src/App.ts", classes, imports, declarations,
	)

	if got != 9 {
		t.Fatalf("proven imported base = %d, want 9", got)
	}
}
