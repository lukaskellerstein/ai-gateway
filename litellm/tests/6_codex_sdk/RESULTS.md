# Codex SDK on litellm

Measured 2026-09-30 19:24 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `openai-codex` 0.155.1, the Python SDK over the `codex app-server` runtime it ships
- **Gateway**: litellm, `http://localhost:24000/v1/responses` — Codex speaks the Responses API and nothing else
- **Thinking level**: `model_reasoning_effort="medium"`, on the wire as `reasoning: {effort: medium, summary: auto}` in every request
- **Conversation**: one Codex thread for the three turns. Every request resends the whole conversation (`store: false`, no `previous_response_id`) and carries the thread id as `prompt_cache_key`
- **Isolation**: an empty temporary `CODEX_HOME` and `features.plugins=false`: 9 tools in every request (2026-09-30), where this machine's `~/.codex` handed the model ~108
- **Tool**: Codex's own shell (`exec_command`) in the read-only sandbox with `deny_all` approvals, in a temporary directory holding `order.json`
- **Compaction**: `model_context_window=122880`
- **Timeout and retries**: `stream_idle_timeout_ms=3600000`, `request_max_retries=0`, `stream_max_retries=0`
- **Streaming**: always, in Codex; first token and decode speed come from its delta events

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 4.11 s | 16.5 s | 4 | — → — | — | 10506 → 10757 | 0 (0%) | 723 |
| `lms-qwen38-27b` | LMStudio | ok | 4.27 s | 32.3 s | 4 | 9.22 s → 1.14 s | 28 | 8456 → 8998 | 8704 (96%) | 341 |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.17 s | 11.3 s | 5 | 4.78 s → 0.28 s | 121 | 8240 → 8582 | 0 (0%) | 0 |
| `unsloth-qwen38-27b` | Unsloth | ok | 14.15 s | 37.8 s | 4 | 21.29 s → 0.55 s | 27 | 8464 → 8843 | 0 (0%) | 0 |
| `ollama-gemma4-26b` | Ollama | ok | 5.14 s | 13.1 s | 5 | 6.08 s → 0.26 s | 118 | 10419 → 10774 | 10718 (99%) | 0 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.86 s | 17.2 s | 4 | 3.58 s → 1.47 s | 108 | 10850 → 11133 | 10240 (91%) | 524 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 0.83 s | 22.5 s | 4 | 1.38 s → 0.61 s | 40 | 11407 → 11720 | 10976 (93%) | 211 |

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
- **Cached** is Codex's `cachedInputTokens`, a required integer: a gateway that sends no cache count reads as **0**, so a 0 here can mean *not reported*. LiteLLM's `/v1/responses` sends none for LMStudio; Envoy passes LMStudio's own count through (2026-09-30).
- **One row per model request**, from Codex's `thread/tokenUsage/updated`. Its time runs to that event, which follows the shell command the request asked for — milliseconds for a `cat`.
- **First token** and **Decode tok/s** are `—` for a request that reached Codex with no streamed delta. Through LiteLLM that is every request: its Responses stream opens the reasoning item without a `summary` field and never opens the message item, and Codex surfaces neither (2026-09-30).

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | — | 6.82 s | — | 10506 | 0 (0%) | 158 | 108 |
| 2 | 1 | — | 2.10 s | — | 10774 | 0 (0%) | 146 | 129 |
| 3 | 2 | — | 1.62 s | — | 10706 | 0 (0%) | 105 | 80 |
| 4 | 3 | — | 5.71 s | — | 10757 | 0 (0%) | 444 | 406 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 9.22 s | 10.93 s | 29 | 8456 | 4096 (48%) | 20 | 12 |
| 2 | 1 | 1.08 s | 9.96 s | 26 | 8649 | 8448 (97%) | 233 | 178 |
| 3 | 2 | 1.71 s | 3.12 s | 30 | 8919 | 8448 (94%) | 43 | 19 |
| 4 | 3 | 1.14 s | 8.21 s | 26 | 8998 | 8704 (96%) | 183 | 132 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 4.78 s | 5.84 s | 158 | 8240 | 0 (0%) | 137 | 0 |
| 2 | 1 | — | 0.36 s | — | 8436 | 0 (0%) | 19 | 0 |
| 3 | 1 | 0.20 s | 0.60 s | 115 | 8589 | 0 (0%) | 46 | 0 |
| 4 | 2 | 0.38 s | 1.21 s | 124 | 8531 | 0 (0%) | 103 | 0 |
| 5 | 3 | 0.28 s | 3.08 s | 117 | 8582 | 0 (0%) | 328 | 0 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 21.29 s | 23.37 s | 61 | 8464 | 0 (0%) | 64 | 0 |
| 2 | 1 | 0.89 s | 3.77 s | 23 | 8666 | 0 (0%) | 68 | 0 |
| 3 | 2 | 0.62 s | 2.27 s | 30 | 8766 | 0 (0%) | 46 | 0 |
| 4 | 3 | 0.55 s | 8.13 s | 22 | 8843 | 0 (0%) | 166 | 0 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 6.08 s | 7.52 s | 121 | 10419 | 0 (0%) | 146 | 0 |
| 2 | 1 | 0.26 s | 0.55 s | 277 | 10626 | 10523 (99%) | 27 | 0 |
| 3 | 1 | 0.41 s | 0.83 s | 118 | 10794 | 10621 (98%) | 50 | 0 |
| 4 | 2 | 0.44 s | 0.71 s | 114 | 10718 | 10419 (97%) | 31 | 0 |
| 5 | 3 | 0.26 s | 3.46 s | 90 | 10774 | 10718 (99%) | 288 | 0 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.58 s | 4.59 s | 158 | 10850 | 0 (0%) | 121 | 71 |
| 2 | 1 | 3.95 s | 4.82 s | 46 | 11033 | 0 (0%) | 19 | 0 |
| 3 | 2 | 1.24 s | 2.59 s | 118 | 11077 | 10240 (92%) | 158 | 127 |
| 4 | 3 | 1.47 s | 5.14 s | 99 | 11133 | 10240 (91%) | 363 | 326 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.38 s | 3.56 s | 60 | 11407 | 0 (0%) | 80 | 49 |
| 2 | 1 | 1.11 s | 14.00 s | 12 | 11578 | 10976 (94%) | 158 | 100 |
| 3 | 2 | 1.07 s | 1.87 s | 37 | 11668 | 10976 (94%) | 30 | 9 |
| 4 | 3 | 0.61 s | 2.99 s | 42 | 11720 | 10976 (93%) | 101 | 53 |
