"""LangChain and LangGraph, both pointed at the gateway. Two demos, one file.

THE WHOLE TRICK IS THREE ARGUMENTS. The gateway is OpenAI-compatible, so the
official `langchain-openai` package reaches it with no adapter and no plugin:

    ChatOpenAI(model=ALIAS, base_url=BASE_URL, api_key=API_KEY)

Nothing below is gateway-specific after that line. The point of the file is that a
LangChain program written against OpenAI runs against a 4B model on this laptop by
changing where it points, and against a cloud model by changing `GATEWAY_ENGINE` in
../../.env — with no edit here at all.

    demo 1  LangChain   `create_agent` — the prebuilt agent, two tools, one call
    demo 2  LangGraph   the same loop BUILT BY HAND — model node, tool node, and
                        the conditional edge between them

Demo 2 is not a longer way to write demo 1. `create_agent` returns a compiled
graph and hides it; building the graph yourself is what shows where the gateway
sits in an agent — every `llm.invoke` inside `call_model` is ONE HTTP REQUEST to
the gateway, and the loop runs until the model stops asking for tools.

THIS FILE IS BYTE-IDENTICAL IN ALL THREE PROJECTS. It names no port and no
gateway; everything specific comes from ../gateway.py. Keep it that way — a demo
that reads `NAME` to decide what to do has stopped being portable.

    uv run main.py
    uv run main.py --model lms-26b
    uv run main.py --only langgraph
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Annotated

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

# The three shared facts — base URL, key, alias. See ../gateway.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway import ALIAS, API_KEY, BASE_URL, BODY_EXTRAS, MAX_TOKENS, NAME, REQUEST_TIMEOUT_SECONDS  # noqa: E402

# ---------------------------------------------------------------------------
# Two tools that return FIXED NUMBERS
# ---------------------------------------------------------------------------
#
# The same pair `../2_openai_client/02_tools_call.py` uses, and for the same
# reason: a test that calls a real market API cannot tell "the gateway is broken"
# from "the market is closed".
#
# TWO TOOLS, NOT ONE. With a single tool a model that always calls it looks
# correct. Two make the choice observable.

PRICES = {"MSFT": 512.34, "GOOG": 187.65}
DIVIDEND_DATES = {"MSFT": "2026-09-11", "GOOG": "2026-09-15"}


@tool
def get_stock_price(ticker: Annotated[str, "The ticker symbol, e.g. GOOG"]) -> dict:
    """Get the current price of a stock."""
    return {"ticker": ticker, "current_price": PRICES.get(ticker.upper())}


@tool
def get_dividend_date(ticker: Annotated[str, "The ticker symbol, e.g. GOOG"]) -> dict:
    """Get the next dividend payment date of a stock."""
    return {"ticker": ticker, "dividend_date": DIVIDEND_DATES.get(ticker.upper())}


TOOLS = [get_stock_price, get_dividend_date]
QUESTION = "What is the current stock price for MSFT?"
SYSTEM_PROMPT = "You are a helpful assistant. Use the tools when they fit, and be concise."


def build_model(alias: str) -> ChatOpenAI:
    """The one place the gateway is named. Everything else is ordinary LangChain.

    `max_tokens` comes from ../gateway.py: it is None on LiteLLM, whose routes
    store their own ceiling, and 2048 on the two sibling gateways, which store
    none. `max_retries=0` because a silent retry hides the failure this file
    exists to find, and the timeout matches the 3600 s on every local route.
    """
    return ChatOpenAI(
        model=alias,
        base_url=BASE_URL,
        api_key=API_KEY,
        max_tokens=BODY_EXTRAS.get("max_tokens"),
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
        temperature=0,  # an agent that answers differently on Tuesday is a bug
    )


# ---------------------------------------------------------------------------
# Demo 1 — LangChain's prebuilt agent
# ---------------------------------------------------------------------------


def demo_langchain(alias: str) -> str:
    """`create_agent` — the shortest agent in LangChain 1.x.

    It compiles a graph internally and runs the tool loop for you. The gateway
    sees exactly what demo 2 sends it; the difference is only in who wrote the
    loop.
    """
    print("\n--- LangChain: create_agent ---")
    agent = create_agent(build_model(alias), tools=TOOLS, system_prompt=SYSTEM_PROMPT)

    result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})

    for message in result["messages"]:
        calls = getattr(message, "tool_calls", None)
        if calls:
            for call in calls:
                print(f"  tool call    {call['name']}({json.dumps(call['args'])})")
        elif isinstance(message, ToolMessage):
            print(f"  tool result  {message.content}")

    answer = result["messages"][-1].content
    print(f"  answer       {answer}")
    return str(answer)


# ---------------------------------------------------------------------------
# Demo 2 — the same loop, built as a LangGraph by hand
# ---------------------------------------------------------------------------


def demo_langgraph(alias: str) -> str:
    """Two nodes and one conditional edge — the whole ReAct loop, visible.

        START -> model -> (tools_condition) -> tools -> model -> ... -> END

    `MessagesState` is a TypedDict whose single `messages` key APPENDS rather than
    replaces, which is what lets the loop accumulate a conversation instead of
    overwriting it. `tools_condition` reads the last message and routes to
    `tools` when it carries tool calls and to END when it does not.

    EVERY PASS THROUGH `call_model` IS ONE REQUEST TO THE GATEWAY. That is the
    fact worth seeing: an agent is not one call, it is a loop of them, and the
    per-route `timeout: 3600` in ../../config/ exists because each one can be slow.
    """
    print("\n--- LangGraph: StateGraph built by hand ---")
    model = build_model(alias).bind_tools(TOOLS)

    def call_model(state: MessagesState) -> dict:
        print(f"  -> gateway   ({len(state['messages'])} messages in the prompt)")
        return {"messages": [model.invoke([("system", SYSTEM_PROMPT), *state["messages"]])]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")
    graph = builder.compile()

    result = graph.invoke(
        {"messages": [{"role": "user", "content": QUESTION}]},
        # A local model that loses the plot loops forever otherwise. Fail fast.
        config={"recursion_limit": 20},
    )

    for message in result["messages"]:
        calls = getattr(message, "tool_calls", None)
        if calls:
            for call in calls:
                print(f"  tool call    {call['name']}({json.dumps(call['args'])})")
        elif isinstance(message, ToolMessage):
            print(f"  tool result  {message.content}")

    answer = result["messages"][-1].content
    print(f"  answer       {answer}")
    return str(answer)


DEMOS = {"langchain": demo_langchain, "langgraph": demo_langgraph}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=ALIAS, help=f"alias to call (default: {ALIAS})")
    parser.add_argument("--only", choices=sorted(DEMOS), help="run one demo instead of both")
    args = parser.parse_args()

    print(f"\n{'=' * 70}\nLangChain and LangGraph")
    print(f"{NAME} -> {BASE_URL}  model={args.model}  max_tokens={BODY_EXTRAS.get('max_tokens')}")
    print("=" * 70)

    chosen = [args.only] if args.only else sorted(DEMOS)
    started = time.perf_counter()
    summaries: list[str] = []
    try:
        for name in chosen:
            answer = DEMOS[name](args.model)
            # The check is on the TOOL RESULT reaching the final answer. A model
            # that emits tool calls as raw text produces a perfectly readable
            # reply with the number missing, and nothing raises.
            if "512" not in answer:
                raise AssertionError(f"{name}: the tool result 512.34 never reached the answer: {answer!r}")
            summaries.append(f"{name}: {answer.strip()!r}")
        passed = True
    except Exception as error:  # noqa: BLE001 — a failing test reports, it does not crash
        summaries.append(f"{type(error).__name__}: {error}")
        passed = False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {NAME:8s} {seconds:6.1f}s  {' | '.join(summaries)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
