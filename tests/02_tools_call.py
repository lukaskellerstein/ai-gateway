"""Test 2 — a chat completion with tools, and the full two-turn loop.

This is the test that matters for agents. A model that answers prose fine can
still emit tool calls as RAW TEXT — `<|tool_call>call:get_stock_price{...}` with
`tool_calls` absent. Nothing errors: the agent sees an assistant message with no
tool calls, executes nothing, and stops. So the check below is on the STRUCTURE
of the reply, not on its words.

The tools return fixed numbers instead of calling a market API. A test whose
result depends on the internet cannot tell "the gateway is broken" from "the
market is closed".

    uv run 02_tools_call.py
    uv run 02_tools_call.py --gateway mlflow
"""

import json
import sys

from common import Gateway, answer_of, check, client_for, run, show

PRICES = {"MSFT": 512.34, "GOOG": 187.65}
DIVIDEND_DATES = {"MSFT": "2026-09-11", "GOOG": "2026-09-15"}


def get_stock_price(ticker: str) -> dict:
    return {"ticker": ticker, "current_price": PRICES.get(ticker.upper())}


def get_dividend_date(ticker: str) -> dict:
    return {"ticker": ticker, "dividend_date": DIVIDEND_DATES.get(ticker.upper())}


AVAILABLE_FUNCTIONS = {
    "get_stock_price": get_stock_price,
    "get_dividend_date": get_dividend_date,
}

# Two tools, not one: with a single tool a model that always calls it looks
# correct. Two make the choice observable.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "Use this function to get the current price of a stock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "The ticker symbol, e.g. GOOG"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dividend_date",
            "description": "Use this function to get the next dividend payment date of a stock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "The ticker symbol, e.g. GOOG"},
                },
                "required": ["ticker"],
            },
        },
    },
]


def run_tool_calls(messages: list, tool_calls) -> None:
    """Append the assistant turn and one `tool` message per call, in place."""
    messages.append(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in tool_calls
            ],
        }
    )
    for call in tool_calls:
        result = AVAILABLE_FUNCTIONS[call.function.name](**json.loads(call.function.arguments))
        print(f"--- Ran {call.function.name}({call.function.arguments}) -> {result}")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": json.dumps(result),
            }
        )


def scenario(gateway: Gateway, model: str) -> str:
    client = client_for(gateway)
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools when they fit."},
        {"role": "user", "content": "What is the current stock price for MSFT?"},
    ]

    # `**gateway.body_extras` is the per-gateway calling contract from common.py.
    # BOTH TURNS CARRY IT: a tool loop that sets a ceiling on the first call and
    # forgets it on the second gets an empty final answer on MLflow, which reads
    # like the tool result never arrived.
    first = client.chat.completions.create(
        model=model, messages=messages, tools=TOOLS, tool_choice="auto", **gateway.body_extras
    )
    show("First response", first)

    tool_calls = first.choices[0].message.tool_calls
    check(bool(tool_calls), "no tool_calls in the reply — the model answered as text instead of calling the tool")
    check(
        first.choices[0].finish_reason == "tool_calls",
        f"finish_reason was {first.choices[0].finish_reason!r}, expected 'tool_calls'",
    )
    called = tool_calls[0].function.name
    check(called == "get_stock_price", f"the model picked {called!r} instead of 'get_stock_price'")

    run_tool_calls(messages, tool_calls)

    second = client.chat.completions.create(
        model=model, messages=messages, tools=TOOLS, tool_choice="auto", **gateway.body_extras
    )
    show("Second response", second)
    text = answer_of(second)
    print(f"--- Response text: ---\n{text}")

    check("512" in text, f"the tool result 512.34 did not reach the final answer: {text!r}")
    return f"called {called}, final answer {text!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 2 — tool calling, two-turn loop"))
