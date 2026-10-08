# OpenCode on envoy

Measured 2026-09-30 19:41 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: OpenCode 1.18.30, `opencode serve` driven over its HTTP API with `httpx` — OpenCode has no Python SDK
- **Gateway**: envoy, `http://localhost:26000/v1/chat/completions`, as the custom provider `ai-gateway-envoy-tests` on `@ai-sdk/openai-compatible`, handed in through `OPENCODE_CONFIG_CONTENT`
- **Thinking level**: the model option `reasoningEffort: medium`, which the provider sends as `reasoning_effort` in every body
- **Ceiling**: none set here — OpenCode sends `max_tokens: 32000` on every request, its default for a model it has no catalogue entry for
- **Agent**: OpenCode's built-in `build` agent and its own system prompt, which names the working directory and today's date
- **Tools**: OpenCode's built-ins less `bash`, `edit` and `write`, which `permission` denies outright — on 1.18.30 `glob`, `grep`, `question`, `read`, `skill`, `task`, `todowrite`, `webfetch`; the file is read with `read`
- **Isolation**: `OPENCODE_DISABLE_CLAUDE_CODE=1`, so ~/.claude/CLAUDE.md and ~/.claude/skills stay out of the prompt; a provider id no other OpenCode config declares, so ~/.config/opencode adds nothing to the model
- **Conversation**: one session per alias, created with a title so `small_model` is never asked for one; turns 2 and 3 resend the whole history, earlier thinking included as `reasoning_content`
- **Working directory**: a fresh temporary directory per session, holding a real `order.json`
- **Streaming**: always — OpenCode sends `stream: true` with `stream_options.include_usage`; the timings come from its event stream, `GET /event`

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 37.73 s | 8.4 s | 4 | 2.98 s → 0.37 s | 92 | 7202 → 7505 | 0 (0%) | 170 |
| `lms-qwen38-27b` | LMStudio | ok | 49.89 s | 20.8 s | 4 | 5.58 s → 0.61 s | 31 | 7588 → 8096 | 0 (0%) | 143 |
| `unsloth-gemma4-26b` | Unsloth | ok | 18.98 s | 9.3 s | 4 | 3.46 s → 0.23 s | 146 | 7207 → 7510 | 7459 (99%) | 0 |
| `unsloth-qwen38-27b` | Unsloth | ok | 11.01 s | 37.7 s | 4 | 16.47 s → 0.60 s | 27 | 7767 → 8286 | 8254 (99%) | 0 |
| `ollama-gemma4-26b` | Ollama | ok | 6.46 s | 6.2 s | 4 | 3.20 s → 0.20 s | 213 | 7163 → 7467 | 7416 (99%) | 0 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 1.04 s | 29.0 s | 5 | 2.40 s → 3.76 s | 85 | 7206 → 7588 | 0 (0%) | 476 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 3.69 s | 13.7 s | 4 | 0.91 s → 0.45 s | 46 | 7765 → 8203 | 7840 (95%) | 196 |

- **Warm-up** is one tiny request sent first, so loading the model is not counted as a
  first token. A long warm-up means the engine had to load it.
- **First token** is the wait before the first streamed token of a request. On the
  later requests the conversation so far is a prefix the engine can reuse, so a cache
  hit shows as a short wait there even when no count is reported.
- **Cached** is what the client was told. `not reported` means the reply carried no
  cache field — LMStudio's chat completions route never does
  (lmstudio-ai/lmstudio-bug-tracker#778) — not that the cache missed.
- **Decode tok/s** is the median over the requests, from the first streamed token to
  the last, thinking included.
- **Requests** are OpenCode's steps, one model request each, read off `step-finish` on its event stream and filed under the turn that caused them. **Request time** runs to `step-finish`, which follows the tool the step ran — a `read` takes milliseconds.
- **First token** is measured from the `session.status: busy` OpenCode emits just before it sends a request to the first streamed chunk of text, thinking or a tool call.
- **Cached** is 0, never `not reported`, when the reply carries no cache field: OpenCode writes `cache.read: 0`. On LMStudio's chat completions route 0 therefore means NOT REPORTED (lmstudio-ai/lmstudio-bug-tracker#778); the first-token times show whether the engine reused the prefix. **Thinking** is 0 in the same way when the gateway reports no split.
- **The working directory is in the system prompt**, after OpenCode's own instructions, so the first request of a session can reuse the previous session's harness only up to that line.

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.98 s | 3.31 s | 60 | 7202 | 0 (0%) | 19 | 1 |
| 2 | 1 | 0.45 s | 0.62 s | 100 | 7410 | 0 (0%) | 18 | 1 |
| 3 | 2 | 0.42 s | 0.69 s | 90 | 7454 | 0 (0%) | 26 | 1 |
| 4 | 3 | 0.37 s | 2.55 s | 94 | 7505 | 0 (0%) | 205 | 167 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.58 s | 8.98 s | 30 | 7588 | 0 (0%) | 101 | 31 |
| 2 | 1 | 1.40 s | 4.55 s | 31 | 7887 | 0 (0%) | 98 | 44 |
| 3 | 2 | 1.04 s | 2.33 s | 32 | 8020 | 0 (0%) | 42 | 16 |
| 4 | 3 | 0.61 s | 3.65 s | 31 | 8096 | 0 (0%) | 94 | 52 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.46 s | 4.03 s | 156 | 7207 | 0 (0%) | 89 | 0 |
| 2 | 1 | 0.23 s | 0.53 s | 136 | 7493 | 7280 (97%) | 42 | 0 |
| 3 | 2 | 0.32 s | 0.90 s | 167 | 7459 | 7207 (96%) | 97 | 0 |
| 4 | 3 | 0.23 s | 2.77 s | 131 | 7510 | 7459 (99%) | 333 | 0 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 16.47 s | 19.94 s | 29 | 7767 | 0 (0%) | 101 | 0 |
| 2 | 1 | 0.82 s | 4.03 s | 25 | 8062 | 7868 (97%) | 82 | 0 |
| 3 | 2 | 0.49 s | 3.16 s | 29 | 8176 | 8145 (99%) | 79 | 0 |
| 4 | 3 | 0.60 s | 9.61 s | 22 | 8286 | 8254 (99%) | 201 | 0 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.20 s | 3.22 s | 1007000 | 7163 | 0 (0%) | 19 | 0 |
| 2 | 1 | 0.24 s | 0.31 s | 216 | 7375 | 7163 (97%) | 15 | 0 |
| 3 | 2 | 0.20 s | 0.32 s | 210 | 7416 | 7372 (99%) | 26 | 0 |
| 4 | 3 | 0.20 s | 0.46 s | 142 | 7467 | 7416 (99%) | 37 | 0 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.40 s | 3.82 s | 85 | 7206 | 0 (0%) | 119 | 100 |
| 2 | 1 | 2.05 s | 2.60 s | 56 | 7385 | 1024 (13%) | 30 | 11 |
| 3 | 1 | 3.44 s | 4.58 s | 72 | 7609 | 0 (0%) | 51 | 33 |
| 4 | 2 | 3.55 s | 3.87 s | 91 | 7533 | 0 (0%) | 30 | 0 |
| 5 | 3 | 3.76 s | 13.25 s | 91 | 7588 | 0 (0%) | 371 | 332 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.91 s | 2.67 s | 54 | 7765 | 0 (0%) | 95 | 27 |
| 2 | 1 | 0.61 s | 3.49 s | 21 | 8053 | 6272 (77%) | 60 | 14 |
| 3 | 2 | 0.41 s | 0.89 s | 55 | 8145 | 7840 (96%) | 27 | 4 |
| 4 | 3 | 0.45 s | 5.77 s | 39 | 8203 | 7840 (95%) | 207 | 151 |
