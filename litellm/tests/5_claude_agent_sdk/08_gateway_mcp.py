"""08 MCP THROUGH THE GATEWAY — the agent is given ONE address, and it is the gateway's.

04 hands the agent a server of its own. This one hands it nothing but `MCP_URL`,
the gateway's `/mcp`, as an `http` MCP server, and the gateway forwards to a
server the agent never learns about: `mcp_server.py`, started here over HTTP on the
port the GATEWAY's config names. That is what "the MCP servers live behind the
gateway" means to a caller: move the server, and this file does not change.

ONE GATEWAY, TWO SURFACES. The model's requests go to the Anthropic route and the
tool calls go to `/mcp`, and neither surface knows about the other. The agent's
loop is what joins them.

THE PREFIX IS THE PROOF. Straight from the server the tools are `bench_serial` and
`bench_firmware`. Through the gateway they arrive renamed `<server><sep><tool>`,
and the separator is the gateway's own, so settings.py declares it. The CLI then
adds its own `mcp__gateway__` in front. `allowed_tools` names the full result, so a
tool that did not come through the gateway is not even callable.

Everything specific to a gateway is in settings.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import agent_options, ask, gateway_mcp_server, report, run
from settings import MCP_HEADERS, MCP_TOOL_PREFIX, MCP_URL

SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"
TOOLS = [f"mcp__gateway__{MCP_TOOL_PREFIX}{name}" for name in ("bench_serial", "bench_firmware")]


async def scenario(model: str) -> str:
    with gateway_mcp_server():
        answer = await ask(
            "For the appliance named atlas, report its serial number and its firmware version. "
            "Use the tools; do not guess.",
            agent_options(
                model,
                mcp_servers={"gateway": {"type": "http", "url": MCP_URL, "headers": MCP_HEADERS}},
                allowed_tools=TOOLS,
                system_prompt="You are a helpful assistant. Use the tools you are given, then answer in one sentence.",
            ),
        )
    report("gateway mcp", answer)

    for name in TOOLS:
        if name not in answer.tools:
            raise AssertionError(f"the model never called {name}; it called {answer.tools or 'nothing'}")
    for value in (SERIAL, FIRMWARE):
        if not answer.says(value):
            raise AssertionError(f"{value} is missing from the reply: {answer.text.strip()!r}")
    return f"gateway MCP: {SERIAL} and {FIRMWARE} came back through {MCP_URL}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
