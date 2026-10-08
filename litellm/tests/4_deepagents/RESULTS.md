# deepagents on litellm

Measured 2026-09-30 19:08 UTC by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`order.json` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

- **Client**: deepagents 0.7.13 `create_deep_agent` on `ChatOpenAI` (langchain-openai 1.6.0)
- **Gateway**: litellm, `http://localhost:24000/v1/chat/completions`
- **Thinking level**: `reasoning_effort='medium'` on ChatOpenAI, in every body
- **Ceiling**: none sent — the gateway's route stores one
- **Streaming**: `streaming=True` and `stream_usage=True`, so every body carries `stream_options.include_usage`
- **Conversation**: one thread per session — an `InMemorySaver` checkpointer and one `thread_id` — so turns 2 and 3 resend the whole history
- **Harness**: the default deep-agent harness: its system prompt and a dozen tool schemas come first in every request and carry no per-request value, so they are a prefix the engine can reuse
- **File tool**: the agent's own `read_file`, on `FilesystemBackend(root_dir=<temp dir>, virtual_mode=True)` holding a real `order.json`
- **Sampling and retries**: `temperature=0`, `max_retries=0`

## The numbers

| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request | Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `lms-gemma4-26b` | LMStudio | ok | 2.20 s | 10.3 s | 5 | 1.42 s → 0.38 s | 99 | 4348 → 4602 | not reported | 583 |
| `lms-qwen38-27b` | LMStudio | ok | 2.57 s | 23.8 s | 5 | 5.15 s → 0.76 s | 30 | 4702 → 5031 | not reported | 271 |
| `unsloth-gemma4-26b` | Unsloth | ok | 17.09 s | 10.2 s | 4 | 1.97 s → 0.21 s | 144 | 4358 → 4584 | 4528 (98%) | 792 |
| `unsloth-qwen38-27b` | Unsloth | ok | 12.67 s | 26.2 s | 5 | 10.10 s → 0.83 s | 31 | 4703 → 4997 | 4936 (98%) | 198 |
| `ollama-gemma4-26b` | Ollama | ok | 7.33 s | 12.2 s | 4 | 1.89 s → 0.17 s | 147 | 4345 → 4566 | 4515 (98%) | 896 |
| `openrouter-gemma4-26b` | OpenRouter | ok | 0.54 s | 24.4 s | 5 | 1.79 s → 3.37 s | 112 | 4377 → 4628 | 0 (0%) | 735 |
| `openrouter-qwen38-27b` | OpenRouter | ok | 10.76 s | 37.9 s | 4 | 0.61 s → 11.40 s | 35 | 4704 → 4983 | 4704 (94%) | 199 |

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
| 1 | 1 | 1.42 s | 2.65 s | 93 | 4348 | not reported | 116 | 100 |
| 2 | 1 | 0.63 s | 0.95 s | 73 | 4377 | not reported | 24 | 1 |
| 3 | 1 | 0.32 s | 1.04 s | 112 | 4507 | not reported | 82 | 65 |
| 4 | 2 | 0.33 s | 1.31 s | 105 | 4551 | not reported | 103 | 78 |
| 5 | 3 | 0.38 s | 4.12 s | 99 | 4602 | not reported | 370 | 339 |

**`lms-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 5.15 s | 6.93 s | 32 | 4702 | not reported | 58 | 29 |
| 2 | 1 | 0.67 s | 1.84 s | 30 | 4751 | not reported | 36 | 7 |
| 3 | 1 | 1.14 s | 6.13 s | 29 | 4891 | not reported | 146 | 95 |
| 4 | 2 | 0.65 s | 2.57 s | 31 | 4974 | not reported | 61 | 35 |
| 5 | 3 | 0.76 s | 6.32 s | 29 | 5031 | not reported | 161 | 105 |

**`unsloth-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.97 s | 2.60 s | 146 | 4358 | 0 (0%) | 93 | 59 |
| 2 | 1 | 0.18 s | 0.84 s | 161 | 4487 | 4358 (97%) | 107 | 77 |
| 3 | 2 | 0.22 s | 0.97 s | 142 | 4528 | 4484 (99%) | 107 | 66 |
| 4 | 3 | 0.21 s | 5.79 s | 124 | 4584 | 4528 (98%) | 693 | 590 |

**`unsloth-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 10.10 s | 11.84 s | 33 | 4703 | 0 (0%) | 59 | 27 |
| 2 | 1 | 0.52 s | 1.59 s | 33 | 4752 | 4699 (98%) | 36 | 6 |
| 3 | 1 | 0.85 s | 1.92 s | 31 | 4892 | 4748 (97%) | 34 | 15 |
| 4 | 2 | 0.78 s | 3.53 s | 31 | 4940 | 4888 (98%) | 85 | 53 |
| 5 | 3 | 0.83 s | 7.31 s | 23 | 4997 | 4936 (98%) | 149 | 97 |

**`ollama-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.89 s | 2.52 s | 155 | 4345 | 0 (0%) | 99 | 65 |
| 2 | 1 | 0.16 s | 0.76 s | 149 | 4474 | 4345 (97%) | 90 | 63 |
| 3 | 2 | 0.17 s | 0.89 s | 144 | 4515 | 4471 (99%) | 105 | 69 |
| 4 | 3 | 0.17 s | 8.00 s | 105 | 4566 | 4515 (98%) | 826 | 699 |

**`openrouter-gemma4-26b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 1.79 s | 2.67 s | 130 | 4377 | 0 (0%) | 116 | 99 |
| 2 | 1 | 4.93 s | 4.95 s | 1307 | 4406 | 0 (0%) | 24 | 0 |
| 3 | 1 | 3.24 s | 4.78 s | 53 | 4533 | 0 (0%) | 82 | 64 |
| 4 | 2 | 2.85 s | 3.85 s | 102 | 4577 | 0 (0%) | 103 | 77 |
| 5 | 3 | 3.37 s | 8.12 s | 112 | 4628 | 0 (0%) | 534 | 495 |

**`openrouter-qwen38-27b`**

| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1 | 0.61 s | 2.38 s | 29 | 4704 | 0 (0%) | 52 | 23 |
| 2 | 1 | 0.64 s | 2.99 s | 41 | 4844 | 0 (0%) | 97 | 47 |
| 3 | 2 | 1.39 s | 18.31 s | 6 | 4926 | 0 (0%) | 95 | 69 |
| 4 | 3 | 11.40 s | 14.15 s | 42 | 4983 | 4704 (94%) | 117 | 60 |
