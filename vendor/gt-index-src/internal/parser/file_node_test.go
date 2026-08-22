package parser

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/harneet2512/groundtruth/gt-index/internal/specs"
	"github.com/harneet2512/groundtruth/gt-index/internal/walker"
)

func TestDeclarationFreeShellSourceGetsConcreteFileNode(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "start.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexec qemu-system-x86_64 -nographic\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "vm/start.sh",
		AbsPath:  path,
		Language: "bash",
		Spec:     specs.ForExtension(".sh"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Nodes) != 1 {
		t.Fatalf("declaration-free shell source must emit one file node: %+v", result.Nodes)
	}
	node := result.Nodes[0]
	if node.Label != "File" || node.FilePath != "vm/start.sh" || node.Name != "start" {
		t.Fatalf("unexpected file node: %+v", node)
	}
	if node.IsExported {
		t.Fatalf("generic command-only file node must be identity-only: %+v", node)
	}
}

func TestDeclaredSourceAlsoGetsConcreteFileNode(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "app.js")
	if err := os.WriteFile(path, []byte("function answer() { return 42; }\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "src/app.js",
		AbsPath:  path,
		Language: "javascript",
		Spec:     specs.ForExtension(".js"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	var fileNodes int
	for _, node := range result.Nodes {
		if node.Label == "File" {
			fileNodes++
			if node.QualifiedName != "src/app.js" {
				t.Fatalf("unexpected file anchor: %+v", node)
			}
		}
	}
	if fileNodes != 1 {
		t.Fatalf("declared source must have exactly one file anchor: %+v", result.Nodes)
	}
}

func TestCommonJSReExportKeepsLocalSourceSymbol(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "exports.js")
	source := []byte("function Router() {}\nexports.router = Router;\n")
	if err := os.WriteFile(path, source, 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "exports.js",
		AbsPath:  path,
		Language: "javascript",
		Spec:     specs.ForExtension(".js"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.ReExports) != 1 {
		t.Fatalf("re-export missing: %+v", result.ReExports)
	}
	reExport := result.ReExports[0]
	if reExport.ExportedName != "router" || reExport.SourceSymbol != "Router" || reExport.SourceModule != "" {
		t.Fatalf("unexpected CommonJS re-export identity: %+v", reExport)
	}
}

func TestTypeScriptTypeAliasIsIndexedAsDefinition(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "types.ts")
	if err := os.WriteFile(path, []byte("export type Reducer<S> = (state: S) => S\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "types.ts",
		AbsPath:  path,
		Language: "typescript",
		Spec:     specs.ForExtension(".ts"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Nodes) != 2 || result.Nodes[0].Name != "Reducer" || result.Nodes[1].Label != "File" {
		t.Fatalf("type alias plus file anchor missing: %+v", result.Nodes)
	}
}

func TestTypeScriptGenericInterfacesAndAliasesAreIndexed(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "store.ts")
	source := []byte(`export interface StoreCreator {
  <S, A>(reducer: Reducer<S, A>): Store<S, A>
}
export type StoreEnhancer<Ext extends {} = {}> = <NextExt extends {}>(
  next: StoreCreator
) => StoreCreator
export type StoreEnhancerStoreCreator<Ext extends {} = {}> = <S>(state: S) => S & Ext
`)
	if err := os.WriteFile(path, source, 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "store.ts",
		AbsPath:  path,
		Language: "typescript",
		Spec:     specs.ForExtension(".ts"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	seen := make(map[string]bool)
	for _, node := range result.Nodes {
		seen[node.Name] = true
	}
	for _, name := range []string{"StoreCreator", "StoreEnhancer", "StoreEnhancerStoreCreator"} {
		if !seen[name] {
			t.Fatalf("generic TypeScript definition %q missing: %+v", name, result.Nodes)
		}
	}
}

func TestCommentOnlyShellSourceDoesNotFabricateFileNode(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "notes.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n# documentation only\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "notes.sh",
		AbsPath:  path,
		Language: "bash",
		Spec:     specs.ForExtension(".sh"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Nodes) != 0 {
		t.Fatalf("comment-only source must not fabricate graph authority: %+v", result.Nodes)
	}
}

func TestMalformedDeclarationFreeShellSourceDoesNotGainAuthority(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "broken.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nif then\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	result, err := ParseFile(walker.SourceFile{
		Path:     "broken.sh",
		AbsPath:  path,
		Language: "bash",
		Spec:     specs.ForExtension(".sh"),
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Nodes) != 0 {
		t.Fatalf("malformed source must not gain graph authority: %+v", result.Nodes)
	}
}
