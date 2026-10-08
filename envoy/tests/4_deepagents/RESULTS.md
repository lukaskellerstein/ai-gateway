# deepagents on envoy

Measured 2026-09-30 19:11 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: deepagents 0.7.13 `create_deep_agent` on `ChatOpenAI` (langchain-openai 1.6.0)
- **Gateway**: envoy, `http://localhost:26000/v1/chat/completions`
- **Thinking level**: `reasoning_effort='medium'` on ChatOpenAI, in every body
- **Ceiling**: `max_tokens=8192` on ChatOpenAI, sent as `max_completion_tokens`
- **Streaming**: `streaming=True` and `stream_usage=True`, so every body carries `stream_options.include_usage`
- **Conversation**: one thread per session — an `InMemorySaver` checkpointer and one `thread_id` — so turns 2 and 3 resend the whole history
- **Harness**: the default deep-agent harness: its system prompt and a dozen tool schemas come first in every request and carry no per-request value, so they are a prefix the engine can reuse
- **File tool**: the agent's own `read_file`, on `FilesystemBackend(root_dir=<temp dir>, virtual_mode=True)` holding a real `order.json`
- **Sampling and retries**: `temperature=0`, `max_retries=0`

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 4.01 s | 10.5 s | 5 | 1.57 s → 0.44 s | 98 | 4351 → 4605 | not reported | 621 |
| `lms-qwen38-27b` | LMStudio | ok | 2.67 s | 21.7 s | 5 | 3.56 s → 0.64 s | 31 | 4707 → 5009 | not reported | 316 |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.36 s | 6.9 s | 4 | 1.89 s → 0.19 s | 153 | 4359 → 4580 | 4529 (98%) | — |
| `unsloth-qwen38-27b` | Unsloth | ok | 17.59 s | 26.3 s | 5 | 10.32 s → 0.94 s | 31 | 4706 → 5000 | 4939 (98%) | — |
| `ollama-gemma4-26b` | Ollama | ok | 12.35 s | 12.3 s | 4 | 2.50 s → 0.19 s | 124 | 4343 → 4569 | 4513 (98%) | — |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.65 s | 25.2 s | 5 | 1.75 s → 1.85 s | 62 | 4379 → 4630 | 0 (0%) | 613 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 0.51 s | 8.7 s | 4 | 0.78 s → 0.43 s | 53 | 4707 → 4950 | 4704 (95%) | 135 |

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
- **Requests** are every model request the agent made, counted by a LangChain callback on the model — a subagent's or a summary's included — each under the turn that caused it.
- **First token** is the first streamed chunk of ANY kind: ChatOpenAI drops `reasoning_content`, so a thinking token arrives as an empty chunk. The closing frames land in the same millisecond as the last token, so they do not stretch the decode window.
- **Cached** is `not reported` when the reply has no `cached_tokens`: langchain-openai leaves `cache_read` out of `usage_metadata` rather than writing 0, so the SDK hides nothing here.
- **Thinking** is counted by the engine but never re-enters the conversation: ChatOpenAI drops the text, so a later request does not resend it.

## Every request

**`lms-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.57 s | 3.22 s | 98 | 4351 | not reported | 162 | 146 |
| 2 | 1 | 0.32 s | 0.61 s | 81 | 4380 | not reported | 24 | 1 |
| 3 | 1 | 0.31 s | 1.00 s | 106 | 4510 | not reported | 74 | 57 |
| 4 | 2 | 0.37 s | 1.43 s | 96 | 4554 | not reported | 103 | 78 |
| 5 | 3 | 0.44 s | 4.04 s | 103 | 4605 | not reported | 370 | 339 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 3.56 s | 4.82 s | 32 | 4707 | not reported | 41 | 12 |
| 2 | 1 | 0.54 s | 1.65 s | 32 | 4756 | not reported | 36 | 7 |
| 3 | 1 | 0.99 s | 4.84 s | 31 | 4896 | not reported | 119 | 95 |
| 4 | 2 | 0.54 s | 4.86 s | 30 | 4952 | not reported | 132 | 106 |
| 5 | 3 | 0.64 s | 5.48 s | 30 | 5009 | not reported | 147 | 96 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.89 s | 2.49 s | 153 | 4359 | 0 (0%) | 93 | — |
| 2 | 1 | 0.17 s | 0.81 s | 167 | 4488 | 4359 (97%) | 107 | — |
| 3 | 2 | 0.20 s | 0.85 s | 153 | 4529 | 4485 (99%) | 102 | — |
| 4 | 3 | 0.19 s | 2.73 s | 132 | 4580 | 4529 (98%) | 336 | — |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 10.32 s | 12.01 s | 34 | 4706 | 0 (0%) | 59 | — |
| 2 | 1 | 0.49 s | 1.63 s | 32 | 4755 | 4702 (98%) | 37 | — |
| 3 | 1 | 0.93 s | 2.02 s | 30 | 4895 | 4751 (97%) | 34 | — |
| 4 | 2 | 0.81 s | 3.51 s | 31 | 4943 | 4891 (98%) | 85 | — |
| 5 | 3 | 0.94 s | 7.13 s | 24 | 5000 | 4939 (98%) | 149 | — |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 2.50 s | 3.23 s | 131 | 4343 | 0 (0%) | 97 | — |
| 2 | 1 | 0.19 s | 0.90 s | 122 | 4472 | 4343 (97%) | 89 | — |
| 3 | 2 | 0.17 s | 1.04 s | 125 | 4513 | 4469 (99%) | 109 | — |
| 4 | 3 | 0.19 s | 6.91 s | 112 | 4569 | 4513 (98%) | 751 | — |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.75 s | 3.32 s | 71 | 4379 | 0 (0%) | 112 | 95 |
| 2 | 1 | 3.16 s | 4.14 s | 23 | 4408 | 0 (0%) | 24 | 0 |
| 3 | 1 | 5.24 s | 6.42 s | 62 | 4535 | 0 (0%) | 74 | 56 |
| 4 | 2 | 3.29 s | 5.45 s | 47 | 4579 | 0 (0%) | 103 | 77 |
| 5 | 3 | 1.85 s | 5.83 s | 106 | 4630 | 0 (0%) | 423 | 385 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.78 s | 1.70 s | 56 | 4707 | 0 (0%) | 52 | 23 |
| 2 | 1 | 1.10 s | 1.47 s | 59 | 4847 | 0 (0%) | 23 | 9 |
| 3 | 2 | 0.39 s | 1.95 s | 50 | 4893 | 4704 (96%) | 79 | 53 |
| 4 | 3 | 0.43 s | 3.54 s | 27 | 4950 | 4704 (95%) | 86 | 50 |
