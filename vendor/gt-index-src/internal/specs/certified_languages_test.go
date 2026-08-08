package specs

import (
	"strings"
	"testing"

	sitter "github.com/smacker/go-tree-sitter"
)

func parseCertified(t *testing.T, spec *Spec, source string) string {
	t.Helper()
	if spec == nil || spec.Language == nil {
		t.Fatalf("language spec is not registered")
	}
	p := sitter.NewParser()
	t.Cleanup(p.Close)
	p.SetLanguage(spec.Language)
	tree := p.Parse(nil, []byte(source))
	t.Cleanup(tree.Close)
	return tree.RootNode().String()
}

func TestCertifiedCobolGrammarEmitsProceduresAndPerform(t *testing.T) {
	tree := parseCertified(t, ForExtension(".cbl"),
		"       IDENTIFICATION DIVISION.\n"+
			"       PROGRAM-ID. FIXTURE.\n"+
			"       PROCEDURE DIVISION.\n"+
			"       MAIN-PARA.\n"+
			"           PERFORM HELPER-PARA.\n"+
			"       HELPER-PARA.\n"+
			"           STOP RUN.\n")
	for _, nodeType := range []string{"program_definition", "procedure_division", "paragraph_header", "perform_statement_call_proc"} {
		if !strings.Contains(tree, nodeType) {
			t.Fatalf("COBOL tree missing %q: %s", nodeType, tree)
		}
	}
}

func TestCertifiedSchemeGrammarEmitsDefinitionsAndCalls(t *testing.T) {
	tree := parseCertified(t, ForExtension(".scm"),
		"(define (target value) (+ value 1))\n"+
			"(define (caller) (target 1))\n")
	for _, nodeType := range []string{"binding_procedure", "procedure_call"} {
		if !strings.Contains(tree, nodeType) {
			t.Fatalf("Scheme tree missing %q: %s", nodeType, tree)
		}
	}
}

