# GroundTruth Optional MCP Adapter End-to-End Audit

Observed: `2026-08-23T03:58:30.646257Z`

Verdict: **PASS**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-3e2185d\receipts-only\mcp-e2e.json`

A clean MCP client entered an isolated clone of the pinned real itsdangerous repository. The server was the `gt-harness mcp` stdio adapter over the canonical graph; no benchmark adapter or precomputed graph was used. This certifies the optional adapter because the prerelease exposes it. The product itself is GT Harness and its canonical benchmark path is `gt-harness run` plus treatment/result receipts.

| Check | Result |
| --- | --- |
| Cold server initialization built a query-ready graph | PASS |
| Required graph receipt fields reached the client | PASS |
| Real `Signer` definition returned with source evidence | PASS |
| Client edit was detected and graph identity changed | PASS |
| Stale call edge disappeared and new edge appeared | PASS |
| Server restart reused the exact updated graph | PASS |
| Provider calls / credentials | 0 / false |

## Agent-visible identity

- Repository commit: `672971d66a2ef9f85151e53283113f33d642dabd`
- Cold graph: `935407135fe66687fdd80cb7537a429ea20098eb130353cbb6c36197d768119a`
- Updated graph: `a4f8eaff60acf3ded92fb61f3e40ba5e10d2f31d98651dbef0ce3ac0a8bda969`
- Updated state: `READY`; query ready `True`
- MCP initialization latency: `2132.233` ms
- Warm restart initialization latency: `1834.430` ms

The machine receipt stores the bounded status, definition, context, edit, and restart payloads exactly as delivered to the client.
