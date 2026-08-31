# tests — drive both gateways through the OpenAI client

Three scripts, one per kind of call, each run against **both** gateways with the
same alias name and the same client. That is the point: a caller swaps
`base_url` and changes nothing else.

| Script | What it proves |
|:--|:--|
| `01_simple_call.py` | a plain chat completion, with a multi-turn conversation |
| `02_tools_call.py` | tools: a structured `tool_calls` reply, then the second turn that uses the tool result |
| `03_multimodal.py` | an image plus a question, sent as a base64 `data:` URL |
| `run_all.py` | runs all three against both gateways and prints a pass/fail table |

Every script prints the **full** response and then the extracted text, so it
doubles as a sample to copy from.

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

`common.py` sends `max_tokens=2048` on every call, and that number is load-bearing.
Every `unsloth-*` and `ollama-*` route, and `lms-4b` too, spends the same
allowance on a reasoning block before writing a word. Run out mid-thought and the
reply is **empty**, with `finish_reason: "length"` and no error at all.

`answer_of()` names that case rather than reporting a bare "empty content":

```
CheckFailed: empty content, finish_reason='length': the model spent its whole
2048-token allowance on a reasoning block (612 chars) and never started the reply.
Raise MAX_TOKENS in common.py.
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

Verified 2026-08-27, both gateways: **6/6 on each of the three**.

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

Name it `04_something.py`, write one `scenario(gateway, model)` function, and end
it with `sys.exit(run(scenario, "Test 4 — ..."))`. `run_all.py` globs `NN_*.py`,
so it picks the new file up with no edit.

## What is NOT tested here

- **`/v1/messages`**, the Anthropic route. It exists on LiteLLM only, and the
  OpenAI client cannot speak it. The root `README.md` covers driving it from
  Claude Code.
- **Embeddings.** Every `*-embed` alias needs a different route on MLflow
  (`/gateway/openai/v1/embeddings`), not the chat one these scripts share.
- **Fallback chains.** No alias has one, on either gateway, so there is nothing to
  prove.
- **Budgets and virtual keys.** LiteLLM only, and `README.md` has the `curl`.
