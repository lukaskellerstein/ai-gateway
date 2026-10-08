# LangChain + LangGraph on envoy

Measured 2026-09-30 19:52 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `ChatOpenAI` from `langchain-openai`, inside a LangGraph `StateGraph` — model node, `ToolNode`, `tools_condition` — with an `InMemorySaver` holding the conversation
- **Gateway**: envoy, `http://localhost:26000/v1/chat/completions`
- **Thinking level**: `reasoning_effort="medium"` on ChatOpenAI, in every body
- **Ceiling**: `max_tokens=8192` on ChatOpenAI, sent as `max_completion_tokens`
- **Streaming**: `streaming=True`, `stream_usage=True` — ChatOpenAI turns streamed usage off by itself once `base_url` is set
- **Retries and sampling**: `max_retries=0`; no temperature sent, so the engine's default
- **Tool**: one `StructuredTool`, `read_file`, carrying the task's JSON schema; `ToolNode` runs it
- **Measured**: per model request, by a callback handler: `on_chat_model_start` to the first and last streamed chunk, then `usage_metadata` in `on_llm_end`

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 2.22 s | 17.7 s | 4 | 1.01 s → 0.30 s | 102 | 2021 → 2203 | not reported | 1479 |
| `lms-qwen38-27b` | LMStudio | ok | 2.62 s | 39.0 s | 4 | 4.21 s → 0.65 s | 30 | 2230 → 2466 | not reported | 844 |
| `unsloth-gemma4-26b` | Unsloth | ok | 16.88 s | 14.9 s | 4 | 0.76 s → 0.19 s | 157 | 2025 → 2238 | 2182 (97%) | — |
| `unsloth-qwen38-27b` | Unsloth | ok | 12.68 s | 24.0 s | 4 | 5.74 s → 0.87 s | 27 | 2230 → 2465 | 2404 (97%) | — |
| `ollama-gemma4-26b` | Ollama | ok | 1.25 s | 15.4 s | 4 | 1.07 s → 0.18 s | 111 | 2021 → 2229 | 2178 (97%) | — |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.65 s | 41.6 s | 4 | 1.40 s → 1.82 s | 71 | 2025 → 2233 | 0 (0%) | 1907 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.13 s | 12.2 s | 4 | 0.58 s → 0.86 s | 45 | 2231 → 2461 | 0 (0%) | 323 |

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
| 1 | 1 | 1.01 s | 2.59 s | 98 | 2021 | not reported | 155 | 135 |
| 2 | 1 | 0.41 s | 3.88 s | 103 | 2108 | not reported | 357 | 340 |
| 3 | 2 | 0.28 s | 1.96 s | 104 | 2152 | not reported | 176 | 151 |
| 4 | 3 | 0.30 s | 9.03 s | 101 | 2203 | not reported | 884 | 853 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 4.21 s | 5.75 s | 32 | 2230 | not reported | 49 | 21 |
| 2 | 1 | 0.76 s | 6.19 s | 29 | 2358 | not reported | 161 | 143 |
| 3 | 2 | 0.53 s | 5.73 s | 30 | 2408 | not reported | 155 | 128 |
| 4 | 3 | 0.65 s | 21.35 s | 29 | 2466 | not reported | 600 | 552 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.76 s | 1.43 s | 165 | 2025 | 0 (0%) | 110 | — |
| 2 | 1 | 0.15 s | 0.61 s | 150 | 2141 | 2025 (94%) | 66 | — |
| 3 | 2 | 0.19 s | 1.41 s | 166 | 2182 | 2138 (97%) | 200 | — |
| 4 | 3 | 0.19 s | 11.46 s | 130 | 2238 | 2182 (97%) | 1470 | — |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.74 s | 7.22 s | 38 | 2230 | 0 (0%) | 57 | — |
| 2 | 1 | 0.58 s | 4.99 s | 22 | 2358 | 2226 (94%) | 97 | — |
| 3 | 2 | 0.87 s | 5.05 s | 29 | 2408 | 2354 (97%) | 123 | — |
| 4 | 3 | 0.87 s | 6.69 s | 24 | 2465 | 2404 (97%) | 139 | — |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.07 s | 2.63 s | 104 | 2021 | 0 (0%) | 160 | — |
| 2 | 1 | 0.18 s | 1.07 s | 118 | 2137 | 2021 (94%) | 102 | — |
| 3 | 2 | 0.18 s | 1.09 s | 132 | 2178 | 2134 (97%) | 116 | — |
| 4 | 3 | 0.18 s | 10.62 s | 97 | 2229 | 2178 (97%) | 1014 | — |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.40 s | 2.49 s | 96 | 2025 | 0 (0%) | 105 | 84 |
| 2 | 1 | 4.41 s | 7.49 s | 46 | 2138 | 0 (0%) | 140 | 122 |
| 3 | 2 | 3.37 s | 14.08 s | 18 | 2182 | 0 (0%) | 188 | 162 |
| 4 | 3 | 1.82 s | 17.53 s | 104 | 2233 | 0 (0%) | 1581 | 1539 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.58 s | 1.69 s | 45 | 2231 | 0 (0%) | 49 | 21 |
| 2 | 1 | 0.54 s | 1.75 s | 56 | 2359 | 0 (0%) | 69 | 56 |
| 3 | 2 | 0.45 s | 2.10 s | 45 | 2404 | 0 (0%) | 75 | 49 |
| 4 | 3 | 0.86 s | 6.61 s | 42 | 2461 | 0 (0%) | 245 | 197 |
