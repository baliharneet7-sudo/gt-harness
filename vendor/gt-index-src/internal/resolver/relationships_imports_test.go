package resolver

import (
	"testing"

	"github.com/harneet2512/groundtruth/gt-index/internal/parser"
)

func TestBuildImportIndexResolvesPythonSiblingRelativeImport(t *testing.T) {
	imports := []parser.ImportRef{{
		File:         "src/pkg/child.py",
		ModulePath:   ".base",
		ImportedName: "Base",
	}}
	fileMap := map[string][]string{"src/pkg/base": {"src/pkg/base.py"}}

	got := buildImportIndex(imports, fileMap)
	targets := got["src/pkg/child.py"]["Base"]
	if len(targets) != 1 || targets[0] != "src/pkg/base.py" {
		t.Fatalf("sibling relative import targets = %#v, want src/pkg/base.py", targets)
	}
}

func TestBuildImportIndexResolvesPythonParentRelativeImport(t *testing.T) {
	imports := []parser.ImportRef{{
		File:         "src/pkg/nested/child.py",
		ModulePath:   "..base",
		ImportedName: "Base",
	}}
	fileMap := map[string][]string{"src/pkg/base": {"src/pkg/base.py"}}

	got := buildImportIndex(imports, fileMap)
	targets := got["src/pkg/nested/child.py"]["Base"]
	if len(targets) != 1 || targets[0] != "src/pkg/base.py" {
		t.Fatalf("parent relative import targets = %#v, want src/pkg/base.py", targets)
	}
}

func TestBuildParamNameIndexIncludesUntypedCallback(t *testing.T) {
	properties := []parser.PropertyRef{{
		NodeIdx: 0,
		Kind:    "param",
		Value:   "createStore [required]",
	}}

	got := BuildParamNameIndex(properties, []int64{41})
	if !got[41]["createStore"] {
		t.Fatalf("untyped callback parameter missing: %#v", got)
	}
}

func TestBuildCallableFieldIndexRequiresTypedBareClassDefault(t *testing.T) {
	properties := []parser.PropertyRef{
		{NodeIdx: 0, Kind: "class_field", Value: "signer: type[Signer] = Signer"},
		{NodeIdx: 0, Kind: "class_field", Value: "other = Signer"},
		{NodeIdx: 0, Kind: "class_field", Value: "built: type[Signer] = Signer()"},
	}

	got := BuildCallableFieldIndex(properties, []int64{51}, nil)
	if got[51]["signer"] != "Signer" {
		t.Fatalf("callable class field missing: %#v", got)
	}
	if len(got[51]) != 1 {
		t.Fatalf("unsafe callable fields accepted: %#v", got)
	}
}

func TestBuildCallableFieldIndexUsesTypedInstanceAssignment(t *testing.T) {
	properties := []parser.PropertyRef{{
		NodeIdx: 0,
		Kind:    "data_flow",
		Value:   "signer -> signer is None | self.signer: type[Signer] = signer",
	}}
	meta := map[int64]NodeMeta{61: {Label: "Method", ParentID: 51, Name: "__init__"}}

	got := BuildCallableFieldIndex(properties, []int64{61}, meta)
	if got[51]["signer"] != "Signer" {
		t.Fatalf("typed instance callable field missing: %#v", got)
	}
}

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
