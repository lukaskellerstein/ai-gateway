# Claude Agent SDK on envoy

Measured 2026-09-30 19:20 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: Claude Agent SDK 0.2.152, driving the Claude Code CLI it bundles (2.1.259) — one `ClaudeSDKClient` conversation, three `query()` calls
- **Gateway**: envoy, `http://localhost:26000/anthropic/v1/messages` — the Anthropic Messages API; the model is the alias through `anthropic_alias()` in settings.py, named per session below
- **Thinking level**: `CLAUDE_CODE_EFFORT_LEVEL=medium`, sent by the CLI as `output_config.effort`
- **CLI environment**: `API_TIMEOUT_MS=3600000`, `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=off`, `CLAUDE_CODE_ATTRIBUTION_HEADER=0`, `CLAUDE_CODE_EFFORT_LEVEL=medium` — the two cache settings stop the CLI rewriting the top of its prompt (settings.py); `ANTHROPIC_API_KEY` is removed
- **Isolation**: `setting_sources=[]` — nothing from ~/.claude or any CLAUDE.md
- **System prompt**: none of our own (`system_prompt=None`)
- **Tool**: the CLI's own `Read`, the only tool offered (`tools=["Read"]`), in a temporary directory holding `order.json`
- **Streaming**: `include_partial_messages=True` — the raw Anthropic stream of every request

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 16.47 s | 26.8 s | 4 | 13.13 s → 0.36 s | 96 | 2533 → 2761 | 2560 (92%) | — |
| `lms-qwen38-27b` | LMStudio | ok | 7.39 s | 40.3 s | 4 | 14.64 s → 1.11 s | 30 | 2806 → 3357 | 3072 (91%) | — |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.68 s | 15.8 s | 4 | 2.58 s → 0.37 s | 76 | 2542 → 2771 | 0 (0%) | — |
| `unsloth-qwen38-27b` | Unsloth | ok | 13.64 s | 51.9 s | 4 | 28.89 s → 0.89 s | 24 | 2823 → 3267 | 0 (0%) | — |
| `ollama-gemma4-26b` | Ollama | ok | 3.05 s | 31.4 s | 4 | 1.21 s → 1.33 s | 134 | 2542 → 2775 | 2719 (97%) | — |
| `openrouter-gemma4-26b` | OpenRouter | ok | 9.57 s | 22.1 s | 4 | 2.38 s → 1.73 s | 84 | 2542 → 2775 | 0 (0%) | — |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.25 s | 14.4 s | 4 | 0.81 s → 0.56 s | 50 | 2826 → 3299 | 0 (0%) | — |

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
- **One row per model request**: `message_start` … `message_stop` in the raw stream. Its clock starts at the CLI's `requesting` status, because LMStudio's own /v1/messages sends `message_start` only after it has read the prompt.
- **Prompt tokens** are `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, Anthropic's rule — except on `lms-*`, where LMStudio already counts the cached part inside `input_tokens` (measured 2026-09-30).
- **Cached** is `cache_read_input_tokens`. LiteLLM's `message_start` carries every count as 0 before the engine has answered; that 0 is not taken as a count, so a route that never reports its cache reads `not reported`.
- **Thinking tokens** are not reported: Anthropic's usage counts thinking inside `output_tokens`.
- **Session** includes starting the `claude` CLI, about 0.6 s.
- `lms-gemma4-26b` was sent as `lms-gemma4-26b-anthropic`; the CLI spent 2683 input and 1045 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `lms-qwen38-27b` was sent as `lms-qwen38-27b-anthropic`; the CLI spent 2680 input and 167 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `unsloth-gemma4-26b` was sent as `unsloth-gemma4-26b-anthropic`; the CLI spent nothing outside the conversation.
- `unsloth-qwen38-27b` was sent as `unsloth-qwen38-27b-anthropic`; the CLI spent 2720 input and 307 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `ollama-gemma4-26b` was sent as `ollama-gemma4-26b-anthropic`; the CLI spent 2683 input and 1076 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `openrouter-gemma4-26b` was sent as `openrouter-gemma4-26b-anthropic`; the CLI spent 2753 input and 973 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `openrouter-qwen38-27b` was sent as `openrouter-qwen38-27b-anthropic`; the CLI spent 2682 input and 246 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 13.13 s | 14.52 s | 83 | 2533 | 0 (0%) | 115 | — |
| 2 | 1 | 0.46 s | 1.05 s | 93 | 2765 | 2560 (92%) | 56 | — |
| 3 | 2 | 0.51 s | 1.51 s | 105 | 2710 | 2304 (85%) | 106 | — |
| 4 | 3 | 0.36 s | 8.87 s | 98 | 2761 | 2560 (92%) | 838 | — |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 14.64 s | 17.29 s | 30 | 2806 | 0 (0%) | 81 | — |
| 2 | 1 | 1.38 s | 8.87 s | 29 | 3004 | 2560 (85%) | 215 | — |
| 3 | 2 | 1.40 s | 3.57 s | 31 | 3254 | 2816 (86%) | 69 | — |
| 4 | 3 | 1.11 s | 10.13 s | 27 | 3357 | 3072 (91%) | 247 | — |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.58 s | 4.16 s | 74 | 2542 | 0 (0%) | 117 | — |
| 2 | 1 | 0.23 s | 1.27 s | 77 | 2678 | 0 (0%) | 81 | — |
| 3 | 2 | 0.33 s | 1.66 s | 78 | 2717 | 0 (0%) | 105 | — |
| 4 | 3 | 0.37 s | 8.12 s | 69 | 2771 | 0 (0%) | 536 | — |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 28.89 s | 32.39 s | 29 | 2823 | 0 (0%) | 101 | — |
| 2 | 1 | 0.60 s | 6.38 s | 21 | 3038 | 0 (0%) | 120 | — |
| 3 | 2 | 0.84 s | 2.68 s | 26 | 3190 | 0 (0%) | 46 | — |
| 4 | 3 | 0.89 s | 9.76 s | 20 | 3267 | 0 (0%) | 181 | — |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.21 s | 2.09 s | 130 | 2542 | 0 (0%) | 115 | — |
| 2 | 1 | 16.84 s | 17.20 s | 144 | 2777 | 2537 (91%) | 52 | — |
| 3 | 2 | 0.77 s | 2.21 s | 138 | 2719 | 2542 (93%) | 199 | — |
| 4 | 3 | 1.33 s | 9.35 s | 93 | 2775 | 2719 (97%) | 748 | — |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.38 s | 3.69 s | 91 | 2542 | 0 (0%) | 120 | — |
| 2 | 1 | 2.45 s | 3.30 s | 111 | 2779 | 0 (0%) | 44 | — |
| 3 | 2 | 2.43 s | 4.87 s | 76 | 2719 | 0 (0%) | 146 | — |
| 4 | 3 | 1.73 s | 9.78 s | 76 | 2775 | 0 (0%) | 588 | — |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.81 s | 2.87 s | 48 | 2826 | 0 (0%) | 100 | — |
| 2 | 1 | 1.92 s | 3.95 s | 52 | 3040 | 1568 (51%) | 106 | — |
| 3 | 2 | 0.82 s | 3.43 s | 34 | 3178 | 0 (0%) | 90 | — |
| 4 | 3 | 0.56 s | 3.35 s | 51 | 3299 | 0 (0%) | 144 | — |
