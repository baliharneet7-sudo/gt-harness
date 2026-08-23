# GroundTruth Language Support Audit

Observed: `2026-08-23T03:58:23.398687Z`

Verdict: **PASS for the six declared prerelease languages**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\language-lifecycle.json`

| Language | Real repository | Cold/warm | Add | Modify | Delete | Stale edges |
| --- | --- | --- | --- | --- | --- | ---: |
| python | python-small-itsdangerous | PASS | PASS | PASS | PASS | 0 |
| javascript | javascript-express | PASS | PASS | PASS | PASS | 0 |
| typescript | typescript-redux | PASS | PASS | PASS | PASS | 0 |
| go | go-gorilla-mux | PASS | PASS | PASS | PASS | 0 |
| rust | rust-ripgrep | PASS | PASS | PASS | PASS | 0 |
| java | java-gson | PASS | PASS | PASS | PASS | 0 |

The same production lifecycle was exercised for Python, JavaScript, TypeScript, Go, Rust, and Java. All edit paths used the correctness-first atomic full rebuild; file-keyed incremental optimization remains non-canonical.

The broader ten-repository construction matrix separately covers large Python, dynamic/re-export-heavy Python, TypeScript barrels and a monorepo, and multi-package Go. Languages outside these six are parser capabilities, not certified product support, until they receive the same real-repository truth and lifecycle audit.

Linux correctly classified repository symlinks as `non_regular_file`. This produces small platform count differences where Windows materializes symlinks as regular files (Pydantic 729 versus 730 attempted files; pnpm 4,246 versus 4,249), but the skipped paths are explicit and neither platform follows external graph authority.
