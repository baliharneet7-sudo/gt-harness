# GroundTruth MCP End-to-End Audit

Observed: `2026-08-23T01:51:52.530197Z`

Verdict: **PASS**

Machine receipt: `D:\gt-product-audit-5296dc3\codespaces-5bfb153\mcp-e2e.json`

A clean MCP client entered an isolated clone of the pinned real itsdangerous repository. The server was the production `gt-harness mcp` stdio boundary; no benchmark adapter or precomputed graph was used.

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
- Cold graph: `adead2595ae77d32e7a4d1d0b88cda152dafa4d6ddfdd6da200735f1e362ef4d`
- Updated graph: `d42530d573f7678d5036a50667d921e0105071bf4b49a6d9628ded0527c19171`
- Updated state: `READY`; query ready `True`
- MCP initialization latency: `2242.033` ms
- Warm restart initialization latency: `1940.948` ms

The machine receipt stores the bounded status, definition, context, edit, and restart payloads exactly as delivered to the client.
