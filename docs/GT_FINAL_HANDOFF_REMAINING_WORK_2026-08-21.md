# GroundTruth final handoff — remaining work

## Current truth

The implementation repairs are present in the working candidate, but the active
release manifest still identifies the previous frozen runtime. This is correct
fail-closed behavior while tracked changes exist. Do not run a paid task matrix
until the final source-built provider-free proof passes for the exact frozen SHA.

## Closed code defects

- secret-valued workflow dispatch inputs removed;
- stale ten-minute TokenRouter monitor removed;
- TB2 promotion route derived from the frozen baseline manifest;
- merge identity derived from the same manifest instead of literal model names;
- graph refresh bounded inside the synchronous index operation;
- no graph-refresh thread can survive a host timeout and mutate stale state;
- obsolete next-transition timeout escalation removed;
- source deletion and source-to-non-source edits cannot retain or rebind a
  stale graph, including oversized extensionless sources whose prior text was
  absent from the bounded sensor but present in the exact repository mirror;
- arbitrary non-source outputs no longer stale source-bound validation, while
  actual code deliverables and shebang/content-signature sources do;
- observed facts receive selected, rejected, represented, or terminal
  dispositions and cannot starve later facts;
- observed-fact audit joins deliveries and compiler decisions;
- provider censor patterns no longer classify generic verifier timeout text as
  provider failure;
- trial outcomes are mutually exclusive and censor counts count trials, not
  deduplicated task names;
- provider-visible claims require materiality in both compiler and independent
  release/delivery audits; explicit claim IDs are separated from private
  fact/effect accounting IDs;
- task-semantic, feature-guidance, and frontier deliveries have independent
  semantic-support checks instead of trusting producer labels;
- merge joins the live bootstrap canary route proof, immutable release route,
  and each task's provider-route receipt before promotion;
- all required research/release documents are included in the documentation
  audit.

## Remaining no-spend verification

1. Commit the reviewed runtime and documentation candidate.
2. Create the new two-file prediction/release freeze for that runtime commit.
3. Run the complete Python suite against the frozen identity and explain every
   skip. The pre-freeze full pass collected 2,047 tests; after two modernized
   audit fixtures, the only remaining failure is the intentionally stale v23
   release identity.
4. Build/test current Go source with the production `sqlite_fts5` tag on Linux.
5. Provision and verify the pinned Snowflake ONNX and tokenizer hashes.
6. Execute the actual-agent trigger matrix for all 17 historical mechanisms and
   persistent execution state.
7. Replay all 20 archived receipts through current delivery, integrity, and
   release audits; label historical schema/runtime limitations explicitly.
8. Push the exact freeze SHA and run `central_provider_free.yml`.

## Paid benchmark authorization gate

Authorize exactly one parallel-20, fixed `repair20-v1`, GT-on run only when:

- the exact pushed SHA has provider-free `PASS`;
- mechanical completeness and documentation consistency pass;
- repository intelligence is current or explicitly non-applicable;
- every provider-visible claim has a valid delivery and value certificate;
- persistent state is repeatedly exercised on every applicable task;
- outcome accounting preserves all 20 denominator rows;
- provider/model/route identity equals the frozen baseline contract; and
- no scheduled workflow or secret-valued dispatch input exists.

The next report separates integrity, solve outcomes, efficiency, and causal
intervention evidence. No repeated 20-task runs are authorized by this handoff.
