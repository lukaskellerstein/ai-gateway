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
uv run 03_multimodal.py --gateway mlflow --model local-qwen
```

Every script exits `0` on pass and `1` on fail, so they work in a shell chain.

## Flags

| Flag | Default | Meaning |
|:--|:--|:--|
| `--gateway litellm\|mlflow\|both` | `both` | which gateway to drive |
| `--model <alias>` | `local-3b` | the alias to call. Also settable with `AI_GATEWAY_TEST_MODEL` |
| `--verbose` (`run_all.py` only) | off | stream each script's output instead of capturing it |

## Reasoning aliases and `MAX_TOKENS`

`common.py` sends `max_tokens=2048` on every call, and that number is load-bearing.
Several aliases — `reasoning`, `local-qwen`, `creative`, and **both `unsloth-*`** —
spend the same allowance on a reasoning block before writing a word. Run out
mid-thought and the reply is **empty**, with `finish_reason: "length"` and no
error at all.

`answer_of()` names that case rather than reporting a bare "empty content":

```
CheckFailed: empty content, finish_reason='length': the model spent its whole
2048-token allowance on a reasoning block (612 chars) and never started the reply.
Raise MAX_TOKENS in common.py.
```

Raising the ceiling costs nothing when a model does not need it — generation stops
at `stop`, not at the ceiling.

## Why `local-3b` is the default

It is the smallest route that is both vision-capable and tool-trained, so all
three scripts work on one loaded model. **LMStudio must have it loaded** —
`lms ps --json` is the truth, not the LMStudio UI. Any other alias means a JIT
load of many gigabytes, and a JIT load comes back at 8192 context with a 1 h TTL.

```bash
lms load mistralai/ministral-3-3b --context-length 262144 --parallel 1 --gpu max
```

## Testing an Unsloth alias

`--model unsloth-26b` and `--model unsloth-31b` run the same three scripts against
the second local engine. Two extra requirements:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   LiteLLM 401s and MLflow never got the endpoint at all.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. With it on, a call to `unsloth-31b` unloads `unsloth-26b`
   and loads 17 GB first. It shows up as one slow row and then nothing: in the
   `unsloth-31b` run below, `01_simple_call.py` on litellm took **10.1 s** and every
   later row 1.8–4.2 s.

Verified 2026-08-27, both gateways: **6/6 on `unsloth-26b`** and **6/6 on
`unsloth-31b`** — plain call, tools and multimodal on each.

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
  OpenAI client cannot speak it. `NOTES.md` covers driving it from Claude Code.
- **Embeddings.** `embed` and `embed-hq` need a different route on MLflow
  (`/gateway/openai/v1/embeddings`), not the chat one these scripts share.
- **Fallback chains.** Both fallback maps in `litellm/config.yaml` are commented
  out today, so there is nothing to prove.
- **Budgets and virtual keys.** LiteLLM only, and `README.md` has the `curl`.
