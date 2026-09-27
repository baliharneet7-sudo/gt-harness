# What the agent sees - GT attached tools on the oracle fixture

Verbatim tool output on `tests/canonical/fixtures/oracle`, whose correct answers are known by construction and asserted in `tests/canonical/test_feature_oracle.py`.

## F11 retrieval

`$ gt-query compute the tax on an order total`  (exit 0, 437 bytes)

```
[GT] query compute the tax on an order total
1 source (2):
  py/shop/pricing.py:10  total  (Function)
  py/shop/pricing.py:5  apply_tax  (Function)
2 related tests (2):
  py/tests/test_pricing.py:4  test_total  (Function)
  py/tests/test_pricing.py:8  test_apply_tax_inside_callback  (Function)
note: partial: name-level graph facts, verify by reading the code; omitted: source_unavailable:dense
next: gt-context <symbol> for the top hit
```

## F2/F4/F9/F12 symbol context

`$ gt-context apply_tax`  (exit 0, 484 bytes)

```
[GT] context apply_tax
callee_count: 1
callees (1):
  py/shop/pricing.py:7  round_money  [CERTIFIED]
caller_count: 2
callers (2):
  py/tests/test_pricing.py:9  test_apply_tax_inside_callback  [CERTIFIED]
  py/shop/pricing.py:14  total  [CERTIFIED]
definition: py/shop/pricing.py:5  apply_tax  (Function)
flows (1):
  total -> round_money
note: partial: name-level graph facts, verify by reading the code; omitted: certified_semantics:partial
next: gt-impact <symbol> before editing it
```

## F4 callers

`$ gt-callers round_money 2`  (exit 0, 359 bytes)

```
[GT] callers round_money 2
caller_count: 3
callers_by_depth 1 (1):
  py/shop/pricing.py:7  apply_tax  [CERTIFIED]
callers_by_depth 2 (2):
  py/tests/test_pricing.py:9  test_apply_tax_inside_callback  [CERTIFIED]
  py/shop/pricing.py:14  total  [CERTIFIED]
note: partial: name-level graph facts, verify by reading the code; omitted: certified_semantics:partial
```

## F3 references (call inside a test callback)

`$ gt-refs apply_tax`  (exit 0, 464 bytes)

```
[GT] references apply_tax
reference_count: 3
reference_count_by_type CALLS: 2
reference_count_by_type IMPORTS: 1
references_by_type CALLS (2):
  py/shop/pricing.py:14  total  [CERTIFIED]
  py/tests/test_pricing.py:9  test_apply_tax_inside_callback  [CERTIFIED]
references_by_type IMPORTS (1):
  py/tests/test_pricing.py:1  py/tests/test_pricing.py  [CERTIFIED]
note: partial: name-level graph facts, verify by reading the code; omitted: certified_semantics:partial
```

## F5/F6/F7 virtual dispatch

`$ gt-calls persist`  (exit 0, 312 bytes)

```
[GT] calls in persist
calls (1):
  py/shop/storage.py:17  save -> one of: Store.save (py/shop/storage.py:2); MemoryStore.save (py/shop/storage.py:7) [via inheritance]; FileStore.save (py/shop/storage.py:12) [via inheritance] [incomplete, virtual]
note: partial: name-level graph facts, verify by reading the code
```

## F5/F6 virtual dispatch (TS interface)

`$ gt-calls welcome`  (exit 0, 304 bytes)

```
[GT] calls in welcome
calls (1):
  ts/src/greeter.ts:22  greet -> one of: Greeter.greet (ts/src/greeter.ts:2); Polite.greet (ts/src/greeter.ts:7) [via inheritance]; Rude.greet (ts/src/greeter.ts:16) [via inheritance] [incomplete, virtual]
note: partial: name-level graph facts, verify by reading the code
```

## F7 interface conformance

`$ gt-shape Greeter`  (exit 0, 302 bytes)

```
[GT] shape Greeter
implementations of Greeter (requires farewell, greet) (2):
  ts/src/greeter.ts:6  Polite: has every method
  ts/src/greeter.ts:15  Rude: MISSING farewell
note: partial: name-level graph facts, verify by reading the code; omitted: certified_shape_check_unverifiable, method_names_only
```

## F8/F18 routes, middleware, DI

`$ gt-routes `  (exit 0, 289 bytes)

```
[GT] routes
routes (3):
  ts/src/server.ts:13  GET /api/items -> listItems middleware=[audit]
  py/shop/app.py:17  ANY /report -> report_view
  py/shop/app.py:23  ANY /safe -> safe_view
note: partial: name-level graph facts, verify by reading the code; omitted: certified_semantics:partial
```

## F9 execution flows

`$ gt-flows total`  (exit 0, 258 bytes)

```
[GT] flows total
process_count: 1
processes (1):
  total (py/shop/pricing.py:10) -> apply_tax (py/shop/pricing.py:5) -> round_money (py/shop/pricing.py:1)
note: partial: name-level graph facts, verify by reading the code; omitted: certified_semantics:partial
```

## F14-F17 slice

`$ gt-slice TotalArea 29`  (exit 0, 532 bytes)

```
[GT] slice TotalArea 29
backward slice of TotalArea at line 29 (6):
  go/calc/shapes.go:23  func TotalArea(shapes []Shape) float64 {
  go/calc/shapes.go:24  total := 0.0
  go/calc/shapes.go:25  for _, shape := range shapes {
  go/calc/shapes.go:26  total += shape.Area()
  go/calc/shapes.go:28  scaled := total * 2
  go/calc/shapes.go:29  return scaled
calls not followed (backward slice of TotalArea at line 29) (1):
  shape.Area
note: partial: name-level graph facts, verify by reading the code; omitted: slice_limitations_present
```

## F19 taint

`$ gt-taint report_view run_report`  (exit 0, 548 bytes)

```
[GT] taint report_view run_report
dataflow_omissions (1):
  callsite_args_unresolved
dataflow_paths (1):
  caller=report_view  caller_file=py/shop/app.py  sink=run_report  sink_file=py/shop/app.py  sink_line=19
paths (1):
  ['report_view', 'run_report']
unresolved_reaches (2):
  callee=get  callsite=py/shop/app.py:18  reason=callsite_unresolved
  callee=run  callsite=py/shop/app.py:13  reason=callsite_unresolved
note: partial: name-level graph facts, verify by reading the code; omitted: symbol_level_reachability_only, callsite_args_unresolved
```

## F20 tests reaching a file

`$ gt-tests go/calc/shapes.go`  (exit 0, 255 bytes)

```
[GT] tests for go/calc/shapes.go
tests reaching these files (1):
  go/calc/shapes_test.go:5  TestTotalArea (1 call hop(s) away)
note: partial: name-level graph facts, verify by reading the code; omitted: covering_selector_empty, graph_reachability_depth_3
```

## F10 module

`$ gt-module py/shop/pricing.py`  (exit 0, 172 bytes)

```
[GT] module cluster py/shop/pricing.py
cluster py/ (2 files, cohesion 1.0) (1):
  py/tests/test_pricing.py
note: partial: name-level graph facts, verify by reading the code
```

## Automatic: grep enrichment

`$ grep -rn "apply_tax" py/` - appended to the grep output:

```
[GT] graph context for your search:
  apply_tax (Function) py/shop/pricing.py:5
    called by: test_apply_tax_inside_callback (py/tests/test_pricing.py:9), total (py/shop/pricing.py:14)
    calls: round_money (py/shop/pricing.py:7)
    in flow: total -> round_money
```
