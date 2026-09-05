"""05 MCP — a server in its OWN PROCESS, reached over stdio.

DeepAgents has no MCP client of its own. `langchain-mcp-adapters` is the bridge:
it spawns the server, lists its tools, and hands them back as ordinary LangChain
tools — which then plug into `tools=` exactly like the `@tool` functions in 04.
That is the whole integration, and it is the shape your own
`3_deepagents/3_mcp` lesson uses.

TWO THINGS DIFFER FROM 04 AND BOTH MATTER:

    the tools are ASYNC, so the agent must be driven with `astream`. Calling
    `stream` on an agent holding MCP tools raises rather than degrading.

    the tool result crosses a PROCESS BOUNDARY, serialised as MCP JSON-RPC. A
    gateway that mangles `tool_calls` passes 04 and fails here.

`sys.executable` IS THIS VENV'S INTERPRETER, so the child gets the same
dependencies without a PATH lookup.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from common import STDIO_SERVER, adrive, build_model, report, run

SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"


async def scenario(model: str) -> str:
    client = MultiServerMCPClient(
        {
            "hardware": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(STDIO_SERVER)],
            }
        }
    )
    tools = await client.get_tools()
    print(f"  MCP tools loaded: {[t.name for t in tools]}")
    if not tools:
        raise AssertionError("the MCP server started but exposed no tools")

    agent = create_deep_agent(
        model=build_model(model),
        tools=tools,
        system_prompt="You are a helpful assistant. Use the tools for real data instead of guessing.",
    )
    answer = await adrive(
        agent,
        "For the appliance named atlas, report its serial number and its firmware version. "
        "Use the tools; do not guess.",
    )
    report(answer)

    for name in ("bench_serial", "bench_firmware"):
        if not answer.used(name):
            raise AssertionError(f"the model never called {name}; it called {answer.tools or 'nothing'}")
    for value in (SERIAL, FIRMWARE):
        if not answer.says(value):
            raise AssertionError(f"{value} is missing from the answer: {answer.text.strip()!r}")
    return f"MCP: {SERIAL} and {FIRMWARE} came back through a child process"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or "", is_async=True))
