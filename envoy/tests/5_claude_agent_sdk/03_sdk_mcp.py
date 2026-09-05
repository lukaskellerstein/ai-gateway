"""03 tools — an MCP server that runs INSIDE this process.

`create_sdk_mcp_server` builds a real MCP server with no subprocess and no
socket: the SDK registers the tools with the CLI and answers the calls in this
Python process. It is the cheapest way to give an agent a tool, and the right one
when the tool needs objects this program already holds — a database session, an
open file, a client that is already authenticated.

Scenario 04 is the same idea over stdio, in a process of its own. Read the two
together; the difference between them is the whole of MCP transport.

THE TOOLS RETURN FIXED NUMBERS, and that is deliberate. A test that called a real
market API could not tell "the gateway is broken" from "the market is closed",
and the numbers here are unguessable so a model that invents an answer instead of
calling the tool fails the assertion.

TWO TOOLS, NOT ONE. With a single tool a model that always calls the only thing
it has looks correct. Two tools and one question that needs both is the smallest
test of actual selection.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from claude_agent_sdk import create_sdk_mcp_server, tool

from common import agent_options, ask, report, run

PRICE = "187.42"
STOCK = "1204"


@tool("stock_price", "The current share price of a ticker, in USD", {"ticker": str})
async def stock_price(args: dict[str, str]) -> dict[str, object]:
    return {"content": [{"type": "text", "text": f"{args['ticker']} trades at {PRICE} USD"}]}


@tool("warehouse_stock", "How many units of a ticker's product are in the warehouse", {"ticker": str})
async def warehouse_stock(args: dict[str, str]) -> dict[str, object]:
    return {"content": [{"type": "text", "text": f"{args['ticker']} has {STOCK} units in stock"}]}


BENCH = create_sdk_mcp_server(name="bench", version="1.0.0", tools=[stock_price, warehouse_stock])


async def scenario(model: str) -> str:
    answer = await ask(
        "For the ticker ACME, report the share price and the warehouse unit count. "
        "Use the tools; do not guess.",
        agent_options(
            model,
            mcp_servers={"bench": BENCH},
            # THE PREFIX IS THE PROTOCOL: mcp__<server name>__<tool name>. A tool
            # left out of this list is not offered to the model at all.
            allowed_tools=["mcp__bench__stock_price", "mcp__bench__warehouse_stock"],
            system_prompt="You are a helpful assistant. Use the tools you are given, then answer in one sentence.",
        ),
    )
    report("tools", answer)

    for name in ("stock_price", "warehouse_stock"):
        if not answer.used(name):
            raise AssertionError(f"the model never called {name}; it called {answer.tools or 'nothing'}")
    for value in (PRICE, STOCK):
        if not answer.says(value):
            raise AssertionError(f"{value} is missing from the reply: {answer.text.strip()!r}")
    return f"in-process MCP: both tools called, {PRICE} and {STOCK} reported"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
