"""04 MCP — a server in its OWN PROCESS, reached over stdio.

The same idea as 03 and the opposite mechanism. Here the SDK spawns
`mcp_server.py` as a child process and the two speak JSON-RPC over its stdin and
stdout. This is the transport every MCP server you install from someone else
uses, so it is the one to copy when wiring a real server into an agent.

WHAT THIS PROVES BEYOND 03: the tool result crosses a process boundary, is
serialised as MCP JSON-RPC, and comes back through the gateway inside the
agent's next request. A gateway that mangles `tool_use` or `tool_result` blocks
passes 01 and 02 and fails here.

`sys.executable` IS THE INTERPRETER OF THIS VENV, so the child gets the same
dependencies without any PATH lookup. Naming `python` instead would find whatever
the shell happens to have.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import STDIO_SERVER, agent_options, ask, report, run

SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"


async def scenario(model: str) -> str:
    answer = await ask(
        "For the appliance named atlas, report its serial number and its firmware version. "
        "Use the tools; do not guess.",
        agent_options(
            model,
            mcp_servers={
                "hardware": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [str(STDIO_SERVER)],
                }
            },
            allowed_tools=["mcp__hardware__bench_serial", "mcp__hardware__bench_firmware"],
            system_prompt="You are a helpful assistant. Use the tools you are given, then answer in one sentence.",
        ),
    )
    report("stdio mcp", answer)

    for name in ("bench_serial", "bench_firmware"):
        if not answer.used(name):
            raise AssertionError(f"the model never called {name}; it called {answer.tools or 'nothing'}")
    for value in (SERIAL, FIRMWARE):
        if not answer.says(value):
            raise AssertionError(f"{value} is missing from the reply: {answer.text.strip()!r}")
    return f"stdio MCP: {SERIAL} and {FIRMWARE} came back through a child process"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
