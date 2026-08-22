// Package walker discovers source files in a directory tree.
package walker

import (
	"bufio"
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"github.com/harneet2512/groundtruth/gt-index/internal/specs"
)

// skipDirs are directories to always skip.
var skipDirs = map[string]bool{
	".git":          true,
	".gt":           true,
	".groundtruth":  true,
	".hg":           true,
	".idea":         true,
	".pytest_cache": true,
	".ruff_cache":   true,
	".svn":          true,
	".vscode":       true,
	"__pycache__":   true,
	"node_modules":  true,
	".tox":          true,
	".eggs":         true,
	".venv":         true,
	"venv":          true,
	".mypy_cache":   true,
	"dist":          true,
	"build":         true,
	".next":         true,
	"target":        true, // Rust/Java build output
}

// SkipRecord explains why a repository file was not offered to the parser.
// Path is always slash-normalized and relative to the repository root.
type SkipRecord struct {
	Path   string `json:"path"`
	Reason string `json:"reason"`
}

// SourceFile represents a discovered source file.
type SourceFile struct {
	Path             string // relative path from root
	AbsPath          string
	Language         string
	Spec             *specs.Spec
	ResolutionReason string
}

// WalkResult contains discovered files and metadata about the walk.
type WalkResult struct {
	Files              []SourceFile
	FilesDiscovered    int
	FilesSkipped       int // number of eligible files beyond maxFiles
	Skipped            []SkipRecord
	SkippedDirectories []SkipRecord
	DiscoveryMethod    string
}

// Walk discovers all source files under root that have a registered language spec.
// Respects .gitignore patterns (basic implementation).
func Walk(root string, maxFiles int) ([]SourceFile, error) {
	result, err := WalkWithMeta(root, maxFiles)
	return result.Files, err
}

// WalkWithMeta is like Walk but also returns a complete discovery receipt.
// Git repositories use git's tracked plus non-ignored working-tree file set so
// nested .gitignore rules and negations are authoritative. Non-Git directories
// use a deterministic filesystem fallback with the legacy root ignore matcher.
func WalkWithMeta(root string, maxFiles int) (WalkResult, error) {
	root, _ = filepath.Abs(root)

	relPaths, method, skippedDirs, err := repositoryFiles(root)
	if err != nil {
		return WalkResult{}, err
	}
	result := WalkResult{
		FilesDiscovered:    len(relPaths),
		SkippedDirectories: skippedDirs,
		DiscoveryMethod:    method,
	}
	for _, relPath := range relPaths {
		path := filepath.Join(root, filepath.FromSlash(relPath))
		info, statErr := os.Stat(path)
		if statErr != nil {
			reason := "metadata_access_failed"
			if os.IsNotExist(statErr) {
				reason = "working_tree_deleted"
			}
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: reason})
			continue
		}
		if !info.Mode().IsRegular() {
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "non_regular_file"})
			continue
		}
		if !specs.HasCandidatePath(path) {
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "unsupported_path"})
			continue
		}
		if info.Size() > 500*1024 {
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "too_large"})
			continue
		}
		var prefix []byte
		if specs.ResolutionNeedsContent(path) {
			prefix, err = readPrefix(path, 65536)
			if err != nil {
				result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "content_read_failed"})
				continue
			}
		}
		spec, resolutionReason := specs.ResolveSource(path, prefix)
		if spec == nil {
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "language_unresolved"})
			continue
		}
		if isGeneratedFile(path) {
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "generated"})
			continue
		}
		if maxFiles > 0 && len(result.Files) >= maxFiles {
			result.FilesSkipped++
			result.Skipped = append(result.Skipped, SkipRecord{Path: relPath, Reason: "max_files"})
			continue
		}
		result.Files = append(result.Files, SourceFile{
			Path:             relPath,
			AbsPath:          path,
			Language:         spec.Name,
			Spec:             spec,
			ResolutionReason: resolutionReason,
		})
	}
	sort.Slice(result.Skipped, func(i, j int) bool {
		if result.Skipped[i].Path == result.Skipped[j].Path {
			return result.Skipped[i].Reason < result.Skipped[j].Reason
		}
		return result.Skipped[i].Path < result.Skipped[j].Path
	})
	return result, nil
}

func repositoryFiles(root string) ([]string, string, []SkipRecord, error) {
	command := exec.Command("git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
	if output, err := command.Output(); err == nil {
		seen := make(map[string]bool)
		var paths []string
		var skippedDirs []SkipRecord
		for _, raw := range bytes.Split(output, []byte{0}) {
			if len(raw) == 0 {
				continue
			}
			relPath := filepath.ToSlash(string(raw))
			if directory := skippedDirectory(relPath); directory != "" {
				skippedDirs = append(skippedDirs, SkipRecord{Path: relPath, Reason: "excluded_directory:" + directory})
				continue
			}
			if !seen[relPath] {
				seen[relPath] = true
				paths = append(paths, relPath)
			}
		}
		sort.Strings(paths)
		sort.Slice(skippedDirs, func(i, j int) bool { return skippedDirs[i].Path < skippedDirs[j].Path })
		return paths, "git_ls_files", skippedDirs, nil
	}

	ignorePatterns := loadGitignore(filepath.Join(root, ".gitignore"))
	var paths []string
	var skippedDirs []SkipRecord
	err := filepath.Walk(root, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if info.IsDir() {
			if path != root && skipDirs[filepath.Base(path)] {
				relPath, _ := filepath.Rel(root, path)
				skippedDirs = append(skippedDirs, SkipRecord{Path: filepath.ToSlash(relPath), Reason: "excluded_directory:" + filepath.Base(path)})
				return filepath.SkipDir
			}
			return nil
		}
		relPath, relErr := filepath.Rel(root, path)
		if relErr != nil {
			return relErr
		}
		relPath = filepath.ToSlash(relPath)
		if isIgnored(relPath, ignorePatterns) {
			return nil
		}
		paths = append(paths, relPath)
		return nil
	})
	sort.Strings(paths)
	return paths, "filesystem_fallback", skippedDirs, err
}

func skippedDirectory(relPath string) string {
	parts := strings.Split(filepath.ToSlash(relPath), "/")
	for index, part := range parts {
		if index == len(parts)-1 {
			break
		}
		if skipDirs[part] {
			return part
		}
	}
	return ""
}

func readPrefix(path string, limit int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return io.ReadAll(io.LimitReader(file, limit))
}

// isGeneratedFile checks the first line of a file for common codegen markers.
func isGeneratedFile(path string) bool {
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	// Check first 3 lines for generated markers
	for i := 0; i < 3 && scanner.Scan(); i++ {
		line := scanner.Text()
		if strings.Contains(line, "Code generated") ||
			strings.Contains(line, "Generated by") ||
			strings.Contains(line, "DO NOT EDIT") ||
			strings.Contains(line, "AUTO-GENERATED") ||
			strings.Contains(line, "auto-generated") {
			return true
		}
	}
	return false
}

func loadGitignore(path string) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	var patterns []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		patterns = append(patterns, line)
	}
	return patterns
}

func isIgnored(relPath string, patterns []string) bool {
	base := filepath.Base(relPath)
	ignored := false
	for _, p := range patterns {
		// Gitignore negation: !pattern unignores a previously ignored file.
		// The last matching rule wins (git semantics).
		negate := false
		pat := p
		if strings.HasPrefix(p, "!") {
			negate = true
			pat = p[1:]
		}
		matched := false
		// Glob matching against basename
		if m, _ := filepath.Match(pat, base); m {
			matched = true
		}
		if !matched {
			// Directory-level matching
			if strings.Contains(pat, "/") {
				if m, _ := filepath.Match(pat, relPath); m {
					matched = true
				}
			} else {
				dirPart := "/" + filepath.ToSlash(relPath) + "/"
				if strings.Contains(dirPart, "/"+pat+"/") {
					matched = true
				}
			}
		}
		if matched {
			ignored = !negate
		}
	}
	return ignored
}

// IsTestFile checks if a file path is a test file based on conventions.
func IsTestFile(relPath string) bool {
	base := filepath.Base(relPath)
	dir := filepath.ToSlash(filepath.Dir(relPath))
	ext := filepath.Ext(base)
	stem := strings.TrimSuffix(base, ext)

	// Python: test_*.py, *_test.py
	if strings.HasPrefix(base, "test_") || strings.HasSuffix(stem, "_test") {
		return true
	}
	// Python pytest/Django FILES the test_/_test rules miss (Fable 2026-07-03 leak: their
	// bodies carry fixtures/assertions/graded-test names — indexing them bakes test text
	// into graph.db + the content surface). conftest.py (fixtures), tests.py & test.py
	// (Django app-level test modules), *_tests.py (plural). Root fix so is_test is right
	// for EVERY consumer (content FTS, BFS neighbor, witness render), not per-consumer.
	if ext == ".py" && (base == "conftest.py" || base == "tests.py" || base == "test.py" ||
		strings.HasSuffix(stem, "_tests")) {
		return true
	}
	// Go: *_test.go
	if strings.HasSuffix(base, "_test.go") {
		return true
	}
	// JS/TS: *.test.js, *.spec.js, *.test.ts, *.spec.ts (+ plural .tests./.specs.)
	if strings.Contains(base, ".test.") || strings.Contains(base, ".spec.") ||
		strings.Contains(base, ".tests.") || strings.Contains(base, ".specs.") {
		return true
	}
	// JVM (Java/Kotlin/Scala/Groovy): *Test.java, *Tests.java, *Test.kt, etc.
	if strings.HasSuffix(stem, "Test") || strings.HasSuffix(stem, "Tests") || strings.HasSuffix(stem, "Spec") {
		switch ext {
		case ".java", ".kt", ".kts", ".scala", ".groovy":
			return true
		}
	}
	// C#: *Test.cs, *Tests.cs
	if (strings.HasSuffix(stem, "Test") || strings.HasSuffix(stem, "Tests")) && ext == ".cs" {
		return true
	}
	// PHP: *Test.php (PHPUnit convention)
	if strings.HasSuffix(stem, "Test") && ext == ".php" {
		return true
	}
	// Swift: *Tests.swift
	if (strings.HasSuffix(stem, "Tests") || strings.HasSuffix(stem, "Test")) && ext == ".swift" {
		return true
	}
	// Ruby: *_spec.rb (RSpec convention)
	if strings.HasSuffix(stem, "_spec") && ext == ".rb" {
		return true
	}
	// Rust: tests.rs / test.rs (inline test module files), *_test.rs, *_tests.rs
	// These are Rust files that ARE test modules but live inside source dirs, so
	// directory-segment matching alone won't catch them.
	if ext == ".rs" {
		if base == "tests.rs" || base == "test.rs" {
			return true
		}
		if strings.HasSuffix(stem, "_test") || strings.HasSuffix(stem, "_tests") {
			return true
		}
	}
	// C/C++: *_test.cc, *_test.cpp, *_test.cxx (Google Test / CTest convention)
	if strings.HasSuffix(stem, "_test") {
		switch ext {
		case ".cc", ".cpp", ".cxx", ".c":
			return true
		}
	}
	// Directory-based: tests/, test/, spec/, Jest __tests__/, and underscore-
	// wrapped variants (csstree __tests/, __test__/) — common in JS/TS repos.
	// Whole-segment matching (after trimming wrapping underscores) avoids false
	// positives like "contests/" or "attestations/".
	if hasTestDirSegment(dir) {
		return true
	}
	// JVM convention: src/test/ directory
	if strings.Contains(dir, "src/test/") {
		return true
	}
	// Any path that IsNonSourceFile classifies as non-source (e.g. fuzz/, fuzzing/,
	// fuzz_targets/, corpus/, integration_tests/, e2e_tests/, as well as demo/example/
	// docs/vendor dirs already in hasTestDirSegment or nonSourceDirSegments) should also be
	// flagged by IsTestFile so that the is_test bit is set regardless of which predicate is
	// the entry point.
	if IsNonSourceFile(relPath) {
		return true
	}
	return false
}

// IsTestByStructure reports whether a path is test-classified by a RELIABLE STRUCTURAL
// signal — a test-directory segment (tests/, spec/, __tests__/), a JVM src/test/ tree, or
// a non-source directory (fuzz/, corpus/, examples/). Unlike the filename-convention
// predicates in IsTestFile (test_*, *_test, *Test, *_spec), these have NO production
// false-positive class: a file living under tests/ is test-associated regardless of its
// content. The parser corroborates NAME-only is_test flags against file content (a file
// must actually contain a collectable test unit) but trusts these structural flags as-is,
// so production test-infrastructure named like a test (base_test.py, AbstractFooTest) is
// not wrongly excluded from localization. See parser.ParseFile.
func IsTestByStructure(relPath string) bool {
	dir := filepath.ToSlash(filepath.Dir(relPath))
	if hasTestDirSegment(dir) {
		return true
	}
	if strings.Contains(dir, "src/test/") {
		return true
	}
	if IsNonSourceFile(relPath) {
		return true
	}
	return false
}

// hasTestDirSegment reports whether any path segment, after stripping wrapping
// underscores, names a test directory. This generalizes the common conventions
// — "tests/", "test/", "spec/", "specs/", Jest "__tests__/", and underscore-
// wrapped variants like "__tests/" (csstree) or "__test__/" — so JS/TS test
// files are flagged is_test and have their assertions extracted. Whole-segment
// matching (vs substring) still rejects false positives like "contests/".
func hasTestDirSegment(dir string) bool {
	for _, seg := range strings.Split(dir, "/") {
		switch strings.Trim(seg, "_") {
		case "test", "tests", "spec", "specs":
			return true
		}
	}
	return false
}

// nonSourceDirSegments is the union of test + demo/non-source directory names.
// A file under ANY of these (as a whole path segment) is NOT product source: its
// call edges must never enter the FACT surface (reach / localization / callers),
// because a benchmark/example/fixture caller of an internal symbol is a phantom
// caller — the dacite→mashumaro `from_dict` class of false fact (10,444 such edges
// measured live). This is the Go-indexer half of the same path policy; it MIRRORS
// src/groundtruth/delivery/path_policy.py (_TEST_DIR_SEGMENTS ∪
// _DEMO_NONSOURCE_DIR_SEGMENTS) so Go and Python classify a path identically. If
// you add a segment here, add it there too (DUPLICATION TRAP — the two copies
// drifting is exactly the leak path_policy.py warns about).
var nonSourceDirSegments = map[string]bool{
	// test dirs (superset of hasTestDirSegment; "e2e" is Python-side too)
	"test": true, "tests": true, "spec": true, "specs": true,
	"e2e": true,
	// fuzz / mutation / property-based test dirs (universal across all languages)
	// e.g. crates/fuzz/src/... (Rust), fuzz_targets/ (cargo-fuzz), corpus/ (AFL/libFuzzer),
	// testcases/ (AFL), integration_tests/ (Python pytest),
	// e2e_tests/ (end-to-end test dirs distinct from "e2e").
	// P11: `compat`, `conformance`, and `testing` were REMOVED — they are production-ambiguous
	// (pandas/compat, numpy/compat, protobuf conformance libs, Go `testing`-helper packages
	// are real source), so forcing is_test on them dropped production code out of the fact
	// surface. Only genuinely non-source dirs stay.
	"fuzz": true, "fuzzing": true, "fuzz_targets": true,
	"corpus": true, "testcases": true,
	"integration_tests": true, "e2e_tests": true,
	// demo / example
	"example": true, "examples": true, "demo": true, "demos": true,
	"sample": true, "samples": true,
	// fixtures / test data
	"testdata": true, "fixtures": true, "fixture": true,
	// docs
	"docs": true, "doc": true, "docs_src": true, "doc_src": true,
	"documentation": true, "tutorial": true, "tutorials": true,
	// benchmarks
	"benchmark": true, "benchmarks": true, "benches": true, "bench": true,
	// vendored / third-party / build output
	"vendor": true, "node_modules": true, "third_party": true,
	"dist": true, "build": true,
}

// IsNonSourceFile reports whether relPath lives under a non-source directory —
// test, demo/example, fixtures/testdata, docs, benchmark, or vendored/build dirs
// (see nonSourceDirSegments). Whole-segment, case-insensitive, underscore-trimmed
// match (so "benchmarking/"/"docstore/"/"sampler/" are NOT flagged — substring is
// never enough). Used to mark such nodes is_test so the resolver + consumer FACT
// filters exclude their call edges. Distinct from IsTestFile (which also keys off
// basename markers + extracts test assertions for the consistency pillar) — this
// one is DIRECTORY-only, purely for the fact-surface exclusion.
func IsNonSourceFile(relPath string) bool {
	p := strings.ToLower(filepath.ToSlash(relPath))
	for _, seg := range strings.Split(p, "/") {
		if nonSourceDirSegments[strings.Trim(seg, "_")] {
			return true
		}
	}
	return false
}
