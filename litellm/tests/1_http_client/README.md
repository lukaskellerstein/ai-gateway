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
know is to send the bytes yourself. A mistyped `api_base` in `../../config/` parses
perfectly and fails on the first call; this folder is where that shows up as an
HTTP status instead of a library traceback.

`run.py` deliberately does **not** catch `HTTPError` before printing the body — a
401 or a 404 with the gateway's own explanation is the answer you came for.

## The whole request

```http
POST http://localhost:24000/v1/chat/completions
Authorization: Bearer sk-litellm-master
Content-Type: application/json

{"model": "unsloth-gemma4-e4b", "messages": [{"role": "user", "content": "..."}], "reasoning_effort": "medium"}
```

Two headers. `Authorization` is enforced here — a bogus token gets **401**, which
is not true of the two sibling gateways.

## `max_tokens` is absent on purpose

The body spreads `body_extras()` from [`settings.py`](settings.py), which carries only
the thinking level on this gateway. LiteLLM stores a `max_tokens` on the route and every
local route in `../../config/` carries one, so a caller who sends none still gets a
bounded reply. The Envoy copy of this folder sends `max_tokens: 8192` instead,
because that gateway stores no default — the same script, one honest difference.

## Streaming, without a library

Each frame is one line, and the text is the concatenation of the `delta.content`
values. Assembling them is the entire job the SDK does for you here.

```
data: {"choices":[{"delta":{"content":"1"}}]}
data: [DONE]
```

Two things the loop has to survive, both found by running this same file against
every gateway this repo has had:

- **`choices` can be empty.** Envoy's last frame carries token usage and no choice
  at all, so `frame["choices"][0]` is an `IndexError` on a perfectly correct
  stream.
- **A frame can carry an `error` instead of a `delta`.** The HTTP status was 200
  and the stream opened; the gateway then failed inside its own code. The MLflow
  gateway did exactly that (`KeyError: 'finish_reason'`) before it was removed on
  2026-09-04, so the script checks for it **before** reaching for `choices` and
  reports **SKIPPED** — the plain call worked, so only the streaming path is
  missing. Keep the check: it costs two lines and it is the difference between
  "this gateway cannot stream" and "the reply was empty".

Streaming works here and on Envoy, with the identical script.

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
five. 0.2 s warm — see the note on timings in [`../README.md`](../README.md).
