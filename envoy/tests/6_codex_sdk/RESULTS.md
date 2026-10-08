# Codex SDK on envoy

Measured 2026-09-30 19:30 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `openai-codex` 0.155.1, the Python SDK over the `codex app-server` runtime it ships
- **Gateway**: envoy, `http://localhost:26000/v1/responses` — Codex speaks the Responses API and nothing else
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
| `lms-gemma4-26b` | LMStudio | ok | 3.86 s | 15.1 s | 5 | 2.76 s → 0.48 s | 88 | 8237 → 8562 | 8448 (98%) | 659 |
| `lms-qwen38-27b` | LMStudio | ok | 60.21 s | 38.4 s | 5 | 10.24 s → 0.96 s | 18 | 8452 → 9045 | 8960 (99%) | 226 |
| `unsloth-gemma4-26b` | Unsloth | ok | 0.50 s | 13.1 s | 4 | 5.16 s → 0.42 s | 72 | 8245 → 8517 | 0 (0%) | 0 |
| `unsloth-qwen38-27b` | Unsloth | ok | 16.23 s | 82.6 s | 4 | 56.03 s → 0.59 s | 24 | 8464 → 8984 | 0 (0%) | 0 |
| `ollama-gemma4-26b` | Ollama | ok | 6.66 s | 25.9 s | 4 | 7.14 s → 0.28 s | 98 | 10423 → 10704 | 10648 (99%) | 0 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.91 s | 84.8 s | 7 | 16.68 s → 3.47 s | 58 | 10852 → 12102 | 11264 (93%) | 1993 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 10.83 s | 12.8 s | 4 | 1.26 s → 1.52 s | 47 | 11415 → 11720 | 10976 (93%) | 196 |

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

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.76 s | 4.60 s | 80 | 8237 | 3840 (46%) | 128 | 102 |
| 2 | 1 | 0.42 s | 0.88 s | 134 | 8412 | 8192 (97%) | 17 | 17 |
| 3 | 1 | 0.62 s | 0.98 s | 115 | 8590 | 8192 (95%) | 42 | 29 |
| 4 | 2 | 0.41 s | 1.60 s | 88 | 8508 | 8192 (96%) | 106 | 82 |
| 5 | 3 | 0.48 s | 6.71 s | 74 | 8562 | 8448 (98%) | 463 | 429 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 10.24 s | 13.14 s | 28 | 8452 | 4096 (48%) | 32 | 31 |
| 2 | 1 | 1.05 s | 2.98 s | 27 | 8593 | 8448 (98%) | 25 | 24 |
| 3 | 1 | 1.35 s | 9.87 s | 16 | 8790 | 8448 (96%) | 138 | 81 |
| 4 | 2 | 1.47 s | 3.89 s | 18 | 8965 | 8704 (97%) | 44 | 15 |
| 5 | 3 | 0.96 s | 8.30 s | 16 | 9045 | 8960 (99%) | 121 | 75 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.16 s | 7.05 s | 76 | 8245 | 0 (0%) | 119 | 0 |
| 2 | 1 | 0.40 s | 1.21 s | 67 | 8507 | 0 (0%) | 54 | 0 |
| 3 | 2 | 0.58 s | 0.87 s | 82 | 8468 | 0 (0%) | 24 | 0 |
| 4 | 3 | 0.42 s | 3.90 s | 54 | 8517 | 0 (0%) | 188 | 0 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 56.03 s | 59.22 s | 38 | 8464 | 0 (0%) | 66 | 0 |
| 2 | 1 | 1.07 s | 10.69 s | 19 | 8671 | 0 (0%) | 187 | 0 |
| 3 | 2 | 0.81 s | 3.17 s | 28 | 8890 | 0 (0%) | 63 | 0 |
| 4 | 3 | 0.59 s | 9.24 s | 19 | 8984 | 0 (0%) | 166 | 0 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 7.14 s | 8.45 s | 108 | 10423 | 0 (0%) | 119 | 0 |
| 2 | 1 | 0.30 s | 0.98 s | 101 | 10684 | 10496 (98%) | 70 | 0 |
| 3 | 2 | 0.39 s | 2.46 s | 94 | 10648 | 10423 (97%) | 196 | 0 |
| 4 | 3 | 0.28 s | 13.83 s | 50 | 10704 | 10648 (99%) | 681 | 0 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 16.68 s | 20.14 s | 59 | 10852 | 0 (0%) | 139 | 94 |
| 2 | 1 | 3.50 s | 5.55 s | 164 | 10950 | 0 (0%) | 211 | 117 |
| 3 | 1 | 3.23 s | 6.39 s | 61 | 11320 | 10240 (90%) | 158 | 108 |
| 4 | 1 | 1.87 s | 8.50 s | 58 | 11501 | 11264 (97%) | 370 | 0 |
| 5 | 1 | 2.82 s | 3.17 s | 47 | 12005 | 11264 (93%) | 15 | 0 |
| 6 | 2 | 5.44 s | 9.13 s | 50 | 12049 | 0 (0%) | 184 | 156 |
| 7 | 3 | 3.47 s | 31.83 s | 55 | 12102 | 11264 (93%) | 1556 | 1518 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.26 s | 3.08 s | 84 | 11415 | 0 (0%) | 59 | 28 |
| 2 | 1 | 0.87 s | 3.49 s | 45 | 11586 | 10976 (94%) | 118 | 73 |
| 3 | 2 | 0.58 s | 1.86 s | 48 | 11663 | 10976 (94%) | 62 | 36 |
| 4 | 3 | 1.52 s | 4.27 s | 40 | 11720 | 10976 (93%) | 109 | 59 |
