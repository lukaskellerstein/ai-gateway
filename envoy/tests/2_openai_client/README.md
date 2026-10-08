# 2 — OpenAI client

The gateway driven through **OpenAI's own Python client** — the way most
projects will call it. Six scripts against **26000**: three prove a kind of
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

**`settings.py` is the one file to edit.** It holds the URL, the key placeholder,
the alias (`lms-gemma4-e4b`, or `AI_GATEWAY_MODEL`), the thinking level (`medium`,
or `AI_GATEWAY_REASONING_EFFORT`; empty sends none), `body_extras(alias)` with its
`max_tokens`, and this gateway's `CONTRACT`. Every other file is byte-identical to
the LiteLLM copy in `../../../../litellm/tests/2_openai_client/`.

`uv run run_benchmark.py --aliases <alias>` runs the task every folder shares — a
~1500-token policy, a tool call, two follow-ups — and writes the numbers to
`RESULTS.md` beside it. `--no-write` prints them and leaves the file alone.

> **This suite drives one gateway.** Until 2026-09-03 there was one `tests/` at the
> repo root that ran every script against two ports at once, and it was the thing
> that caught the two alias lists drifting apart. Each gateway is a standalone
> compose project now, so that check has no owner: **nothing here, and nothing
> anywhere in the repo, verifies that an alias answering on 26000 also answers on
> 24000.** Call the other port by hand when it matters.

## The calling contract

`CONTRACT` in `settings.py` declares five things about how to call this gateway,
and `04_gateway_contract.py` checks every one against reality. **Three are `False`**, and
checking a `False` is the point: an absence nobody checks is an absence somebody
eventually assumes away.

| | Envoy `:26000` |
|:--|:--|
| `checks_api_key` | **False** — a bogus Bearer token gets 200. `aigw run` authenticates no caller at all |
| `lists_models` | **True** — `GET /models` returns the alias list, built from the AIGatewayRoute rules |
| `echoes_alias` | **False** — `response.model` is `google/gemma-4-e4b`; `modelNameOverride` rewrote it and nothing undoes that |
| `exposes_route_limits` | **False** — no `/model/info` route, and a route rule carries a timeout but no token ceiling |
| `loopback_only` | **True** — this Mac's network address refuses 26000; `../../compose.yml` publishes on `127.0.0.1` |

**THIS GATEWAY IS NOT A COPY OF THE OTHER ONE.** It lists its models like LiteLLM,
and then checks no caller key at all and echoes the upstream model id rather than the
alias — so a test that assumed "LiteLLM or not-LiteLLM" would be wrong about it. That
is exactly why each project declares and checks its own table, and why the failure
message is always "the table says X and the gateway did Y".

## `body_extras` carries `max_tokens`, and it is load-bearing

The last row above is the one that costs an afternoon. An `AIGatewayRoute` rule
carries a request **timeout** but no token ceiling. Measured 2026-09-04 with
`lms-gemma4-e4b`, one "count to 3000" prompt carrying **no** `max_tokens`:

| Gateway | `finish_reason` | completion tokens |
|:--|:--|--:|
| **Envoy** | `stop` | **13946** — nothing bounded it |
| LiteLLM, for contrast | `length` | 4095 — the route's stored 4096 |

Same prompt, same weights, 3.4× the output and 3.4× the wait. So **here you always
send `max_tokens` yourself**. That is what `Gateway.body_extras` carries, and every
scenario spreads it:

```python
response = client_for(gateway).chat.completions.create(
    model=model,
    messages=CONVERSATION,
    **gateway.body_extras,      # {"max_tokens": 8192, "reasoning_effort": "medium"} here
)
```

A scenario spreads `body_extras` and reads nothing else off `gateway`, so it cannot
grow gateway-specific behaviour by accident.

**Sent explicitly, `max_tokens` behaves normally** — including the trap where a
reasoning model spends the whole allowance thinking and returns empty content with
`finish_reason: "length"` and no error. Only the *default* is missing.

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

`run_all.py` refuses to start if 26000 is not answering, rather than letting six
scripts fail the same way — and `HEALTH_URL` in `settings.py` is
**`26000/v1/models`, not `26064/health`**. The admin port answers `OK` several seconds before Envoy's listener accepts a
connection, so probing it races the thing being tested and the first script then
fails with a connection reset (measured 2026-09-04).

## Flags

| Flag | Default | Meaning |
|:--|:--|:--|
| `--model <alias>` | `lms-gemma4-e4b` | the alias to call — see below. Also settable with `AI_GATEWAY_MODEL` |
| `--verbose` (`run_all.py` only) | off | stream each script's output instead of capturing it |

There is no `--gateway` flag any more. The folder you are in is the gateway.

## Reasoning aliases and `MAX_TOKENS`

`settings.py` sends `max_tokens=8192`, and that number is load-bearing. Every
`unsloth-*` and `ollama-*` route, and `lms-gemma4-e4b` too, spends the same allowance on a
reasoning block before writing a word. Run out mid-thought and the reply is
**empty**, with `finish_reason: "length"` and no error at all.

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
one loaded model. On a gateway naming another engine in `GATEWAY_ENGINE` it has no
`AIGatewayRoute` rule at all and 404s — pass `--model`.

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

Verified 2026-09-04: **4/4 on `ollama-gemma4-e4b`**. `02_tools_call.py` passing is the
result worth noting: it means a structured `tool_calls` reply came back, not the
raw-text tool syntax that makes most local models useless from an agent.

Two extra requirements for the Unsloth one, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   `${UNSLOTH_API_KEY}` substitutes empty and every `unsloth-*` call 401s.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. With it on, the first call unloads whatever was there and
   reads the new weights from disk, which shows up as one slow row and then nothing.
   Note that this covers the embedder too: `unsloth-nomic-embed` and `unsloth-gemma4-e4b` evict
   each other — and so does the LiteLLM project, if it is up on the same engine.

## `test_image.png`

256x256, one red circle on a white background, 977 bytes. Deliberately
unambiguous so `03_multimodal.py` can check for `red` and for a round shape
without depending on how wordy the model is.

## Adding a test

Name it `06_something.py`, write one `scenario(gateway, model)` function, and end
it with `sys.exit(run(scenario, "Test 6 — ..."))`. `run_all.py` globs `NN_*.py`,
so it picks the new file up with no edit.

**Send `**gateway.body_extras` in every request.** On this gateway it carries the
`max_tokens` a scenario would otherwise have to remember, and it is what lets the
same scenario file be copied to the LiteLLM project unchanged — every file but
`settings.py` is byte-identical across both.

## What is NOT tested here

- **Embeddings.** The `*-embed` aliases route fine, but the OpenAI chat client
  these scripts share does not drive `/v1/embeddings`.
- **`/anthropic/v1/messages`.** This gateway HAS it, translated onto the same
  backend, and the OpenAI client cannot speak it. Untested here.
- **`/mcp`.** An agent's surface, not this client's: folders 3 to 7 each call a tool
  through it — `../README.md` § MCP servers behind the gateway.
- **`/metrics` on 26064.** Prometheus output, untested.
- **The two PAID engines.** `config/openrouter.yaml` and `config/openai.yaml` parse
  and register their aliases (checked 2026-09-04), but no call has been made through
  either — that would bill a real account.
- **Fallback chains.** No route has one, so there is nothing to prove.
- **`openrouter-gemma4-26b-free`.** Absent here by design — no `extra_body` for the provider pin.
- **That the same alias answers on 24000.** See the note at the top — no suite
  checks this any more.
