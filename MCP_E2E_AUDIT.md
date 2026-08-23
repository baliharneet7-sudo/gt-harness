# GroundTruth MCP End-to-End Audit

Observed: `2026-08-23T00:27:49.970517Z`

Verdict: **PASS**

Machine receipt: `D:\gt-product-audit-5296dc3\receipts\mcp-e2e-d2d352a6.json`

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
- Cold graph: `903d542a26a33d13795c5ef2a0c50b0fc3c431a9fea4d7d4886b9409a7433fa7`
- Updated graph: `764dbfce9163b9e8f5de545668eb70a676e6a36d33c8e7a668bc4d8dda6688df`
- Updated state: `READY`; query ready `True`
- MCP initialization latency: `3214.341` ms
- Warm restart initialization latency: `1376.43` ms

The machine receipt stores the bounded status, definition, context, edit, and restart payloads exactly as delivered to the client.
