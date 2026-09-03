# tests — drive both gateways through the OpenAI client

Four scripts, each run against **both** gateways with the same alias and the same
client. Three prove the vocabulary is shared; the fourth proves the rest of the
request is **not**.

| Script | What it proves |
|:--|:--|
| `01_simple_call.py` | a plain chat completion, with a multi-turn conversation |
| `02_tools_call.py` | tools: a structured `tool_calls` reply, then the second turn that uses the tool result |
| `03_multimodal.py` | an image plus a question, sent as a base64 `data:` URL |
| `04_gateway_contract.py` | **how the two gateways differ**, and that `common.py`'s table still describes them |
| `run_all.py` | runs all four against both gateways and prints a pass/fail table |

Every script prints the **full** response and then the extracted text, so it
doubles as a sample to copy from.

## The calling contract — the same alias, a different request

The alias and the messages are identical on both ports. **Four things around them
are not**, and `common.py` declares all four on `Gateway`:

| | LiteLLM `:24000` | MLflow `:25000` |
|:--|:--|:--|
| `checks_api_key` | **401** on a bad key | **200** — no key concept at all |
| `lists_models` | `GET /models` → the alias list | `GET /models` → **404** |
| `echoes_alias` | `response.model` = `lms-4b` | = `google/gemma-4-e4b`, the engine's own id |
| `exposes_route_limits` | `/model/info` reports a per-route `max_tokens` | no such route — **nothing stores a ceiling** |

**The last row is the one that costs an afternoon.** LiteLLM stores a `max_tokens`
on the route, so a caller who sends none still gets a bounded reply. MLflow's
endpoints are database rows with no field for it. Measured 2026-09-03 with
`lms-4b`, one "count to 3000" prompt carrying **no** `max_tokens`:

| Gateway | `finish_reason` | completion tokens |
|:--|:--|--:|
| LiteLLM | `length` | **4095** — the route's stored 4096 |
| MLflow | `stop` | **13961** — nothing bounded it |

Same prompt, same weights, 3.4× the output and 3.4× the wait. So on **25000 you
always send `max_tokens` yourself**.

That is what `Gateway.body_extras` carries, and every scenario spreads it:

```python
response = client_for(gateway).chat.completions.create(
    model=model,
    messages=CONVERSATION,
    **gateway.body_extras,      # {} on LiteLLM, {"max_tokens": 2048} on MLflow
)
```

**A scenario still never branches on a gateway name.** It applies whatever the
table declares and cannot behave differently depending on which gateway it got.
`04_gateway_contract.py` is the one script that reads the table, checks reality
against it, and fails with "the table says X and the gateway did Y".

**Sent explicitly, `max_tokens` behaves identically on both** — including the trap
where a reasoning model spends the whole allowance thinking and returns empty
content with `finish_reason: "length"` and no error. Only the *default* differs.

## Run

The stack must be up first (`podman compose up -d` in the repo root).

```bash
cd tests
uv sync                     # once
uv run run_all.py           # all three, both gateways
```

One at a time:

```bash
uv run 01_simple_call.py                            # both gateways
uv run 02_tools_call.py --gateway litellm
uv run 03_multimodal.py --gateway mlflow --model ollama-4b
```

Every script exits `0` on pass and `1` on fail, so they work in a shell chain.

## Flags

| Flag | Default | Meaning |
|:--|:--|:--|
| `--gateway litellm\|mlflow\|both` | `both` | which gateway to drive |
| `--model <alias>` | follows `GATEWAY_ENGINE` | the alias to call — see below. Also settable with `AI_GATEWAY_TEST_MODEL` |
| `--verbose` (`run_all.py` only) | off | stream each script's output instead of capturing it |

## Reasoning aliases and `MAX_TOKENS`

`common.py` sends `max_tokens=2048` **to MLflow**, and that number is
load-bearing. Every `unsloth-*` and `ollama-*` route, and `lms-4b` too, spends the
same allowance on a reasoning block before writing a word. Run out mid-thought and
the reply is **empty**, with `finish_reason: "length"` and no error at all.

**On LiteLLM the scripts send no ceiling at all**, and get the route's stored
`max_tokens` — 4096 on `lms-*`, 8192 on `ollama-*` and `unsloth-*`. That is
deliberate: it is what every caller who forgets `max_tokens` actually gets, so it
is worth testing. `openai-mini` is the one route storing none; OpenAI's own
default applies there.

`answer_of()` names the empty case rather than reporting a bare "empty content",
and points at **both** places the ceiling can come from:

```
CheckFailed: empty content, finish_reason='length': the model spent its whole token
allowance on a reasoning block (612 chars) and never started the reply. Raise
MAX_TOKENS in common.py (that is what MLflow gets), or the route's `max_tokens` in
litellm/<engine>.yaml (that is what LiteLLM gets).
```

Raising the ceiling costs nothing when a model does not need it — generation stops
at `stop`, not at the ceiling.

## Why the default alias follows `GATEWAY_ENGINE`

**One engine runs at a time**, so the aliases of every other engine are not in the
config at all. A fixed `lms-4b` default would therefore fail with "model not found"
on a perfectly healthy stack serving Ollama.

`common.py` reads `GATEWAY_ENGINE` and picks that engine's small chat route —
`lms-4b`, `unsloth-4b`, `ollama-4b` or `openrouter-26b`. Each is the one alias on its
engine that is both vision- and tool-capable, which all three scripts need from a
single loaded model.

**An unrecognised engine is an error, not a fallback.** `all` used to be valid and is
exactly the value people still have written down; defaulting quietly produced
"Invalid model name passed in model=lms-4b" from a healthy stack, which reads as a
broken gateway rather than a stale `.env`. `openai` maps to nothing on purpose —
`gpt-5.4-mini` has no vision, so `03_multimodal.py` cannot pass against it.

`AI_GATEWAY_TEST_MODEL` overrides the choice permanently; `--model` for one run.

The gateway list follows `COMPOSE_PROFILES` the same way: a stack running only
MLflow gets three rows, not six, instead of three connection errors against 24000.

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
# in .env: GATEWAY_ENGINE=lms      then  docker compose up -d
uv run run_all.py
# in .env: GATEWAY_ENGINE=ollama   then  docker compose up -d
uv run run_all.py
```

Verified 2026-08-27, both gateways: **6/6 on each of the three**. Re-verified
2026-09-03 on `lms` with the fourth script added: **8/8**.

Two extra requirements for the Unsloth one, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   LiteLLM 401s and MLflow never got the endpoint at all.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. With it on, the first call unloads whatever was there and
   reads the new weights from disk, which shows up as one slow row and then nothing.
   Note that this covers the embedder too: `unsloth-embed` and `unsloth-4b` evict
   each other.

## The two gateways

| Gateway | `base_url` | Key |
|:--|:--|:--|
| LiteLLM | `http://localhost:24000/v1` | `AI_GATEWAY_KEY`, else `LITELLM_MASTER_KEY`, else `sk-litellm-master` |
| MLflow | `http://localhost:25000/gateway/mlflow/v1` | **none** — a placeholder string, because the OpenAI client refuses to build without one |

`common.py` loads the repo's `.env` without overriding the shell, the same
ordering compose uses.

## `test_image.png`

256x256, one red circle on a white background, 977 bytes. Deliberately
unambiguous so `03_multimodal.py` can check for `red` and for a round shape
without depending on how wordy the model is.

## Adding a test

Name it `05_something.py`, write one `scenario(gateway, model)` function, and end
it with `sys.exit(run(scenario, "Test 5 — ..."))`. `run_all.py` globs `NN_*.py`,
so it picks the new file up with no edit.

**Send `**gateway.body_extras` in every request, and do not branch on
`gateway.name`.** A scenario that reads the name has stopped proving the two
gateways share a vocabulary, which is the reason this folder exists.
`04_gateway_contract.py` is the single exception, because the difference *is* its
subject — and even it checks the declared table rather than hardcoding a name.

## What is NOT tested here

- **`/v1/messages`**, the Anthropic route. It exists on LiteLLM only, and the
  OpenAI client cannot speak it. The root `README.md` covers driving it from
  Claude Code.
- **Embeddings.** Every `*-embed` alias needs a different route on MLflow
  (`/gateway/openai/v1/embeddings`), not the chat one these scripts share.
- **Fallback chains.** No alias has one, on either gateway, so there is nothing to
  prove.
- **Budgets and virtual keys.** LiteLLM only, and `README.md` has the `curl`.
