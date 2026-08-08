package parser

import (
	"os"
	"testing"

	"github.com/harneet2512/groundtruth/gt-index/internal/walker"
)

func TestRedcodeAdapterEmitsLabelsAndControlFlow(t *testing.T) {
	path := t.TempDir() + "/fixture.red"
	source := ";redcode-94\nstart mov 0, 1\n      jmp start\n      end start\n"
	if err := os.WriteFile(path, []byte(source), 0o600); err != nil {
		t.Fatal(err)
	}
	result, err := ParseFile(walker.SourceFile{Path: "fixture.red", AbsPath: path, Language: "red"}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Nodes) != 1 || result.Nodes[0].Name != "start" {
		t.Fatalf("unexpected Redcode nodes: %+v", result.Nodes)
	}
	if len(result.Calls) != 1 || result.Calls[0].CalleeName != "start" {
		t.Fatalf("unexpected Redcode calls: %+v", result.Calls)
	}
}

func TestPOVRayAdapterEmitsMacroAndInvocation(t *testing.T) {
	path := t.TempDir() + "/fixture.pov"
	source := "#include \"shapes.inc\"\n#macro Thing()\nsphere { <0,0,0>, 1 }\n#end\nThing()\n"
	if err := os.WriteFile(path, []byte(source), 0o600); err != nil {
		t.Fatal(err)
	}
	result, err := ParseFile(walker.SourceFile{Path: "fixture.pov", AbsPath: path, Language: "povray"}, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Nodes) != 1 || result.Nodes[0].Name != "Thing" {
		t.Fatalf("unexpected POV-Ray nodes: %+v", result.Nodes)
	}
	if len(result.Imports) != 1 || result.Imports[0].ModulePath != "shapes.inc" {
		t.Fatalf("unexpected POV-Ray imports: %+v", result.Imports)
	}
	if len(result.Calls) != 1 || result.Calls[0].CalleeName != "Thing" {
		t.Fatalf("unexpected POV-Ray calls: %+v", result.Calls)
	}
}
