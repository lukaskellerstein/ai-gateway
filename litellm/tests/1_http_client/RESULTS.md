# HTTP client (urllib) on litellm

Measured 2026-09-30 18:47 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: `urllib` from the standard library — no client library at all
- **Gateway**: litellm, `http://localhost:24000/v1/chat/completions`
- **Thinking level**: `reasoning_effort: medium` in every body
- **Streaming**: `stream: true` with `stream_options.include_usage`
- **Tool**: one function tool, `read_file`, answered by this script

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 0.98 s | 13.0 s | 4 | 0.73 s → 0.29 s | 110 | 2024 → 2206 | not reported | 1135 |
| `lms-qwen38-27b` | LMStudio | ok | 25.52 s | 19.5 s | 4 | 2.61 s → 0.44 s | 31 | 2231 → 2466 | not reported | 360 |
| `unsloth-gemma4-26b` | Unsloth | ok | 1.62 s | 5.3 s | 4 | 0.75 s → 0.22 s | 237 | 2025 → 2233 | 2182 (97%) | 633 |
| `unsloth-qwen38-27b` | Unsloth | ok | 21.97 s | 32.8 s | 4 | 6.41 s → 1.02 s | 23 | 2228 → 2501 | 2440 (97%) | 356 |
| `ollama-gemma4-26b` | Ollama | ok | 10.92 s | 16.1 s | 4 | 0.99 s → 0.26 s | 95 | 2024 → 2237 | 2181 (97%) | 1085 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 1.36 s | 30.2 s | 4 | 1.66 s → 1.35 s | 82 | 2024 → 2232 | 0 (0%) | 1375 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 0.62 s | 20.5 s | 4 | 0.56 s → 0.56 s | 43 | 2229 → 2460 | 0 (0%) | 686 |

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
| 1 | 1 | 0.73 s | 3.93 s | 104 | 2024 | not reported | 333 | 313 |
| 2 | 1 | 0.35 s | 2.04 s | 112 | 2111 | not reported | 191 | 174 |
| 3 | 2 | 0.25 s | 1.27 s | 114 | 2155 | not reported | 118 | 93 |
| 4 | 3 | 0.29 s | 5.73 s | 108 | 2206 | not reported | 589 | 555 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.61 s | 4.17 s | 31 | 2231 | not reported | 49 | 21 |
| 2 | 1 | 0.63 s | 3.32 s | 32 | 2359 | not reported | 87 | 69 |
| 3 | 2 | 0.39 s | 4.01 s | 32 | 2409 | not reported | 115 | 89 |
| 4 | 3 | 0.44 s | 8.01 s | 31 | 2466 | not reported | 237 | 181 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.75 s | 1.23 s | 232 | 2025 | 0 (0%) | 108 | 74 |
| 2 | 1 | 0.12 s | 0.99 s | 242 | 2141 | 2025 (94%) | 205 | 159 |
| 3 | 2 | 0.21 s | 1.02 s | 242 | 2182 | 2138 (97%) | 190 | 139 |
| 4 | 3 | 0.22 s | 2.12 s | 174 | 2233 | 2182 (97%) | 325 | 261 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 6.41 s | 8.65 s | 29 | 2228 | 0 (0%) | 60 | 29 |
| 2 | 1 | 0.69 s | 6.30 s | 22 | 2356 | 2224 (94%) | 126 | 67 |
| 3 | 2 | 1.08 s | 7.36 s | 24 | 2444 | 2352 (96%) | 150 | 118 |
| 4 | 3 | 1.02 s | 10.48 s | 22 | 2501 | 2440 (97%) | 208 | 142 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.99 s | 2.67 s | 134 | 2024 | 0 (0%) | 226 | 174 |
| 2 | 1 | 0.22 s | 2.03 s | 92 | 2140 | 2024 (94%) | 167 | 127 |
| 3 | 2 | 0.30 s | 2.47 s | 99 | 2181 | 2137 (97%) | 211 | 152 |
| 4 | 3 | 0.26 s | 8.97 s | 84 | 2237 | 2181 (97%) | 733 | 632 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.66 s | 3.67 s | 108 | 2024 | 0 (0%) | 218 | 197 |
| 2 | 1 | 1.15 s | 2.41 s | 76 | 2137 | 0 (0%) | 81 | 63 |
| 3 | 2 | 0.61 s | 1.67 s | 89 | 2181 | 2048 (93%) | 95 | 69 |
| 4 | 3 | 1.35 s | 22.44 s | 51 | 2232 | 0 (0%) | 1084 | 1046 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.56 s | 1.60 s | 47 | 2229 | 0 (0%) | 49 | 21 |
| 2 | 1 | 0.72 s | 5.03 s | 35 | 2357 | 0 (0%) | 152 | 138 |
| 3 | 2 | 0.42 s | 2.72 s | 39 | 2403 | 1568 (65%) | 90 | 64 |
| 4 | 3 | 0.56 s | 11.19 s | 49 | 2460 | 0 (0%) | 521 | 463 |
