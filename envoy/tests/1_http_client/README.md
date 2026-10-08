# 1 — HTTP client

The gateway with **no client library at all**: `urllib` from the standard library.
`pyproject.toml` lists no dependencies, and that is the point of the folder.

```bash
uv run run.py
uv run run.py --model lms-gemma4-26b
```

| What it does | Why it is here |
|:--|:--|
| `POST /v1/chat/completions` with a hand-built JSON body | the request every other folder wraps |
| the same body plus `"stream": true`, read frame by frame | shows the `data: {...}` SSE lines and the `[DONE]` sentinel an SDK hides |

## Why start here

"Use the OpenAI SDK" is good advice and bad debugging. When a call fails you have
to know whether the **gateway** or the **wrapper** was wrong, and the only way to
know is to send the bytes yourself. On this gateway that matters more than on the
other two: an alias with no `AIGatewayRoute` rule gets a plain **404** with nothing
in `compose logs` to explain it, because `AIGW_DEBUG` is `false` by default.

`run.py` deliberately does **not** catch `HTTPError` before printing the body.

## The whole request

```http
POST http://localhost:26000/v1/chat/completions
Content-Type: application/json

{"model": "unsloth-gemma4-e4b", "messages": [...], "max_tokens": 8192, "reasoning_effort": "medium"}
```

**No `Authorization` header is needed, and one would not be checked.** A bogus
`Bearer sk-wrong` gets 200 — `aigw run` authenticates no caller at all. The key that
matters is the one the gateway sends **upstream**, out of a `Secret` in
`../../config/<engine>.yaml`, and a caller never sees it.

The `model` field is doing more work here than it looks. The gateway copies it into
an `x-ai-eg-model` header and routes on **that**, then `modelNameOverride` rewrites
it to the engine's own id on the way out — which is why `response.model` comes back
as `unsloth/gemma-4-E4B-it-qat-GGUF` and not as the alias you sent.

## `max_tokens` is sent, and it is not optional

The body spreads `body_extras()` from [`settings.py`](settings.py), which carries
`max_tokens: 8192` here. An `AIGatewayRoute` rule carries a request
**timeout** but no token ceiling, so a caller who sends none gets an unbounded
reply. Measured 2026-09-04 with one "count to 3000" prompt:

| Gateway | `finish_reason` | completion tokens |
|:--|:--|--:|
| **Envoy** | `stop` | **13946** — nothing bounded it |
| LiteLLM, for contrast | `length` | 4095 — the route's stored 4096 |

## Streaming, and the empty last frame

Each frame is one line, and the text is the concatenation of the `delta.content`
values:

```
data: {"choices":[{"delta":{"content":"1"}}]}
data: [DONE]
```

**This gateway's last frame carries token usage and `"choices": []`.** Indexing
`frame["choices"][0]` on it is an `IndexError` on a perfectly correct stream, so
`run.py` skips a frame with no choices rather than indexing it. That guard is why
the identical script also runs against LiteLLM. It carries a second guard, for a
frame that carries an `error` instead of a `delta`: the MLflow gateway failed that
way before it was removed on 2026-09-04, and the guard reports SKIPPED rather than
an empty reply.

## Copy this folder

`settings.py` is **the one file to edit** when you take this folder into another
project: the URL, the key, the default model, the thinking level, and what every
request body must carry on this gateway. Every other file is byte-identical to the
same folder in the other project and names no port, key or model.

**The thinking level is sent on every request** — `reasoning_effort: medium`. Qwen 3.8
defaults to `xhigh`, where one agent step took 693 s and answered nothing (2026-09-30).

## What it costs, per model — `run_benchmark.py`

```bash
uv run run_benchmark.py                                  # every default model, writes RESULTS.md
uv run run_benchmark.py --aliases lms-gemma4-26b --no-write
```

The same three-turn task as every other folder — a ~1500-token policy, `read_file` on
`order.json`, a follow-up, a customer message — streamed, so each request's first
token, decode speed and cache count are read off the wire. The numbers are in
[`RESULTS.md`](RESULTS.md); the task and the table are the shared part at the
bottom of `run_benchmark.py`, byte-identical in all fourteen folders. OpenRouter rows cost money.

## One file, two gateways

`run.py` and `run_benchmark.py` are **byte-identical** in both projects, and the shared
part of `run_benchmark.py` is the same in every folder. Everything specific comes from
`settings.py`.

## Verified

2026-09-04, `unsloth-gemma4-e4b`: the plain call returned Paris and the stream counted to
five, past the empty last frame. 0.2 s warm.
