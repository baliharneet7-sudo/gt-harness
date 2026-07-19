---
project: projects/nano-harness
type: services
---

# Services — nano-harness

Hosted / third-party services. This is a local CLI agent harness — there is **no application hosting, database, or web service**. The only external services are the LLM inference APIs it calls.

## LLM inference

| Service | Role | Auth |
|---|---|---|
| **Anthropic Messages API** | `AnthropicProvider` (with prompt caching). | `ANTHROPIC_API_KEY` |
| **OpenAI Chat Completions API** | `OpenAIProvider`. | `OPENAI_API_KEY` |
| **OpenAI-compatible inference servers** | Any server speaking the OpenAI chat protocol — vLLM, Ollama, llama.cpp, Together — reached via `--base-url` / `OPENAI_BASE_URL`. | varies (often none for local) |

## Benchmarks (tooling, not hosted dependencies)

Terminal-Bench 2.0 (`harbor`) and SWE-bench Verified (`swebench`) run locally in containers for evaluation; they are not runtime services.

No hosted DB, storage, auth, or deploy platform is configured.
