# tests — drive the Envoy AI Gateway through the OpenAI client

Four scripts, each run against **this project's gateway on 26000**. Three prove a
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
> anywhere in the repo, verifies that an alias answering on 26000 also answers on
> 24000 or 25000.** Call the other ports by hand when it matters.

## The calling contract

`common.py` declares four things about how to call this gateway, and
`04_gateway_contract.py` checks every one against reality. **Three are `False`**, and
checking a `False` is the point: an absence nobody checks is an absence somebody
eventually assumes away.

| | Envoy `:26000` |
|:--|:--|
| `checks_api_key` | **False** — a bogus Bearer token gets 200. `aigw run` authenticates no caller at all |
| `lists_models` | **True** — `GET /models` returns the alias list, built from the AIGatewayRoute rules |
| `echoes_alias` | **False** — `response.model` is `google/gemma-4-e4b`; `modelNameOverride` rewrote it and nothing undoes that |
| `exposes_route_limits` | **False** — no `/model/info` route, and a route rule carries a timeout but no token ceiling |

**THIS GATEWAY IS A THIRD ROW, not a copy of either other one.** It lists its models
like LiteLLM and checks no key like MLflow, so a test that assumed "LiteLLM or
not-LiteLLM" would be wrong about it. That is exactly why each project declares and
checks its own table, and why the failure message is always "the table says X and the
gateway did Y".

## `body_extras` carries `max_tokens`, and it is load-bearing

The last row above is the one that costs an afternoon. An `AIGatewayRoute` rule
carries a request **timeout** but no token ceiling. Measured 2026-09-04 with
`lms-4b`, one "count to 3000" prompt carrying **no** `max_tokens`:

| Gateway | `finish_reason` | completion tokens |
|:--|:--|--:|
| **Envoy** | `stop` | **13946** — nothing bounded it |
| MLflow | `stop` | 13961 — nothing bounded it either |
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

`run_all.py` refuses to start if 26000 is not answering, rather than letting four
scripts fail the same way — and it probes **`26000/v1/models`, not `26064/health`**.
The admin port answers `OK` several seconds before Envoy's listener accepts a
connection, so probing it races the thing being tested and the first script then
fails with a connection reset (measured 2026-09-04).

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

**One engine runs at a time**, so the aliases of every other engine have no
`AIGatewayRoute` rule at all. A fixed `lms-4b` default would therefore 404 on a
perfectly healthy gateway serving Ollama.

`common.py` reads `GATEWAY_ENGINE` from `../.env` — this project's own, not a
repo-root one, and not the same file either sibling project reads — and picks that engine's
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

Changing the engine here swaps the whole config file, so nothing from the previous
engine is left answering — unlike the MLflow project, whose endpoints persist in a
database until pruned.

Verified 2026-09-04: **4/4 on `ollama-4b`**. `02_tools_call.py` passing is the
result worth noting: it means a structured `tool_calls` reply came back, not the
raw-text tool syntax that makes most local models useless from an agent.

Two extra requirements for the Unsloth one, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `docker compose up -d`, or
   `${UNSLOTH_API_KEY}` substitutes empty and every `unsloth-*` call 401s.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. With it on, the first call unloads whatever was there and
   reads the new weights from disk, which shows up as one slow row and then nothing.
   Note that this covers the embedder too: `unsloth-embed` and `unsloth-4b` evict
   each other — and so do the other two projects, if either is up on the same engine.

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
same scenario file be copied to either sibling project unchanged — `01`–`03` are
byte-identical across all three.

## What is NOT tested here

- **Embeddings.** The `*-embed` aliases route fine, but the OpenAI chat client
  these scripts share does not drive `/v1/embeddings`.
- **`/anthropic/v1/messages`.** This gateway HAS it, translated onto the same
  backend, and the OpenAI client cannot speak it. Untested here.
- **`/mcp`.** The MCP gateway needs `--mcp-config`, which `../compose.yml` does not
  pass. Nothing is wired up, so there is nothing to test yet.
- **`/metrics` on 26064.** Prometheus output, untested.
- **The two PAID engines.** `config/openrouter.yaml` and `config/openai.yaml` parse
  and register their aliases (checked 2026-09-04), but no call has been made through
  either — that would bill a real account.
- **Fallback chains.** No route has one, so there is nothing to prove.
- **`openrouter-free`.** Absent here by design — no `extra_body` for the provider pin.
- **That the same alias answers on 24000 or 25000.** See the note at the top — no
  suite checks this any more.
