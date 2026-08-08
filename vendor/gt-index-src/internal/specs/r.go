package specs

import (
	tree_sitter_r "github.com/r-lib/tree-sitter-r/bindings/go"
	sitter "github.com/smacker/go-tree-sitter"
)

// R is a validation-relevant Terminal-Bench language.  The upstream grammar
// exposes assignment-bound functions as function_definition nodes with a
// concrete name field, so this mapping can remain structural rather than
// falling back to text heuristics.
func init() {
	Register(&Spec{
		Name:          "r",
		Extensions:    []string{".r"},
		Language:      sitter.NewLanguage(tree_sitter_r.Language()),
		FunctionNodes: []string{"function_definition"},
		CallNodes:     []string{"call"},
		ImportNodes:   []string{"namespace_definition", "library_call"},
		NameField:     "name",
		BodyField:     "body",
		ParamsField:   "parameters",
		IsExported: func(name string) bool {
			return name != "" && name[0] != "."
		},
	})
}
