# tests — drive the MLflow gateway through the OpenAI client

Four scripts, each run against **this project's gateway on 25000**. Three prove a
kind of call works; the fourth proves this gateway's calling contract is still
what `common.py` says it is.

| Script | What it proves |
|:--|:--|
| `01_simple_call.py` | a plain chat completion, with a multi-turn conversation |
| `02_tools_call.py` | tools: a structured `tool_calls` reply, then the second turn that uses the tool result |
| `03_multimodal.py` | an image plus a question, sent as a base64 `data:` URL |
| `04_gateway_contract.py` | **this gateway's contract**, and that `common.py`'s table still describes it |
| `run_all.py` | runs all four and prints a pass/fail table |

Every script prints the **full** response and then the extracted text, so it
doubles as a sample to copy from.

> **This suite drives one gateway.** Until 2026-09-03 there was one `tests/` at the
> repo root that ran every script against 24000 **and** 25000, and it was the thing
> that caught the two alias lists drifting apart. Each gateway is a standalone
> compose project now, so that check has no owner: **nothing here, and nothing
> anywhere in the repo, verifies that an alias answering on 25000 also answers on
> 24000.** Call both ports by hand when it matters.

## The calling contract

`common.py` declares four things about how to call this gateway, and
`04_gateway_contract.py` checks every one against reality. **All four are `False`**,
and checking a `False` is the point: an absence nobody checks is an absence somebody
eventually assumes away.

| | MLflow `:25000` |
|:--|:--|
| `checks_api_key` | **False** — a bogus Bearer token gets 200. No key concept at all |
| `lists_models` | **False** — `GET /models` returns 404 |
| `echoes_alias` | **False** — `response.model` is `google/gemma-4-e4b`, the engine's own id |
| `exposes_route_limits` | **False** — no `/model/info` route, because nothing stores a ceiling |

The failure message is always "the table says X and the gateway did Y", which is
the sentence you want. `../../litellm/tests/` declares the opposite four against its
own gateway and checks them the same way.

## `body_extras` carries `max_tokens`, and it is load-bearing

The last row above is the one that costs an afternoon. MLflow's endpoints are
database rows with no field for a default ceiling. Measured 2026-09-03 with
`lms-4b`, one "count to 3000" prompt carrying **no** `max_tokens`:

| Gateway | `finish_reason` | completion tokens |
|:--|:--|--:|
| **MLflow** | `stop` | **13961** — nothing bounded it |
| LiteLLM, for contrast | `length` | 4095 — the route's stored 4096 |

Same prompt, same weights, 3.4× the output and 3.4× the wait. So **here you always
send `max_tokens` yourself**. That is what `Gateway.body_extras` carries, and every
scenario spreads it:

```python
response = client_for(gateway).chat.completions.create(
    model=model,
    messages=CONVERSATION,
    **gateway.body_extras,      # {"max_tokens": 2048} on this gateway
)
```

A scenario spreads `body_extras` and reads nothing else off `gateway`, so it cannot
grow gateway-specific behaviour by accident.

**Sent explicitly, `max_tokens` behaves normally** — including the trap where a
reasoning model spends the whole allowance thinking and returns empty content with
`finish_reason: "length"` and no error. Only the *default* is missing.

## Run

The gateway must be up first — `docker compose up -d` in the parent directory.

```bash
cd tests
uv sync                     # once
uv run run_all.py           # all four
```

One at a time:

```bash
uv run 01_simple_call.py
uv run 02_tools_call.py --model lms-26b
uv run 03_multimodal.py --model ollama-4b
```

Every script exits `0` on pass and `1` on fail, so they work in a shell chain.
`run_all.py` refuses to start if 25000 is not answering, rather than letting four
scripts fail the same way.

## Flags

| Flag | Default | Meaning |
|:--|:--|:--|
| `--model <alias>` | follows `GATEWAY_ENGINE` | the alias to call — see below. Also settable with `AI_GATEWAY_TEST_MODEL` |
| `--verbose` (`run_all.py` only) | off | stream each script's output instead of capturing it |

There is no `--gateway` flag any more. The folder you are in is the gateway.

## Reasoning aliases and `MAX_TOKENS`

`common.py` sends `max_tokens=2048`, and that number is load-bearing. Every
`unsloth-*` and `ollama-*` route, and `lms-4b` too, spends the same allowance on a
reasoning block before writing a word. Run out mid-thought and the reply is
**empty**, with `finish_reason: "length"` and no error at all.

`answer_of()` names that case rather than reporting a bare "empty content":

```
CheckFailed: empty content, finish_reason='length': the model spent its whole token
allowance (2048) on a reasoning block (612 chars) and never started the reply. Raise
MAX_TOKENS in common.py.
```

Raising the ceiling costs nothing when a model does not need it — generation stops
at `stop`, not at the ceiling.

## Why the default alias follows `GATEWAY_ENGINE`

**One engine runs at a time**, so the endpoints of every other engine are not seeded
at all. A fixed `lms-4b` default would therefore 404 on a perfectly healthy gateway
serving Ollama.

`common.py` reads `GATEWAY_ENGINE` from `../.env` — this project's own, not a
repo-root one, and not the same file `../../litellm` reads — and picks that engine's
small chat route: `lms-4b`, `unsloth-4b`, `ollama-4b` or `openrouter-26b`. Each is
the one alias on its engine that is both vision- and tool-capable, which all three
scripts need from a single loaded model.

**An unrecognised engine is an error, not a fallback.** Defaulting quietly produced a
404 from a healthy gateway, which reads as a broken gateway rather than a stale
`.env`. `openai` maps to nothing on purpose — `gpt-5.4-mini` has no vision, so
`03_multimodal.py` cannot pass against it.

`AI_GATEWAY_TEST_MODEL` overrides the choice permanently; `--model` for one run.

**On LMStudio the model must be loaded first** — `lms ps --json` is the truth, not
the LMStudio UI. A JIT load comes back at 8192 context with a 1 h TTL. Ollama loads
on demand and needs none of this.

```bash
lms load google/gemma-4-e4b --context-length 131072 --parallel 1 --gpu max
```

## The same test on another engine

The suite doubles as an engine comparison, but only one engine is served at a time —
so it is a restart between runs, not a second `--model`:

```bash
# in ../.env: GATEWAY_ENGINE=lms      then  (cd .. && docker compose up -d)
uv run run_all.py
# in ../.env: GATEWAY_ENGINE=ollama   then  (cd .. && docker compose up -d)
uv run run_all.py
```

Changing the engine leaves the **old** endpoints in place — the seed never deletes
without `--prune` — so an alias from the previous engine keeps answering here after
`../../litellm` has stopped serving it. [`../README.md`](../README.md) has the
`--prune` warning.

Verified 2026-09-03: **4/4 on `unsloth-4b`**, with the LiteLLM project also running.
Verified 2026-08-27 on the pre-split suite: 6/6 on each of `lms`, `ollama` and
`unsloth`, across both gateways.

Two extra requirements for the Unsloth one, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `docker compose up -d`, or
   the seed skips every `unsloth-*` endpoint and they 404 here.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. With it on, the first call unloads whatever was there and
   reads the new weights from disk, which shows up as one slow row and then nothing.
   Note that this covers the embedder too: `unsloth-embed` and `unsloth-4b` evict
   each other — and so does the LiteLLM project, if it is up on the same engine.

## `test_image.png`

256x256, one red circle on a white background, 977 bytes. Deliberately
unambiguous so `03_multimodal.py` can check for `red` and for a round shape
without depending on how wordy the model is.

## Adding a test

Name it `05_something.py`, write one `scenario(gateway, model)` function, and end
it with `sys.exit(run(scenario, "Test 5 — ..."))`. `run_all.py` globs `NN_*.py`,
so it picks the new file up with no edit.

**Send `**gateway.body_extras` in every request.** On this gateway it carries the
`max_tokens` a scenario would otherwise have to remember, and it is what lets the
same scenario file be copied to the LiteLLM project unchanged.

## What is NOT tested here

- **Embeddings.** Every `*-embed` alias needs a different route here
  (`/gateway/openai/v1/embeddings`), not the chat one these scripts share.
- **`/v1/messages`.** This gateway does not have it. That is a LiteLLM route.
- **Fallback chains.** No endpoint has one, so there is nothing to prove.
- **`openrouter-free`.** Absent here by design — MLflow cannot carry the provider
  pin.
- **That the same alias answers on 24000.** See the note at the top — no suite
  checks this any more.
