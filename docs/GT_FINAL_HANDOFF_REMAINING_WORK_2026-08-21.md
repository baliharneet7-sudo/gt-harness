# GroundTruth final handoff — remaining work

> Historical handoff. The evidence risks below were repaired in the subsequent
> candidate. Use
> [GT_BENCHMARK_READINESS_AUTHORITY_2026-08-21.md](GT_BENCHMARK_READINESS_AUTHORITY_2026-08-21.md)
> as the sole current status and authorization sequence.

## Current truth

The implementation repairs are present in the working candidate. Candidate SHA
`77db941152d0d33929348590c7ce9528b3be64d6` has a passing exact Linux
provider-free mechanical proof (`WORKFLOW:32526386608`), while the active
release manifest still points to runtime SHA `bcc1543d6d050cb54820baeccc15c3c8f2e230cc`.
This is why the product is mechanically stable yet still not benchmark-authorized.

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

1. freeze a single canonical manifest path and align it to the proven runtime
   candidate (or rerun provider-free on the manifest runtime);
2. re-run the full no-spend suite on the exact frozen identity and keep the
   current no-spend output hash trail;
3. run the complete Python suite against that same frozen identity and explain
   every skip/failure explicitly;
4. build/test current Go source with production `sqlite_fts5` on Linux;
5. provision and verify the pinned Snowflake ONNX and tokenizer hashes;
6. execute full actual-agent triggers for all 17 historical mechanisms plus
   persistent execution state;
7. replay all 20 archived receipts through delivery, integrity, and release audits;
8. close three high-confidence evidence-to-causality gaps:
   - source→non-source transition when prior source bytes are missing from the
     workspace sensor but present in the mirror;
   - terminal observed-fact proof still needs stronger self-authored/no-op guards;
   - censor classification must separate provider-connection failures from verifier/
     task execution exceptions;
9. push the exact frozen SHA.

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
