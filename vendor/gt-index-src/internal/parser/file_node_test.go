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
