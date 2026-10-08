# OpenAI Python client on envoy

Measured 2026-09-30 19:49 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `openai` 3.8.0, `OpenAI(base_url=…).chat.completions.create`
- **Gateway**: envoy, `http://localhost:26000/v1/chat/completions`
- **Thinking level**: `reasoning_effort='medium'` on every call
- **Every body carries**: `{"max_tokens": 8192, "reasoning_effort": "medium"}` — `settings.body_extras(alias)`
- **Streaming**: `stream=True` with `stream_options={'include_usage': True}`
- **Retries**: `max_retries=0` — a retried request would be timed as one
- **Timeout**: 3600 s per request
- **Tool**: one function tool, `read_file`, answered by this script; streamed pieces joined here
- **Prompt cache**: nothing to set on the client: each request resends the conversation unchanged, and the engine reuses the prefix it has already read

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 2.13 s | 13.7 s | 4 | 1.16 s → 0.34 s | 100 | 2025 → 2210 | not reported | 1011 |
| `lms-qwen38-27b` | LMStudio | ok | 2.63 s | 38.9 s | 4 | 4.69 s → 0.78 s | 29 | 2230 → 2460 | not reported | 797 |
| `unsloth-gemma4-26b` | Unsloth | ok | 16.58 s | 8.0 s | 4 | 0.83 s → 0.22 s | 135 | 2021 → 2229 | 2178 (97%) | — |
| `unsloth-qwen38-27b` | Unsloth | ok | 12.70 s | 27.2 s | 4 | 5.66 s → 0.88 s | 26 | 2231 → 2464 | 2403 (97%) | — |
| `ollama-gemma4-26b` | Ollama | ok | 1.07 s | 14.2 s | 4 | 1.12 s → 0.25 s | 112 | 2025 → 2238 | 2182 (97%) | — |
| `openrouter-gemma4-26b` | OpenRouter | ok | 1.14 s | 29.3 s | 4 | 1.46 s → 2.18 s | 101 | 2025 → 2239 | 0 (0%) | 1452 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.51 s | 25.1 s | 4 | 0.58 s → 5.52 s | 38 | 2232 → 2465 | 1568 (63%) | 272 |

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
| 1 | 1 | 1.16 s | 2.46 s | 87 | 2025 | not reported | 114 | 94 |
| 2 | 1 | 0.44 s | 1.34 s | 106 | 2112 | not reported | 97 | 82 |
| 3 | 2 | 0.29 s | 1.29 s | 104 | 2154 | not reported | 105 | 75 |
| 4 | 3 | 0.34 s | 8.62 s | 95 | 2210 | not reported | 792 | 760 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 4.69 s | 6.20 s | 32 | 2230 | not reported | 49 | 21 |
| 2 | 1 | 0.97 s | 4.92 s | 28 | 2358 | not reported | 112 | 99 |
| 3 | 2 | 0.62 s | 5.06 s | 29 | 2403 | not reported | 132 | 106 |
| 4 | 3 | 0.78 s | 22.75 s | 28 | 2460 | not reported | 616 | 571 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.83 s | 2.09 s | 136 | 2021 | 0 (0%) | 172 | — |
| 2 | 1 | 0.16 s | 0.75 s | 141 | 2137 | 2021 (94%) | 84 | — |
| 3 | 2 | 0.23 s | 1.09 s | 135 | 2178 | 2134 (97%) | 114 | — |
| 4 | 3 | 0.22 s | 4.11 s | 122 | 2229 | 2178 (97%) | 474 | — |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.66 s | 7.14 s | 38 | 2231 | 0 (0%) | 57 | — |
| 2 | 1 | 0.60 s | 4.12 s | 22 | 2359 | 2227 (94%) | 75 | — |
| 3 | 2 | 0.83 s | 7.04 s | 27 | 2407 | 2355 (97%) | 170 | — |
| 4 | 3 | 0.88 s | 8.86 s | 25 | 2464 | 2403 (97%) | 200 | — |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.12 s | 2.50 s | 112 | 2025 | 0 (0%) | 157 | — |
| 2 | 1 | 0.18 s | 1.16 s | 111 | 2141 | 2025 (94%) | 110 | — |
| 3 | 2 | 0.20 s | 1.47 s | 120 | 2182 | 2138 (97%) | 150 | — |
| 4 | 3 | 0.25 s | 9.10 s | 104 | 2238 | 2182 (97%) | 916 | — |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.46 s | 3.16 s | 91 | 2025 | 0 (0%) | 155 | 134 |
| 2 | 1 | 2.47 s | 4.56 s | 111 | 2138 | 0 (0%) | 231 | 213 |
| 3 | 2 | 1.70 s | 3.47 s | 110 | 2182 | 0 (0%) | 196 | 164 |
| 4 | 3 | 2.18 s | 18.11 s | 61 | 2239 | 0 (0%) | 978 | 941 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.58 s | 1.90 s | 43 | 2232 | 0 (0%) | 58 | 30 |
| 2 | 1 | 3.16 s | 5.12 s | 29 | 2360 | 0 (0%) | 57 | 41 |
| 3 | 2 | 5.00 s | 7.23 s | 39 | 2408 | 0 (0%) | 86 | 60 |
| 4 | 3 | 5.52 s | 10.88 s | 38 | 2465 | 1568 (63%) | 201 | 141 |
