# HTTP client (urllib) on envoy

Measured 2026-09-30 19:45 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `urllib` from the standard library — no client library at all
- **Gateway**: envoy, `http://localhost:26000/v1/chat/completions`
- **Thinking level**: `reasoning_effort: medium` in every body
- **Streaming**: `stream: true` with `stream_options.include_usage`
- **Tool**: one function tool, `read_file`, answered by this script

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 39.68 s | 9.0 s | 4 | 1.02 s → 0.29 s | 111 | 2024 → 2206 | not reported | 675 |
| `lms-qwen38-27b` | LMStudio | ok | 14.23 s | 29.7 s | 4 | 2.62 s → 0.43 s | 32 | 2231 → 2466 | not reported | 706 |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.24 s | 9.0 s | 4 | 0.68 s → 0.16 s | 215 | 2024 → 2232 | 2181 (97%) | — |
| `unsloth-qwen38-27b` | Unsloth | ok | 12.76 s | 23.4 s | 4 | 5.71 s → 0.98 s | 26 | 2232 → 2467 | 2406 (97%) | — |
| `ollama-gemma4-26b` | Ollama | ok | 1.19 s | 23.6 s | 4 | 1.12 s → 0.20 s | 101 | 2023 → 2236 | 2180 (97%) | — |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.84 s | 26.9 s | 4 | 3.22 s → 1.80 s | 94 | 2024 → 2237 | 0 (0%) | 1400 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 1.27 s | 20.1 s | 4 | 0.64 s → 0.94 s | 29 | 2231 → 2466 | 0 (0%) | 401 |

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
| 1 | 1 | 1.02 s | 2.33 s | 97 | 2024 | not reported | 127 | 107 |
| 2 | 1 | 0.42 s | 1.27 s | 117 | 2111 | not reported | 101 | 84 |
| 3 | 2 | 0.27 s | 2.03 s | 113 | 2155 | not reported | 200 | 175 |
| 4 | 3 | 0.29 s | 3.37 s | 110 | 2206 | not reported | 340 | 309 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.62 s | 4.19 s | 30 | 2231 | not reported | 48 | 20 |
| 2 | 1 | 0.64 s | 2.32 s | 33 | 2359 | not reported | 57 | 39 |
| 3 | 2 | 0.38 s | 3.43 s | 33 | 2409 | not reported | 101 | 75 |
| 4 | 3 | 0.43 s | 19.79 s | 32 | 2466 | not reported | 613 | 572 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.68 s | 1.91 s | 173 | 2024 | 0 (0%) | 213 | — |
| 2 | 1 | 0.14 s | 0.81 s | 258 | 2140 | 2024 (94%) | 174 | — |
| 3 | 2 | 0.20 s | 0.94 s | 264 | 2181 | 2137 (97%) | 193 | — |
| 4 | 3 | 0.16 s | 5.32 s | 171 | 2232 | 2181 (97%) | 880 | — |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.71 s | 7.43 s | 33 | 2232 | 0 (0%) | 57 | — |
| 2 | 1 | 0.65 s | 4.39 s | 24 | 2360 | 2228 (94%) | 90 | — |
| 3 | 2 | 0.93 s | 4.17 s | 28 | 2410 | 2356 (97%) | 92 | — |
| 4 | 3 | 0.98 s | 7.38 s | 24 | 2467 | 2406 (97%) | 149 | — |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.12 s | 2.64 s | 100 | 2023 | 0 (0%) | 152 | — |
| 2 | 1 | 0.20 s | 1.16 s | 102 | 2139 | 2023 (94%) | 99 | — |
| 3 | 2 | 0.20 s | 1.18 s | 112 | 2180 | 2136 (97%) | 107 | — |
| 4 | 3 | 0.20 s | 18.62 s | 89 | 2236 | 2180 (97%) | 1631 | — |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.22 s | 5.36 s | 64 | 2024 | 0 (0%) | 136 | 115 |
| 2 | 1 | 2.16 s | 3.61 s | 85 | 2137 | 0 (0%) | 92 | 74 |
| 3 | 2 | 2.05 s | 5.46 s | 103 | 2181 | 0 (0%) | 230 | 199 |
| 4 | 3 | 1.80 s | 12.49 s | 104 | 2237 | 0 (0%) | 1058 | 1012 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.64 s | 2.95 s | 28 | 2231 | 0 (0%) | 64 | 36 |
| 2 | 1 | 0.51 s | 2.29 s | 44 | 2359 | 1568 (66%) | 79 | 61 |
| 3 | 2 | 0.64 s | 3.44 s | 29 | 2409 | 1568 (65%) | 82 | 56 |
| 4 | 3 | 0.94 s | 11.45 s | 29 | 2466 | 0 (0%) | 303 | 248 |
