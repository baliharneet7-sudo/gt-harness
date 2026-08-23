# Graph Truth Audit

Observed: `2026-08-23T03:57:30.423756Z`

Receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\graph-truth.json`

Verdict: **PASS**

Expected facts were derived from frozen repository source by the independent oracles in `scripts/graph_truth_audit.py`; GT output was used only as the system under test.

| Metric | Value |
| --- | ---: |
| facts | 11 |
| true_positives | 62 |
| false_positives | 0 |
| false_negatives | 0 |
| precision | 1.0 |
| recall | 1.0 |
| false_positive_rate | 0.0 |
| false_negative_rate | 0.0 |
| unsupported_rate | 0.0 |
| wrong_file_rate | 0.0 |
| wrong_symbol_rate | 0.0 |
| exact_set_accuracy | 1.0 |
| stale_edge_rate | NOT_MEASURED_IN_STATIC_TRUTH_CORPUS |

## Fact results

| Fact | Language | Relationship | Result | TP | FP | FN | Latency ms |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| python-direct-subclasses-baddata | python | subclasses | PASS | 2 | 0 | 0 | 5.719 |
| python-in-repository-callees-base64-encode | python | callees | PASS | 1 | 0 | 0 | 5.632 |
| javascript-relative-requires-express-entry | javascript | imports | PASS | 3 | 0 | 0 | 7.737 |
| javascript-commonjs-local-reexports | javascript | reexports | PASS | 5 | 0 | 0 | 7.921 |
| typescript-redux-type-barrel | typescript | reexports | PASS | 22 | 0 | 0 | 9.975 |
| typescript-external-react-component-abstention | javascript | subclasses | PASS | 0 | 0 | 0 | 9.491 |
| go-clean-import-path-caller | go | callers | PASS | 1 | 0 | 0 | 6.728 |
| rust-cli-crate-reexports | rust | reexports | PASS | 25 | 0 | 0 | 8.213 |
| rust-stdlib-import-abstention | rust | imports | PASS | 0 | 0 | 0 | 7.920 |
| java-direct-subclasses-billing-instrument | java | subclasses | PASS | 2 | 0 | 0 | 9.806 |
| java-in-file-callees-utc-format | java | callees | PASS | 1 | 0 | 0 | 9.650 |

## Scope

This is a bounded, reproducible real-repository sample, not a claim of universal graph accuracy. A separate adversarial competitor question set found additional caller-resolution errors that this 11-fact corpus did not exercise; those defects were repaired before this final receipt. The competitive set is reported separately and is not folded into the 62/62 claim. Stale-edge behavior is deferred to the lifecycle campaign.

Reproduce (PowerShell):

```powershell
python scripts/graph_truth_audit.py --workspace D:\gt-product-audit-5296dc3 --output D:\gt-product-audit-5296dc3\receipts\graph-truth.json --report GRAPH_TRUTH_AUDIT.md
```
