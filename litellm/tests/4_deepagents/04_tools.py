"""04 tools — your own tools, ADDED to the harness rather than replacing it.

A `@tool` function becomes one more schema beside `write_todos`, `write_file` and
the rest. So this scenario is not really "can the model call a tool" — folder 3
answers that with two tools on the table. It is "can the model pick the right
one out of a dozen", which is the question a deep agent actually poses.

TWO TOOLS, AND ONE QUESTION THAT NEEDS BOTH. With a single tool a model that
always calls the only thing it has looks correct.

THE TOOLS RETURN FIXED NUMBERS. A test calling a real API could not tell "the
gateway is broken" from "the API is down", and the values are unguessable so a
model that invents an answer fails the assertion.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys
from typing import Annotated

from deepagents import create_deep_agent
from langchain_core.tools import tool

from common import build_model, drive, report, run

PRICE = "187.42"
STOCK = "1204"


@tool
def stock_price(ticker: Annotated[str, "The ticker symbol, e.g. ACME"]) -> str:
    """The current share price of a ticker, in USD."""
    return f"{ticker} trades at {PRICE} USD"


@tool
def warehouse_stock(ticker: Annotated[str, "The ticker symbol, e.g. ACME"]) -> str:
    """How many units of a ticker's product are in the warehouse."""
    return f"{ticker} has {STOCK} units in stock"


def scenario(model: str) -> str:
    agent = create_deep_agent(
        model=build_model(model),
        tools=[stock_price, warehouse_stock],
        system_prompt="You are a helpful assistant. Use the tools for real data instead of guessing.",
    )
    answer = drive(
        agent,
        "For the ticker ACME, report the share price and the warehouse unit count. "
        "Use the tools; do not guess.",
    )
    report(answer)

    for name in ("stock_price", "warehouse_stock"):
        if not answer.used(name):
            raise AssertionError(f"the model never called {name}; it called {answer.tools or 'nothing'}")
    for value in (PRICE, STOCK):
        if not answer.says(value):
            raise AssertionError(f"{value} is missing from the answer: {answer.text.strip()!r}")
    return f"tools: both called, {PRICE} and {STOCK} reported"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
