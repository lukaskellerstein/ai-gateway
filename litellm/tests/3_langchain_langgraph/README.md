# 3 — LangChain and LangGraph

Two demos in one `main.py`, both reaching the gateway through **one line**:

```python
ChatOpenAI(model=ALIAS, base_url=BASE_URL, api_key=API_KEY)
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
`call_model` is one HTTP request to 24000, and the loop runs until the model stops
asking for tools. The run prints the message count per pass so you can watch the
prompt grow:

```
--- LangGraph: StateGraph built by hand ---
  -> gateway   (1 messages in the prompt)
  -> gateway   (3 messages in the prompt)
  tool call    get_stock_price({"ticker": "MSFT"})
  tool result  {"ticker": "MSFT", "current_price": 512.34}
```

That is why `../../config/<engine>.yaml` puts `timeout: 3600` on every local
route. An agent is not one call, it is a loop of them.

## No adapter, no plugin

The gateway speaks the OpenAI protocol, so the official `langchain-openai` package
is the whole integration. **Nothing in `main.py` is gateway-specific after
`build_model`.** A LangChain program written against OpenAI runs against a 4B model
on this laptop by changing where it points — and against a cloud model by changing
`GATEWAY_ENGINE` in `../../.env`, with no edit here at all.

## The check is on the number, not the words

Both demos assert that **`512` reaches the final answer**. A model that emits tool
calls as raw text — `<|tool_call>get_stock_price{...}` with `tool_calls` absent —
returns a perfectly readable reply with the number missing, and nothing raises.
That is the failure this file exists to catch, the same one
[`../2_openai_client/02_tools_call.py`](../2_openai_client/02_tools_call.py) checks
at the protocol level.

The tools return **fixed numbers**. A test that called a real market API could not
tell "the gateway is broken" from "the market is closed".

## `max_tokens`

`build_model` passes `BODY_EXTRAS.get("max_tokens")` from
[`../gateway.py`](../gateway.py) — `None` here, because LiteLLM stores a ceiling on
every route in `../../config/`. The Envoy copy of this folder passes `2048`,
because that gateway stores no default and an unbounded agent turn on a reasoning
model runs for minutes.

## Verified

2026-09-04, `unsloth-4b`: both demos returned `$512.34` through a structured
`tool_calls` reply. 1.5 s warm for the pair.
