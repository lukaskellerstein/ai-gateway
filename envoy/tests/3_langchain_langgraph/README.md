# 3 — LangChain and LangGraph

Three demos in one `run.py`, all reaching the gateway's model through **one line**:

```python
ChatOpenAI(model=MODEL, base_url="http://localhost:26000/v1", api_key=API_KEY)
```

```bash
uv run run.py
uv run run.py --model lms-gemma4-26b
uv run run.py --only langgraph
uv run run.py --only mcp
uv run run_benchmark.py --aliases lms-gemma4-26b --no-write
```

## Copying this folder

[`settings.py`](settings.py) is the one file to edit: the URL, the key, the alias,
the thinking level (`reasoning_effort=` on ChatOpenAI, `medium` by default), the
`max_tokens` ceiling and `stream_usage`. Every other file is byte-identical to the
LiteLLM copy. `uv run run_benchmark.py` runs the shared task through demo 2's loop and
times every model request; `RESULTS.md` holds the numbers.

| Demo | Builds | Shows |
|:--|:--|:--|
| `langchain` | `create_agent(model, tools=…)` | the prebuilt agent — the shortest agent in LangChain 1.x |
| `langgraph` | `StateGraph` by hand | the same ReAct loop with the nodes visible: `START → model → tools → model → END` |
| `mcp` | `create_agent` with tools from the gateway's `/mcp` | the MCP server **behind the gateway**: the agent gets one URL, and the tool arrives renamed |

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
is the whole integration. **Nothing in `run.py` is gateway-specific after
`build_model`** — the file is byte-identical in both projects.

Two things about this gateway a LangChain program feels:

- **`api_key` is a placeholder.** `aigw run` checks no caller credential; the
  OpenAI client simply demands the argument.
- **`response.model` is not the alias you sent.** `modelNameOverride` rewrote it to
  the engine's own id on the way out and nothing rewrites it back, so anything
  keying a metric or a log line off `response.model` sees
  `unsloth/gemma-4-E4B-it-qat-GGUF`.

## `max_tokens` is passed, and it matters here

`build_model` passes `MAX_TOKENS` from [`settings.py`](settings.py) — **8192** on
this gateway, because an `AIGatewayRoute` rule carries a request timeout but no
token ceiling. LiteLLM's copy of this folder passes `None`, since its routes carry
their own.

Without it an agent turn on a reasoning model runs until the model stops, which on
a local engine is minutes rather than seconds. ChatOpenAI sends it as
`max_completion_tokens` for every model — what OpenAI's newer models demand, and
LMStudio honours it too (measured 2026-09-30) — so unlike `1_http_client` this
folder needs no per-alias switch.

## What LangChain shows of a streamed reply

Measured 2026-09-30 on `lms-gemma4-26b`, both gateways:

- **No thinking text.** `ChatOpenAI` drops `reasoning_content`; only the count
  survives, in `usage_metadata.output_token_details.reasoning`.
- **No invented cache count.** With no cache field in the reply,
  `input_token_details` is `{}` — `cache_read` is absent, not 0.

## The check is on the number, not the words

The first two demos assert that **`512` reaches the final answer**. A model that emits tool
calls as raw text — `<|tool_call>get_stock_price{...}` with `tool_calls` absent —
returns a perfectly readable reply with the number missing, and nothing raises.
That the check passes here is worth noting: it means this gateway carries a
structured `tool_calls` reply through untouched.

The tools return **fixed numbers**. A test that called a real market API could not
tell "the gateway is broken" from "the market is closed".

## MCP through the gateway — demo 3

`mcp` starts [`mcp_server.py`](mcp_server.py) over HTTP on the port the gateway's
config names — `MCP_SERVER_PORT` in `settings.py` — and gives the agent nothing
but `MCP_URL`. `langchain-mcp-adapters` turns the gateway's tools into ordinary
LangChain tools. **The renamed tool is the proof**: `bench_hardware-bench_serial` on
LiteLLM, `bench-hardware__bench_serial` on Envoy, and the demo asserts the model
called it and that `SN-4417-QX` reached the answer.

## Verified

2026-09-30, `lms-gemma4-26b`: both demos returned `$512.34` through a structured
`tool_calls` reply, and the benchmark passed all three turns in 4 requests.

2026-10-07, `lms-gemma4-e4b`, both gateways: demo 3 called the renamed tool and
answered `SN-4417-QX`, and the first two demos still returned `$512.34`.
