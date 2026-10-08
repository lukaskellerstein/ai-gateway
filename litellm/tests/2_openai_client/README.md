# 2 — OpenAI client

The gateway driven through **OpenAI's own Python client** — the way most
projects will call it. Six scripts against **24000**: three prove a kind of
call works, the fourth proves this gateway's calling contract is still what
`settings.py` says it is, the fifth that the thinking level reaches the model, and
the sixth that a `-fast` alias answers with thinking off.

This is folder 2 of seven. The index, and the six other ways in, are in
[`../README.md`](../README.md).

| Script | What it proves |
|:--|:--|
| `01_simple_call.py` | a plain chat completion, with a multi-turn conversation |
| `02_tools_call.py` | tools: a structured `tool_calls` reply, then the second turn that uses the tool result |
| `03_multimodal.py` | an image plus a question, sent as a base64 `data:` URL |
| `04_gateway_contract.py` | **this gateway's contract**, and that `settings.py`'s table still describes it |
| `05_reasoning_effort.py` | `reasoning_effort` reaches a Qwen 3.8 template; "not applicable" on any other alias |
| `06_thinking_off.py` | a `-fast` alias answers with no thinking where its base alias thinks, on chat and `/v1/responses` — **and is the example of calling one: only the name changes**. "Not applicable" on any other alias |
| `run_all.py` | runs all six and prints a pass/fail table |
| `run_benchmark.py` | times the shared three-turn task — never run by `run_all.py` |

Every script prints the **full** response and then the extracted text, so it
doubles as a sample to copy from.

## Copying this folder

**`settings.py` is the one file to edit.** It holds the URL, the key, the alias
(`lms-gemma4-e4b`, or `AI_GATEWAY_MODEL`), the thinking level (`medium`, or
`AI_GATEWAY_REASONING_EFFORT`; empty sends none), `body_extras(alias)` and this
gateway's `CONTRACT`. Every other file is byte-identical to the Envoy copy in
`../../../../envoy/tests/2_openai_client/`.

`uv run run_benchmark.py --aliases <alias>` runs the task every folder shares — a
~1500-token policy, a tool call, two follow-ups — and writes the numbers to
`RESULTS.md` beside it. `--no-write` prints them and leaves the file alone.

> **This suite drives one gateway.** Until 2026-09-03 there was one `tests/` at the
> repo root that ran every script against two ports at once, and it was the thing
> that caught the two alias lists drifting apart. Each gateway is a standalone
> compose project now, so that check has no owner: **nothing here, and nothing
> anywhere in the repo, verifies that an alias answering on 24000 also answers on
> 26000.** Call both ports by hand when it matters.

## The calling contract

`CONTRACT` in `settings.py` declares five things about how to call this gateway,
and `04_gateway_contract.py` checks every one against reality:

| | LiteLLM `:24000` |
|:--|:--|
| `checks_api_key` | **True** — a bogus Bearer token gets 401, so the master key is enforced |
| `lists_models` | **True** — `GET /models` returns the alias list |
| `echoes_alias` | **True** — `response.model` is `lms-gemma4-e4b`, the alias that was sent |
| `exposes_route_limits` | **True** — `/model/info` reports each route's stored `max_tokens` |
| `loopback_only` | **True** — this Mac's network address refuses 24000; `../../compose.yml` publishes on `127.0.0.1` |

The failure message is always "the table says X and the gateway did Y", which is
the sentence you want. The Envoy copy of `settings.py` declares its own five, the
same `04` checks them against that gateway — and two of the five match.

**`body_extras` carries the thinking level and no ceiling here**, and the missing
ceiling is deliberate. LiteLLM stores a `max_tokens` on the route and every local
route in `../../config/` carries one, so a caller who sends none still gets a
bounded reply. Scripts 01-03 therefore run against the stored default, which is
worth testing: it is what every caller who forgets `max_tokens` actually gets.

```python
response = client_for(gateway).chat.completions.create(
    model=model,
    messages=CONVERSATION,
    **gateway.body_extras,      # {"reasoning_effort": "medium"} on this gateway
)
```

A scenario spreads `body_extras` and reads nothing else off `gateway`, so it cannot
grow gateway-specific behaviour by accident.

## Run

The gateway must be up first — `podman compose up -d` two directories up.

```bash
uv run run_all.py           # all six scripts in this folder
```

`uv run` builds this folder's own venv on first use, so there is no `uv sync` step.
To run all SEVEN folders instead, use `../run_all.py`.

One at a time:

```bash
uv run 01_simple_call.py
uv run 02_tools_call.py --model lms-gemma4-26b
uv run 03_multimodal.py --model ollama-gemma4-e4b
```

Every script exits `0` on pass and `1` on fail, so they work in a shell chain.
`run_all.py` refuses to start if 24000 is not answering, rather than letting six
scripts fail the same way. The URL it probes is `HEALTH_URL` in `settings.py`.

## Flags

| Flag | Default | Meaning |
|:--|:--|:--|
| `--model <alias>` | `lms-gemma4-e4b` | the alias to call — see below. Also settable with `AI_GATEWAY_MODEL` |
| `--verbose` (`run_all.py` only) | off | stream each script's output instead of capturing it |

There is no `--gateway` flag any more. The folder you are in is the gateway.

## Reasoning aliases and the stored ceiling

**The scripts send no `max_tokens` at all** and get the route's stored value — 4096
on `lms-*`, 8192 on `ollama-*` and `unsloth-*`. `openai-gpt54-mini` is the one route
storing none; OpenAI's own default applies there.

That matters because every `unsloth-*` and `ollama-*` route, and `lms-gemma4-e4b` too,
spends the same allowance on a reasoning block before writing a word. Run out
mid-thought and the reply is **empty**, with `finish_reason: "length"` and no error
at all.

`answer_of()` names that case rather than reporting a bare "empty content":

```
CheckFailed: empty content, finish_reason='length': the model spent its whole token
allowance on a reasoning block (612 chars) and never started the reply. Raise the
ceiling in settings.body_extras, or the route's stored `max_tokens`.
```

Raising the ceiling costs nothing when a model does not need it — generation stops
at `stop`, not at the ceiling.

## The default alias

`settings.MODEL` is `lms-gemma4-e4b`, which the `lms`, `all` and `lukas` configs all
serve. It is small, and both vision- and tool-capable, which `02` and `03` need from
one loaded model. On a gateway naming another engine in `GATEWAY_ENGINE` it is not
in the config at all and fails with "model not found" — pass `--model`.

`AI_GATEWAY_MODEL` overrides it permanently; `--model` for one run.

**On LMStudio the model must be loaded first** — `lms ps --json` is the truth, not
the LMStudio UI. A JIT load comes back at 8192 context with a 1 h TTL. Ollama loads
on demand and needs none of this.

```bash
lms load google/gemma-4-e4b --context-length 131072 --parallel 1 --gpu max
```

## The same test on another engine

The suite doubles as an engine comparison. The default `all` config serves every
engine at once, so it is a second `--model`, not a restart:

```bash
uv run run_all.py --model lms-gemma4-e4b
uv run run_all.py --model ollama-gemma4-e4b
```

Verified 2026-09-03: **4/4 on `unsloth-gemma4-e4b`**, with a second gateway also running.
Verified 2026-08-27 on the pre-split suite: 6/6 on each of `lms`, `ollama` and
`unsloth`, across both gateways.

Two extra requirements for the Unsloth one, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   every `unsloth-*` route 401s at call time.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. With it on, the first call unloads whatever was there and
   reads the new weights from disk, which shows up as one slow row and then nothing.
   Note that this covers the embedder too: `unsloth-nomic-embed` and `unsloth-gemma4-e4b` evict
   each other — and so does the Envoy project, if it is up on the same engine.

## `test_image.png`

256x256, one red circle on a white background, 977 bytes. Deliberately
unambiguous so `03_multimodal.py` can check for `red` and for a round shape
without depending on how wordy the model is.

## Adding a test

Name it `06_something.py`, write one `scenario(gateway, model)` function, and end
it with `sys.exit(run(scenario, "Test 6 — ..."))`. `run_all.py` globs `NN_*.py`,
so it picks the new file up with no edit.

**Send `**gateway.body_extras` in every request.** It carries the thinking level
here, and it is what keeps a scenario from reaching into the gateway object for
anything else — which is what lets the same scenario file be copied to the Envoy
project unchanged.

## What is NOT tested here

- **`/v1/messages`**, the Anthropic route. The OpenAI client cannot speak it.
  [`../../README.md`](../../README.md) covers driving it from Claude Code.
- **Embeddings.** Every `*-embed` alias needs a different route from the chat one
  these scripts share.
- **Fallback chains.** No alias has one, so there is nothing to prove.
- **Budgets and virtual keys.** [`../../README.md`](../../README.md) has the `curl`.
- **That the same alias answers on 26000.** See the note at the top — no suite
  checks this any more.
