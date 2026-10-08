# OpenCode on litellm

Measured 2026-09-30 19:55 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: OpenCode 1.18.30, `opencode serve` driven over its HTTP API with `httpx` — OpenCode has no Python SDK
- **Gateway**: litellm, `http://localhost:24000/v1/chat/completions`, as the custom provider `ai-gateway-litellm-tests` on `@ai-sdk/openai-compatible`, handed in through `OPENCODE_CONFIG_CONTENT`
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
| `lms-gemma4-26b` | LMStudio | ok | 2.58 s | 8.6 s | 5 | 3.08 s → 0.35 s | 101 | 7205 → 7637 | 0 (0%) | 99 |
| `lms-qwen38-27b` | LMStudio | ok | 2.73 s | 34.1 s | 5 | 7.09 s → 0.76 s | 30 | 7590 → 8376 | 0 (0%) | 424 |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.11 s | 9.6 s | 4 | 3.51 s → 0.22 s | 179 | 7207 → 7517 | 7461 (99%) | 407 |
| `unsloth-qwen38-27b` | Unsloth | ok | 12.63 s | 35.1 s | 4 | 16.42 s → 0.54 s | 28 | 7768 → 8295 | 8265 (99%) | 187 |
| `ollama-gemma4-26b` | Ollama | ok | 6.49 s | 10.0 s | 4 | 3.12 s → 0.25 s | 210 | 7165 → 7473 | 7417 (99%) | 413 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.97 s | 30.6 s | 5 | 3.57 s → 2.72 s | 85 | 7207 → 7583 | 0 (0%) | 525 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.18 s | 11.5 s | 4 | 0.88 s → 0.40 s | 48 | 7760 → 8261 | 7840 (94%) | 191 |

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
| 1 | 1 | 3.08 s | 4.09 s | 90 | 7205 | 0 (0%) | 89 | 71 |
| 2 | 1 | 0.38 s | 1.36 s | 74 | 7354 | 0 (0%) | 73 | 9 |
| 3 | 1 | 0.41 s | 0.69 s | 118 | 7625 | 0 (0%) | 34 | 17 |
| 4 | 2 | 0.41 s | 0.68 s | 115 | 7581 | 0 (0%) | 31 | 1 |
| 5 | 3 | 0.35 s | 0.70 s | 101 | 7637 | 0 (0%) | 37 | 1 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 7.09 s | 9.33 s | 31 | 7590 | 0 (0%) | 70 | 39 |
| 2 | 1 | 1.04 s | 3.70 s | 30 | 7722 | 0 (0%) | 79 | 9 |
| 3 | 1 | 1.05 s | 9.33 s | 28 | 7999 | 0 (0%) | 236 | 187 |
| 4 | 2 | 1.23 s | 3.51 s | 31 | 8270 | 0 (0%) | 72 | 46 |
| 5 | 3 | 0.76 s | 7.37 s | 28 | 8376 | 0 (0%) | 189 | 143 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.51 s | 3.58 s | 273 | 7207 | 0 (0%) | 19 | 0 |
| 2 | 1 | 0.25 s | 0.32 s | 188 | 7420 | 7207 (97%) | 15 | 0 |
| 3 | 2 | 0.25 s | 0.43 s | 169 | 7461 | 7417 (99%) | 31 | 0 |
| 4 | 3 | 0.22 s | 4.23 s | 129 | 7517 | 7461 (99%) | 513 | 407 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 16.42 s | 19.81 s | 31 | 7768 | 0 (0%) | 104 | 32 |
| 2 | 1 | 0.83 s | 4.56 s | 26 | 8066 | 7872 (97%) | 98 | 44 |
| 3 | 2 | 0.50 s | 2.75 s | 32 | 8196 | 8165 (99%) | 68 | 36 |
| 4 | 3 | 0.54 s | 6.74 s | 22 | 8295 | 8265 (99%) | 138 | 75 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.12 s | 3.13 s | 1248517 | 7165 | 0 (0%) | 19 | 0 |
| 2 | 1 | 0.24 s | 0.34 s | 219 | 7376 | 7165 (97%) | 15 | 0 |
| 3 | 2 | 0.20 s | 0.36 s | 201 | 7417 | 7373 (99%) | 31 | 0 |
| 4 | 3 | 0.25 s | 5.27 s | 101 | 7473 | 7417 (99%) | 504 | 413 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.57 s | 5.40 s | 80 | 7207 | 0 (0%) | 145 | 126 |
| 2 | 1 | 2.42 s | 3.33 s | 37 | 7411 | 0 (0%) | 34 | 15 |
| 3 | 1 | 6.58 s | 7.13 s | 91 | 7639 | 0 (0%) | 46 | 28 |
| 4 | 2 | 6.58 s | 7.83 s | 85 | 7532 | 0 (0%) | 106 | 80 |
| 5 | 3 | 2.72 s | 5.72 s | 104 | 7583 | 0 (0%) | 312 | 276 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.88 s | 2.87 s | 48 | 7760 | 0 (0%) | 92 | 23 |
| 2 | 1 | 0.89 s | 3.06 s | 47 | 8046 | 6272 (77%) | 101 | 48 |
| 3 | 2 | 0.42 s | 1.49 s | 49 | 8179 | 7840 (95%) | 51 | 25 |
| 4 | 3 | 0.40 s | 3.28 s | 47 | 8261 | 7840 (94%) | 137 | 95 |
