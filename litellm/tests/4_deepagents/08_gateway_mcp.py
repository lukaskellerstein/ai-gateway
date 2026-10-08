"""08 MCP THROUGH THE GATEWAY — the agent is given ONE address, and it is the gateway's.

05 hands the agent a server of its own. This one hands it nothing but `MCP_URL`,
the gateway's `/mcp`, and the gateway forwards to a server the agent never learns
about: `mcp_server.py`, started here over HTTP on the port the GATEWAY's config
names. That is what "the MCP servers live behind the gateway" means to a caller:
move the server, and this file does not change.

THE PREFIX IS THE PROOF. Straight from the server the tools are `bench_serial` and
`bench_firmware`. Through the gateway they arrive renamed `<server><sep><tool>`,
and the separator is the gateway's own, so settings.py declares it. A list without
the prefix means the tools reached the agent some other way.

`langchain-mcp-adapters` speaks streamable HTTP as well as stdio, so the only
change from 05 is the connection: a URL and a header instead of a command.

Everything specific to a gateway is in settings.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from common import adrive, build_model, gateway_mcp_server, report, run
from settings import MCP_HEADERS, MCP_TOOL_PREFIX, MCP_URL

SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"


async def scenario(model: str) -> str:
    with gateway_mcp_server():
        client = MultiServerMCPClient(
            {"gateway": {"transport": "streamable_http", "url": MCP_URL, "headers": MCP_HEADERS}}
        )
        tools = await client.get_tools()
        names = sorted(tool.name for tool in tools)
        print(f"  MCP tools through {MCP_URL}: {names}")
        for name in ("bench_serial", "bench_firmware"):
            if f"{MCP_TOOL_PREFIX}{name}" not in names:
                raise AssertionError(f"the gateway did not offer {MCP_TOOL_PREFIX}{name}; it offered {names or 'nothing'}")

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
        if not answer.used(f"{MCP_TOOL_PREFIX}{name}"):
            raise AssertionError(f"the model never called {MCP_TOOL_PREFIX}{name}; it called {answer.tools or 'nothing'}")
    for value in (SERIAL, FIRMWARE):
        if not answer.says(value):
            raise AssertionError(f"{value} is missing from the answer: {answer.text.strip()!r}")
    return f"gateway MCP: {SERIAL} and {FIRMWARE} came back through {MCP_URL}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or "", is_async=True))
