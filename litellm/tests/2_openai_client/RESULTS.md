# OpenAI Python client on litellm

Measured 2026-09-30 18:54 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `openai` 3.8.0, `OpenAI(base_url=…).chat.completions.create`
- **Gateway**: litellm, `http://localhost:24000/v1/chat/completions`
- **Thinking level**: `reasoning_effort='medium'` on every call
- **Every body carries**: `{"reasoning_effort": "medium"}` — `settings.body_extras(alias)`
- **Streaming**: `stream=True` with `stream_options={'include_usage': True}`
- **Retries**: `max_retries=0` — a retried request would be timed as one
- **Timeout**: 3600 s per request
- **Tool**: one function tool, `read_file`, answered by this script; streamed pieces joined here
- **Prompt cache**: nothing to set on the client: each request resends the conversation unchanged, and the engine reuses the prefix it has already read

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 12.73 s | 9.3 s | 4 | 1.32 s → 0.36 s | 103 | 2020 → 2207 | not reported | 600 |
| `lms-qwen38-27b` | LMStudio | ok | 4.55 s | 24.0 s | 4 | 2.94 s → 0.68 s | 31 | 2233 → 2473 | not reported | 437 |
| `unsloth-gemma4-26b` | Unsloth | ok | 16.77 s | 6.8 s | 4 | 0.77 s → 0.21 s | 161 | 2022 → 2233 | 2179 (97%) | 616 |
| `unsloth-qwen38-27b` | Unsloth | ok | 15.12 s | 20.2 s | 4 | 5.18 s → 0.85 s | 30 | 2230 → 2465 | 2404 (97%) | 245 |
| `ollama-gemma4-26b` | Ollama | ok | 3.86 s | 11.6 s | 4 | 0.87 s → 0.25 s | 145 | 2024 → 2238 | 2181 (97%) | 1021 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.67 s | 28.6 s | 4 | 2.24 s → 2.14 s | 72 | 2025 → 2239 | 0 (0%) | 1408 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.12 s | 14.1 s | 4 | 0.60 s → 0.60 s | 41 | 2231 → 2503 | 0 (0%) | 342 |

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


## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.32 s | 2.63 s | 87 | 2020 | not reported | 112 | 92 |
| 2 | 1 | 0.44 s | 2.09 s | 107 | 2107 | not reported | 177 | 160 |
| 3 | 2 | 0.29 s | 1.28 s | 103 | 2151 | not reported | 103 | 73 |
| 4 | 3 | 0.36 s | 3.32 s | 103 | 2207 | not reported | 305 | 275 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.94 s | 4.47 s | 32 | 2233 | not reported | 49 | 21 |
| 2 | 1 | 0.69 s | 2.71 s | 32 | 2361 | not reported | 66 | 43 |
| 3 | 2 | 0.60 s | 5.65 s | 30 | 2416 | not reported | 151 | 125 |
| 4 | 3 | 0.68 s | 11.16 s | 29 | 2473 | not reported | 309 | 248 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.77 s | 1.45 s | 169 | 2022 | 0 (0%) | 115 | 80 |
| 2 | 1 | 0.16 s | 0.87 s | 168 | 2138 | 2022 (94%) | 115 | 85 |
| 3 | 2 | 0.24 s | 2.49 s | 141 | 2179 | 2135 (97%) | 317 | 251 |
| 4 | 3 | 0.21 s | 1.99 s | 154 | 2233 | 2179 (97%) | 270 | 200 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.18 s | 6.41 s | 42 | 2230 | 0 (0%) | 48 | 17 |
| 2 | 1 | 0.50 s | 2.35 s | 31 | 2358 | 2226 (94%) | 58 | 37 |
| 3 | 2 | 0.82 s | 5.00 s | 29 | 2408 | 2354 (97%) | 121 | 89 |
| 4 | 3 | 0.85 s | 6.40 s | 26 | 2465 | 2404 (97%) | 148 | 102 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.87 s | 1.41 s | 177 | 2024 | 0 (0%) | 91 | 60 |
| 2 | 1 | 0.14 s | 1.10 s | 176 | 2140 | 2024 (94%) | 167 | 127 |
| 3 | 2 | 0.16 s | 3.25 s | 115 | 2181 | 2137 (97%) | 353 | 296 |
| 4 | 3 | 0.25 s | 5.80 s | 110 | 2238 | 2181 (97%) | 609 | 538 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.24 s | 4.12 s | 79 | 2025 | 0 (0%) | 146 | 125 |
| 2 | 1 | 2.63 s | 4.72 s | 63 | 2138 | 0 (0%) | 91 | 73 |
| 3 | 2 | 1.23 s | 3.93 s | 66 | 2182 | 2048 (93%) | 178 | 146 |
| 4 | 3 | 2.14 s | 15.82 s | 81 | 2239 | 0 (0%) | 1097 | 1064 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.60 s | 1.74 s | 47 | 2231 | 0 (0%) | 53 | 25 |
| 2 | 1 | 0.73 s | 2.01 s | 90 | 2370 | 0 (0%) | 116 | 62 |
| 3 | 2 | 0.60 s | 3.33 s | 36 | 2446 | 0 (0%) | 98 | 72 |
| 4 | 3 | 0.60 s | 6.99 s | 34 | 2503 | 0 (0%) | 219 | 183 |
