# benchmark — what does the gateway itself cost?

One question: both gateways serve the same alias from the same engine, so
**does the choice of gateway change what a caller waits for?**

```bash
cd benchmark
uv run main.py                       # 5 rounds per scenario
uv run main.py --rounds 10           # the published numbers
uv run main.py --model unsloth-26b   # a different alias
uv run main.py --json results.json   # raw per-call timings as well
```

No dependencies. Results, and how to read them, are in
[the root README](../README.md#gateway-comparison).

## Why this exists

Timing a whole `tests/` folder answers a different question, and answers it badly.
A folder's wall clock is dominated by building a venv, importing LangChain,
spawning a CLI, and whether the engine had the model warm. Measured 2026-09-04,
the **same script on the same gateway** ran anywhere from **5.8 s to 46.7 s**
across eight runs — a spread wider than any difference between the gateways.

So this file times **one HTTP request** and nothing else.

## What is held still

Each of these is a way the comparison could have lied:

| Held constant | Why it matters |
|:--|:--|
| **the engine** | both proxy to one Unsloth on `:8888`, which holds one model at a time |
| **the model** | one alias — and the upstream id is **read back** from each reply and compared |
| **the body** | byte-identical messages, `temperature: 0` |
| **`max_tokens`** | **sent explicitly.** Not optional — see below |
| **the order** | round-robin, so no gateway gets the cold first call |
| **warm-up** | one discarded round per scenario, per gateway |

> **`max_tokens` is the control that matters most.** LiteLLM stores a `max_tokens`
> on every route and Envoy stores none. A body that omits it therefore asks
> **LiteLLM to do less work** — it would stop at 4096 tokens while Envoy ran on.
> Sending an explicit ceiling makes the work identical, and the `completion tokens`
> column proves it did: every gateway returns the same count.

## What is measured

Four scenarios, plus streaming:

| Scenario | Is |
|:--|:--|
| `tiny` | a two-token reply — the **fixed overhead** of a round trip, with generation out of the way |
| `chat` | a one-sentence answer |
| `tools` | a tool schema in, a structured `tool_calls` reply out — the most *translated* part of an OpenAI body |
| `long-prompt` | a ~4 KB prompt, big enough to matter to Envoy's `bufferLimit` |
| `streaming` | **time to first token**, which is the number a buffering proxy would destroy |

Reported per scenario: min, median, p90, max, and the **completion tokens** — a
gateway that answered faster by generating less has not answered faster.

## The direct row

When `UNSLOTH_API_KEY` is in the shell, the benchmark also calls the engine on
`:8888` with **no gateway at all**. Every gateway row can then be read as *"the
engine, plus this much"*. That row asks for the engine's own model id, not the
alias — an alias is a gateway's invention and the engine has never heard of it —
and the id is discovered from a gateway that echoes it back rather than hardcoded.

## Two things it checks before it trusts itself

1. **That both are on the same engine.** Each project reads its own `.env` and
   nothing keeps them in step. Envoy returns the upstream model id in
   `response.model`; if it disagrees with the direct row, the run says so loudly
   and the table below it means nothing. (LiteLLM echoes the alias by design, so
   its upstream id is not visible this way.)
2. **That a failure is counted, not treated as a verdict.** Every round is
   attempted even after one fails. An earlier version gave up on a gateway at its
   first error and printed the row as `unsupported` — so one transient 503 was
   indistinguishable from a route that does not exist. The table now says
   `unsupported` only when **every** round failed, and otherwise reports the
   successes with a failure count beside them.

## It touches both ports, and that is allowed

This is the only thing in the repo that does. **It reads no file belonging to any
project** — only the URLs, which are fixed and documented — so the compose projects
stay exactly as independent as they were. Delete a gateway's folder and its row
here reports `not answering`. That is exactly how `mlflow` on 25000 left this file
on 2026-09-04: one line removed, and nothing else changed.

That also makes it the closest thing the repo has to the cross-gateway check that
went away when the projects were split. It compares **latency**, not vocabulary:
it still will not tell you that an alias present on 24000 is missing on 26000.

## Reading the results

**Read the medians.** A local engine's tail is the engine — a model that pauses
for 60 ms because something else touched the GPU is not a slow proxy.
