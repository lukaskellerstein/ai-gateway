# Claude Agent SDK on litellm

Measured 2026-09-30 19:16 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: Claude Agent SDK 0.2.152, driving the Claude Code CLI it bundles (2.1.259) — one `ClaudeSDKClient` conversation, three `query()` calls
- **Gateway**: litellm, `http://localhost:24000/v1/messages` — the Anthropic Messages API; the model is the alias through `anthropic_alias()` in settings.py, named per session below
- **Thinking level**: `CLAUDE_CODE_EFFORT_LEVEL=medium`, sent by the CLI as `output_config.effort`
- **CLI environment**: `API_TIMEOUT_MS=3600000`, `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=off`, `CLAUDE_CODE_ATTRIBUTION_HEADER=0`, `CLAUDE_CODE_EFFORT_LEVEL=medium` — the two cache settings stop the CLI rewriting the top of its prompt (settings.py); `ANTHROPIC_API_KEY` is removed
- **Isolation**: `setting_sources=[]` — nothing from ~/.claude or any CLAUDE.md
- **System prompt**: none of our own (`system_prompt=None`)
- **Tool**: the CLI's own `Read`, the only tool offered (`tools=["Read"]`), in a temporary directory holding `order.json`
- **Streaming**: `include_partial_messages=True` — the raw Anthropic stream of every request

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 37.40 s | 13.7 s | 4 | 2.60 s → 0.38 s | 100 | 2534 → 2765 | not reported | — |
| `lms-qwen38-27b` | LMStudio | ok | 48.51 s | 27.1 s | 4 | 8.96 s → 1.33 s | 31 | 2799 → 3138 | not reported | — |
| `unsloth-gemma4-26b` | Unsloth | ok | 18.06 s | 17.2 s | 4 | 2.27 s → 0.34 s | 85 | 2532 → 2765 | 2709 (97%) | — |
| `unsloth-qwen38-27b` | Unsloth | ok | 12.80 s | 39.5 s | 4 | 12.02 s → 1.28 s | 16 | 2825 → 3151 | 3090 (98%) | — |
| `ollama-gemma4-26b` | Ollama | ok | 7.46 s | 28.8 s | 4 | 1.14 s → 0.23 s | 163 | 2535 → 2766 | 2712 (98%) | — |
| `openrouter-gemma4-26b` | OpenRouter | ok | 1.05 s | 31.3 s | 4 | 1.61 s → 4.94 s | 103 | 2537 → 2770 | not reported | — |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.57 s | 10.1 s | 4 | 0.54 s → 0.49 s | 55 | 2825 → 3150 | 1568 (49%) | — |

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
- `lms-gemma4-26b` was sent as `lms-gemma4-26b`; the CLI spent 2684 input and 9 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `lms-qwen38-27b` was sent as `lms-qwen38-27b`; the CLI spent 4192 input and 36 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `unsloth-gemma4-26b` was sent as `unsloth-gemma4-26b`; the CLI spent 2684 input and 893 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `unsloth-qwen38-27b` was sent as `unsloth-qwen38-27b`; the CLI spent 2683 input and 362 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `ollama-gemma4-26b` was sent as `ollama-gemma4-26b`; the CLI spent 2686 input and 720 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `openrouter-gemma4-26b` was sent as `openrouter-gemma4-26b`; the CLI spent 2766 input and 9 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.
- `openrouter-qwen38-27b` was sent as `openrouter-qwen38-27b`; the CLI spent 2721 input and 508 output tokens outside the conversation — the session title (`generate_session_title`), sent beside the first request.

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.60 s | 3.53 s | 94 | 2534 | not reported | 87 | — |
| 2 | 1 | 0.35 s | 1.29 s | 108 | 2667 | not reported | 102 | — |
| 3 | 2 | 0.29 s | 1.31 s | 103 | 2711 | not reported | 105 | — |
| 4 | 3 | 0.38 s | 6.52 s | 97 | 2765 | not reported | 593 | — |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 8.96 s | 11.45 s | 31 | 2799 | not reported | 77 | — |
| 2 | 1 | 0.94 s | 4.08 s | 30 | 2981 | not reported | 96 | — |
| 3 | 2 | 1.91 s | 3.73 s | 32 | 3075 | not reported | 60 | — |
| 4 | 3 | 1.33 s | 7.12 s | 31 | 3138 | not reported | 181 | — |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.27 s | 3.20 s | 94 | 2532 | not reported | 88 | — |
| 2 | 1 | 0.22 s | 1.61 s | 85 | 2668 | 2532 (94%) | 118 | — |
| 3 | 2 | 0.33 s | 1.52 s | 85 | 2709 | 2665 (98%) | 99 | — |
| 4 | 3 | 0.34 s | 10.25 s | 84 | 2765 | 2709 (97%) | 828 | — |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 12.02 s | 17.68 s | 14 | 2825 | not reported | 79 | — |
| 2 | 1 | 1.10 s | 6.00 s | 16 | 3010 | 2821 (93%) | 78 | — |
| 3 | 2 | 1.30 s | 6.02 s | 15 | 3094 | 3006 (97%) | 74 | — |
| 4 | 3 | 1.28 s | 9.18 s | 17 | 3151 | 3090 (98%) | 135 | — |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.14 s | 1.54 s | 164 | 2535 | not reported | 60 | — |
| 2 | 1 | 9.41 s | 9.48 s | 226 | 2671 | 2530 (94%) | 15 | — |
| 3 | 2 | 0.23 s | 0.94 s | 162 | 2712 | 2668 (98%) | 114 | — |
| 4 | 3 | 0.23 s | 16.37 s | 91 | 2766 | 2712 (98%) | 1458 | — |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.61 s | 2.50 s | 102 | 2537 | not reported | 91 | — |
| 2 | 1 | 1.16 s | 2.43 s | 117 | 2670 | not reported | 94 | — |
| 3 | 2 | 1.22 s | 2.42 s | 104 | 2714 | not reported | 108 | — |
| 4 | 3 | 4.94 s | 23.52 s | 50 | 2770 | not reported | 917 | — |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.54 s | 1.94 s | 58 | 2825 | not reported | 82 | — |
| 2 | 1 | 0.63 s | 3.05 s | 51 | 3010 | not reported | 122 | — |
| 3 | 2 | 0.43 s | 1.24 s | 59 | 3093 | 1568 (50%) | 48 | — |
| 4 | 3 | 0.49 s | 3.22 s | 52 | 3150 | 1568 (49%) | 143 | — |
