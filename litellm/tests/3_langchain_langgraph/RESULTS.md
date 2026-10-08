# LangChain + LangGraph on litellm

Measured 2026-09-30 19:01 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `ChatOpenAI` from `langchain-openai`, inside a LangGraph `StateGraph` — model node, `ToolNode`, `tools_condition` — with an `InMemorySaver` holding the conversation
- **Gateway**: litellm, `http://localhost:24000/v1/chat/completions`
- **Thinking level**: `reasoning_effort="medium"` on ChatOpenAI, in every body
- **Ceiling**: none sent — the gateway's route stores one
- **Streaming**: `streaming=True`, `stream_usage=True` — ChatOpenAI turns streamed usage off by itself once `base_url` is set
- **Retries and sampling**: `max_retries=0`; no temperature sent, so the engine's default
- **Tool**: one `StructuredTool`, `read_file`, carrying the task's JSON schema; `ToolNode` runs it
- **Measured**: per model request, by a callback handler: `on_chat_model_start` to the first and last streamed chunk, then `usage_metadata` in `on_llm_end`

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 2.22 s | 10.6 s | 4 | 2.78 s → 0.31 s | 105 | 2022 → 2204 | not reported | 598 |
| `lms-qwen38-27b` | LMStudio | ok | 2.54 s | 21.1 s | 4 | 3.41 s → 0.67 s | 31 | 2231 → 2465 | not reported | 366 |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.00 s | 16.4 s | 4 | 0.72 s → 0.18 s | 142 | 2025 → 2233 | 2182 (97%) | 1826 |
| `unsloth-qwen38-27b` | Unsloth | ok | 15.93 s | 23.1 s | 4 | 4.99 s → 0.83 s | 30 | 2233 → 2506 | 2445 (97%) | 285 |
| `ollama-gemma4-26b` | Ollama | ok | 1.06 s | 19.4 s | 4 | 1.05 s → 0.19 s | 117 | 2023 → 2231 | 2180 (97%) | 1592 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 1.18 s | 42.5 s | 4 | 1.83 s → 4.49 s | 57 | 2024 → 2232 | 0 (0%) | 1165 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 0.92 s | 14.3 s | 4 | 0.69 s → 0.73 s | 34 | 2233 → 2503 | 0 (0%) | 219 |

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
- ChatOpenAI drops `reasoning_content`, so a thinking token arrives as an empty chunk. The first-token clock counts every chunk but the finish, usage and `last` frames; thinking counts come from `usage_metadata.output_token_details.reasoning`.
- `cache_read` is absent from `usage_metadata` when the reply carries no cache field — LangChain does not turn it into 0 — so `not reported` means the same as in every other folder.

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.78 s | 3.83 s | 96 | 2022 | not reported | 100 | 80 |
| 2 | 1 | 0.43 s | 1.26 s | 116 | 2109 | not reported | 98 | 81 |
| 3 | 2 | 0.26 s | 1.77 s | 109 | 2153 | not reported | 166 | 141 |
| 4 | 3 | 0.31 s | 3.52 s | 101 | 2204 | not reported | 326 | 296 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.41 s | 4.91 s | 33 | 2231 | not reported | 49 | 21 |
| 2 | 1 | 0.71 s | 2.95 s | 31 | 2359 | not reported | 71 | 55 |
| 3 | 2 | 0.58 s | 4.31 s | 31 | 2407 | not reported | 117 | 90 |
| 4 | 3 | 0.67 s | 8.96 s | 30 | 2465 | not reported | 250 | 200 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.72 s | 1.27 s | 139 | 2025 | 0 (0%) | 76 | 48 |
| 2 | 1 | 0.15 s | 0.65 s | 146 | 2141 | 2025 (94%) | 73 | 48 |
| 3 | 2 | 0.19 s | 1.08 s | 219 | 2182 | 2138 (97%) | 188 | 137 |
| 4 | 3 | 0.18 s | 13.38 s | 135 | 2233 | 2182 (97%) | 1775 | 1593 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 4.99 s | 6.11 s | 43 | 2233 | 0 (0%) | 49 | 18 |
| 2 | 1 | 0.49 s | 4.33 s | 29 | 2361 | 2229 (94%) | 111 | 52 |
| 3 | 2 | 0.83 s | 3.85 s | 32 | 2449 | 2357 (96%) | 97 | 65 |
| 4 | 3 | 0.83 s | 8.79 s | 26 | 2506 | 2445 (97%) | 208 | 150 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.05 s | 1.76 s | 146 | 2023 | 0 (0%) | 99 | 67 |
| 2 | 1 | 0.17 s | 6.95 s | 100 | 2139 | 2023 (94%) | 673 | 601 |
| 3 | 2 | 0.18 s | 1.21 s | 133 | 2180 | 2134 (97%) | 133 | 97 |
| 4 | 3 | 0.19 s | 9.45 s | 100 | 2231 | 2180 (97%) | 931 | 827 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.83 s | 4.43 s | 90 | 2024 | 0 (0%) | 234 | 213 |
| 2 | 1 | 1.81 s | 3.01 s | 73 | 2137 | 0 (0%) | 89 | 71 |
| 3 | 2 | 1.65 s | 4.16 s | 42 | 2181 | 0 (0%) | 105 | 79 |
| 4 | 3 | 4.49 s | 30.94 s | 32 | 2232 | 0 (0%) | 845 | 802 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.69 s | 2.02 s | 40 | 2233 | 0 (0%) | 54 | 26 |
| 2 | 1 | 0.57 s | 3.81 s | 31 | 2361 | 0 (0%) | 101 | 49 |
| 3 | 2 | 0.66 s | 4.76 s | 26 | 2445 | 0 (0%) | 109 | 82 |
| 4 | 3 | 0.73 s | 3.69 s | 36 | 2503 | 0 (0%) | 109 | 62 |
