"""LangChain and LangGraph, both pointed at the gateway. Three demos, one file.

THE WHOLE TRICK IS THREE ARGUMENTS. The gateway is OpenAI-compatible, so the
official `langchain-openai` package reaches it with no adapter and no plugin:

    ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY)

Nothing below is gateway-specific after that line. The point of the file is that a
LangChain program written against OpenAI runs against a 4B model on this laptop by
changing where it points, and against a cloud model by changing the alias
(`--model`, or AI_GATEWAY_MODEL) — with no edit here at all.

    demo 1  LangChain   `create_agent` — the prebuilt agent, two tools, one call
    demo 2  LangGraph   the same loop BUILT BY HAND — model node, tool node, and
                        the conditional edge between them
    demo 3  MCP         `create_agent` again, its tool BEHIND THE GATEWAY: the agent
                        gets one address, the gateway's `/mcp`, and nothing else

Demo 2 is not a longer way to write demo 1. `create_agent` returns a compiled
graph and hides it; building the graph yourself is what shows where the gateway
sits in an agent — every `llm.invoke` inside `call_model` is ONE HTTP REQUEST to
the gateway, and the loop runs until the model stops asking for tools.

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS. It names no port and no gateway;
everything specific comes from settings.py, the one file to edit when you copy this
folder. Keep it that way — a demo that reads `NAME` to decide what to do has stopped
being portable. `run_benchmark.py` beside it times demo 2's loop on several models.

    uv run run.py
    uv run run.py --model lms-gemma4-26b
    uv run run.py --only langgraph
    uv run run.py --only mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from settings import (
    API_KEY,
    BASE_URL,
    MAX_TOKENS,
    MCP_HEADERS,
    MCP_SERVER_PORT,
    MCP_TOOL_PREFIX,
    MCP_URL,
    MODEL,
    NAME,
    REASONING_EFFORT,
    REQUEST_TIMEOUT_SECONDS,
    STREAM_USAGE,
)

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

    `max_tokens` comes from settings.py: it is None on LiteLLM, whose routes
    store their own ceiling, and 2048 on Envoy, which stores none. `max_retries=0`
    because a silent retry hides the failure this file exists to find, and the
    timeout matches the 3600 s on every local route.
    """
    return ChatOpenAI(
        model=alias,
        base_url=BASE_URL,
        api_key=API_KEY,
        max_tokens=MAX_TOKENS,
        reasoning_effort=REASONING_EFFORT,  # None sends nothing — see settings.py
        stream_usage=STREAM_USAGE,  # read only if you stream — see settings.py
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
    return show(result)["answer"]


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
    return show(result)["answer"]


# ---------------------------------------------------------------------------
# Demo 3 — the prebuilt agent again, its tool BEHIND THE GATEWAY
# ---------------------------------------------------------------------------

SERIAL = "SN-4417-QX"
MCP_QUESTION = "What is the serial number of the appliance named atlas? Use the tool; do not guess."
MCP_SERVER = Path(__file__).resolve().parent / "mcp_server.py"


def demo_mcp(alias: str) -> str:
    """`create_agent` with a tool it gets from the gateway's `/mcp`, not from this file.

    The agent is given ONE address, `MCP_URL`, and the gateway forwards to a
    server the agent never learns about: `mcp_server.py`, started here over HTTP on
    the port the GATEWAY's config names. That is what "the MCP servers live behind
    the gateway" means to a caller: move the server, and this file does not change.
    `langchain-mcp-adapters` turns the gateway's tools into ordinary LangChain
    tools, so they go into `tools=` exactly like the two above.

    THE PREFIX IS THE PROOF. Straight from the server the tool is `bench_serial`;
    through the gateway it is `<server><sep>bench_serial`, and the separator is the
    gateway's own, so settings.py declares it.
    """
    print("\n--- LangChain: create_agent, its tool behind the gateway's /mcp ---")
    return asyncio.run(_demo_mcp(alias))


async def _demo_mcp(alias: str) -> str:
    expected = f"{MCP_TOOL_PREFIX}bench_serial"
    with gateway_mcp_server():
        client = MultiServerMCPClient(
            {"gateway": {"transport": "streamable_http", "url": MCP_URL, "headers": MCP_HEADERS}}
        )
        tools = await client.get_tools()
        names = sorted(tool.name for tool in tools)
        print(f"  MCP tools    {names}  through {MCP_URL}")
        if expected not in names:
            raise AssertionError(f"mcp: the gateway did not offer {expected}; it offered {names or 'nothing'}")

        # MCP TOOLS ARE ASYNC, so the agent is driven with `ainvoke`; `invoke` raises.
        agent = create_agent(build_model(alias), tools=tools, system_prompt=SYSTEM_PROMPT)
        result = await agent.ainvoke({"messages": [{"role": "user", "content": MCP_QUESTION}]})
    shown = show(result)
    if expected not in shown["tools"]:
        raise AssertionError(f"mcp: the model never called {expected}; it called {shown['tools'] or 'nothing'}")
    return shown["answer"]


@contextmanager
def gateway_mcp_server() -> Iterator[None]:
    """Run `mcp_server.py` over HTTP, on the port the GATEWAY expects, for demo 3.

    THE AGENT IS NEVER TOLD THIS PORT. The gateway's own config points at it — an
    `mcp_servers` entry on LiteLLM, an `MCPRoute` on Envoy — and the agent gets only
    `MCP_URL`, so a demo that passes made its calls THROUGH the gateway.

    A PORT THAT IS ALREADY TAKEN FAILS LOUDLY, rather than testing a server some
    other run left behind.
    """
    if _listening(MCP_SERVER_PORT):
        raise RuntimeError(f"port {MCP_SERVER_PORT} is already in use: another run, or a server left behind")
    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen(
            [sys.executable, str(MCP_SERVER), "--http", str(MCP_SERVER_PORT)], stdout=log, stderr=log
        )
        try:
            deadline = time.monotonic() + 30
            while not _listening(MCP_SERVER_PORT):
                if server.poll() is not None or time.monotonic() > deadline:
                    log.seek(0)
                    output = log.read().decode(errors="replace")
                    raise RuntimeError(f"mcp_server.py never listened on {MCP_SERVER_PORT}:\n{output}")
                time.sleep(0.2)
            yield
        finally:
            server.terminate()
            server.wait(timeout=10)


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# What every demo prints, and what main() checks
# ---------------------------------------------------------------------------


def show(result: dict[str, Any]) -> dict[str, Any]:
    """Print each tool call and result, then the answer; return both."""
    called: list[str] = []
    for message in result["messages"]:
        calls = getattr(message, "tool_calls", None)
        if calls:
            for call in calls:
                called.append(call["name"])
                print(f"  tool call    {call['name']}({json.dumps(call['args'])})")
        elif isinstance(message, ToolMessage):
            print(f"  tool result  {message.content}")

    answer = str(result["messages"][-1].content)
    print(f"  answer       {answer}")
    return {"answer": answer, "tools": called}


# Each demo, and the tool result its answer must carry.
DEMOS = {
    "langchain": (demo_langchain, "512"),
    "langgraph": (demo_langgraph, "512"),
    "mcp": (demo_mcp, SERIAL),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=MODEL, help=f"alias to call (default: {MODEL})")
    parser.add_argument("--only", choices=sorted(DEMOS), help="run one demo instead of both")
    args = parser.parse_args()

    print(f"\n{'=' * 70}\nLangChain and LangGraph")
    print(f"{NAME} -> {BASE_URL}  model={args.model}  max_tokens={MAX_TOKENS}  reasoning_effort={REASONING_EFFORT}")
    print("=" * 70)

    chosen = [args.only] if args.only else sorted(DEMOS)
    started = time.perf_counter()
    summaries: list[str] = []
    try:
        for name in chosen:
            demo, expected = DEMOS[name]
            answer = demo(args.model)
            # The check is on the TOOL RESULT reaching the final answer. A model
            # that emits tool calls as raw text produces a perfectly readable
            # reply with the value missing, and nothing raises.
            if expected not in answer:
                raise AssertionError(f"{name}: the tool result {expected} never reached the answer: {answer!r}")
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
