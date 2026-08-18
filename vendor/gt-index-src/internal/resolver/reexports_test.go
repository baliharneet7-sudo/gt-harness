package resolver

import (
	"testing"

	"github.com/harneet2512/groundtruth/gt-index/internal/parser"
)

func TestResolveReExportTargetsAbstainsOnAmbiguousModule(t *testing.T) {
	reference := parser.ReExportRef{
		File:         "pkg/__init__.py",
		SourceModule: ".mod",
	}
	fileMap := map[string][]string{
		"pkg/mod.py": {"pkg/mod.py", "generated/pkg/mod.py"},
	}

	if targets := resolveReExportTargets(reference, fileMap); len(targets) != 0 {
		t.Fatalf("ambiguous re-export must abstain, got %v", targets)
	}
}

func TestResolveReExportTargetsKeepsUniqueModule(t *testing.T) {
	reference := parser.ReExportRef{
		File:         "pkg/__init__.py",
		SourceModule: ".mod",
	}
	fileMap := map[string][]string{
		"pkg/mod.py": {"pkg/mod.py"},
	}

	targets := resolveReExportTargets(reference, fileMap)
	if len(targets) != 1 || targets[0] != "pkg/mod.py" {
		t.Fatalf("unique re-export target lost: %v", targets)
	}
}
