# nano-harness — How It Works

One loop, three tools, two providers. ~850 physical lines total. This doc traces
exactly what happens when you run `nano run "fix the bug"`, so you can see where
efficiency lives and where it leaks.

## The pipeline, step by step

1. **CLI** (`cli.py`) — parses args, forces UTF-8 stdout, routes the model name
   to a provider: `--base-url` set → `OpenAIProvider` against any
   OpenAI-compatible endpoint (ASU gateway, vLLM, ollama); name starts with
   `claude` → `AnthropicProvider`; anything else → `OpenAIProvider`.
2. **Agent loop** (`agent.py`) — the core. Repeats: send conversation → get
   text + tool calls → execute tools → append results → repeat. Stops on
   `end_turn`, iteration cap (30), or context cap (200k tokens/step).
3. **Tools** (`tools.py`) — `bash` (persistent shell: bash everywhere, incl.
   Windows via Git bash; cmd.exe fallback only), `read_file` (line-numbered),
   `edit_file` (exact unique string replacement). Malformed calls come back as
   errors the model can fix, never crashes.
4. **Guards** — four things keep a run from dying or lying:
   - *Truncation*: conversation over ~120k chars → oldest tool outputs replaced
     with `[truncated]` placeholders (structure kept).
   - *Retry*: 429/5xx/connection errors retried 3× with backoff.
   - *Continuation*: output cut off mid-response → "continue" nudge, not false
     success.
   - *Verify pass*: the first "done" gets challenged once — re-read the task,
     run the tests, then finish.
5. **Result** — `AgentResult` with stop reason, iteration count, token totals,
   and a full transcript (every message, tool call, and tool result).

## The main loop

```mermaid
flowchart TD
    START([nano run 'task']) --> ROUTE{model name /<br/>--base-url?}
    ROUTE -->|base-url set| OAI[OpenAIProvider<br/>any OpenAI-compatible endpoint]
    ROUTE -->|claude*| ANT[AnthropicProvider<br/>+ prompt caching]
    ROUTE -->|other| OAI
    OAI --> LOOP
    ANT --> LOOP

    LOOP[iteration += 1] --> ITCAP{iteration ><br/>max_iterations?}
    ITCAP -->|yes| RMAX([return: max_iterations])
    ITCAP -->|no| TRUNC{conversation ><br/>120k chars?}
    TRUNC -->|yes| DROP[replace oldest tool outputs<br/>with truncated placeholder]
    TRUNC -->|no| STEP
    DROP --> STEP[provider.step<br/>retries 429/5xx 3x]
    STEP --> CTX{context this step<br/>>= 200k tokens?}
    CTX -->|yes| RTOK([return: max_tokens])
    CTX -->|no| CUT{output cut off<br/>mid-response?}
    CUT -->|yes| NUDGE[inject 'continue' nudge] --> LOOP
    CUT -->|no| DONE{model says done /<br/>no tool calls?}
    DONE -->|no| EXEC[execute each tool call<br/>errors become tool_result errors]
    EXEC --> APPEND[append tool results] --> LOOP
    DONE -->|yes| VERIFY{first 'done' and<br/>tools were used?}
    VERIFY -->|yes| CHALLENGE[inject verify nudge:<br/>re-read task, run tests, confirm] --> LOOP
    VERIFY -->|no| REND([return: end_turn + summary])
```

## One iteration, on the wire

```mermaid
sequenceDiagram
    participant A as Agent loop
    participant P as Provider
    participant G as Model API<br/>(gateway / Anthropic / OpenAI)
    participant T as Tools

    A->>P: step(messages, tools, system)
    P->>G: POST /chat/completions (retry 3x on 429/5xx)
    G-->>P: text + tool_calls + usage
    P-->>A: StepResult (normalized)
    A->>A: log assistant text + tool calls to transcript
    loop each tool call
        A->>T: dispatch(name, arguments)
        alt ok
            T-->>A: output (truncated to 16k chars)
        else bad call / tool error
            T-->>A: ToolError -> tool_result(is_error=true)
        end
    end
    A->>A: append tool results as next user message
    Note over A: repeat until end_turn / caps
```

## The persistent shell

```mermaid
flowchart LR
    RUN[bash tool call] --> ALIVE{shell process<br/>alive?}
    ALIVE -->|no| SPAWN[spawn bash<br/>Git bash on Windows,<br/>cmd.exe only as fallback]
    ALIVE -->|yes| SEND
    SPAWN --> SEND[write command + sentinel echo]
    SEND --> READ[reader thread drains stdout<br/>into a queue]
    READ --> WAIT{sentinel seen<br/>before timeout?}
    WAIT -->|yes| OUT[return output<br/>cwd + env persist for next call]
    WAIT -->|no| KILL[kill + respawn shell<br/>error tells model:<br/>state was reset]
```

Key property: `cd` and `export` survive between calls — the model works in a
real session, not one-shot commands. On timeout the whole shell dies and the
model is told its state is gone.

**Known limitation:** `read_file`/`edit_file` resolve relative paths against
the *process* cwd, not the shell's live cwd. A model that `cd`s in bash then
edits a relative path hits the wrong file. Documented, deferred (fix needs
MSYS path translation on Windows).

## Where the efficiency lives (and leaks)

| Mechanism | Status | Effect |
|---|---|---|
| Prompt caching (`cache_control`) | Anthropic direct only — **inactive through the gateway** (all head-to-head runs show `cache_read=0`) | biggest cost leak on long tasks |
| Iteration cap (30) | active | load-bearing for weak models (haiku hit it on all 3 tasks) |
| Tool output truncation (16k chars) | active | keeps one noisy command from flooding context |
| Conversation truncation (120k chars) | active | keeps long runs inside the window |
| Verify pass (1 extra step) | active | buys correctness for ~1 iteration of cost |
| Loop/thrash detection | **none** | haiku burned 30 iterations on 1-line fixes; nothing stops identical repeated calls |
