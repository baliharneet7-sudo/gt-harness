package resolver

import (
	"testing"

	"github.com/harneet2512/groundtruth/gt-index/internal/parser"
)

func TestBuildImportIndexDoesNotSuffixMatchExternalRustCrate(t *testing.T) {
	imports := []parser.ImportRef{{
		ImportedName: "Command",
		ModulePath:   "std::process",
		File:         "build.rs",
		Line:         1,
	}}
	fileMap := map[string][]string{
		"process": {"src/process.rs"},
	}

	index := buildImportIndex(imports, fileMap)

	if targets := index["build.rs"]["Command"]; len(targets) != 0 {
		t.Fatalf("external Rust import must abstain, got %v", targets)
	}
}

func TestBuildImportIndexKeepsExactWorkspaceRustCrate(t *testing.T) {
	imports := []parser.ImportRef{{
		ImportedName: "Router",
		ModulePath:   "workspace_core::routing",
		File:         "src/lib.rs",
		Line:         1,
	}}
	fileMap := map[string][]string{
		"workspace_core::routing": {"workspace-core/src/routing.rs"},
	}

	index := buildImportIndex(imports, fileMap)

	targets := index["src/lib.rs"]["Router"]
	if len(targets) != 1 || targets[0] != "workspace-core/src/routing.rs" {
		t.Fatalf("exact workspace import lost: %v", targets)
	}
}
