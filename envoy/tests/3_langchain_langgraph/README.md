# 3 — LangChain and LangGraph

Two demos in one `main.py`, both reaching the gateway through **one line**:

```python
ChatOpenAI(model=ALIAS, base_url="http://localhost:26000/v1", api_key=API_KEY)
```

```bash
uv run main.py
uv run main.py --model lms-26b
uv run main.py --only langgraph
```

| Demo | Builds | Shows |
|:--|:--|:--|
| `langchain` | `create_agent(model, tools=…)` | the prebuilt agent — the shortest agent in LangChain 1.x |
| `langgraph` | `StateGraph` by hand | the same ReAct loop with the nodes visible: `START → model → tools → model → END` |

## Why both

`create_agent` returns a compiled graph and hides it. Building the graph yourself
is what shows **where the gateway sits in an agent**: every pass through
`call_model` is one HTTP request to 26000, and the loop runs until the model stops
asking for tools. The run prints the message count per pass so you can watch the
prompt grow.

That is why `../../config/<engine>.yaml` sets `request: 60m` on **both** the route
and the backend — the smaller of the two wins, and upstream's default is 3 minutes.
An agent is not one call, it is a loop of them.

## No adapter, no plugin

The gateway speaks the OpenAI protocol, so the official `langchain-openai` package
is the whole integration. **Nothing in `main.py` is gateway-specific after
`build_model`** — the file is byte-identical in all three projects.

Two things about this gateway a LangChain program feels:

- **`api_key` is a placeholder.** `aigw run` checks no caller credential; the
  OpenAI client simply demands the argument.
- **`response.model` is not the alias you sent.** `modelNameOverride` rewrote it to
  the engine's own id on the way out and nothing rewrites it back, so anything
  keying a metric or a log line off `response.model` sees
  `unsloth/gemma-4-E4B-it-qat-GGUF`.

## `max_tokens` is passed, and it matters here

`build_model` passes `BODY_EXTRAS.get("max_tokens")` from
[`../gateway.py`](../gateway.py) — **2048** on this gateway, because an
`AIGatewayRoute` rule carries a request timeout but no token ceiling. LiteLLM's
copy of this folder passes `None`, since its routes carry their own.

Without it an agent turn on a reasoning model runs until the model stops, which on
a local engine is minutes rather than seconds.

## The check is on the number, not the words

Both demos assert that **`512` reaches the final answer**. A model that emits tool
calls as raw text — `<|tool_call>get_stock_price{...}` with `tool_calls` absent —
returns a perfectly readable reply with the number missing, and nothing raises.
That the check passes here is worth noting: it means this gateway carries a
structured `tool_calls` reply through untouched.

The tools return **fixed numbers**. A test that called a real market API could not
tell "the gateway is broken" from "the market is closed".

## Verified

2026-09-04, `unsloth-4b`: both demos returned `$512.34` through a structured
`tool_calls` reply. 1.5 s warm for the pair.
