"""An MCP server in a process of its own, spoken to over stdio. Scenario 04 runs it.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while `04_stdio_mcp.py` starts it as a child process.

THIS IS THE TRANSPORT REAL MCP SERVERS USE. The client spawns the command, and
the two speak JSON-RPC over the child's stdin and stdout — which is why this file
must never print anything to stdout. A stray `print()` here corrupts the protocol
and the agent sees the server fail to start.

It is written against `mcp` 2.x, where FastMCP became `MCPServer`.

    uv run python mcp_server.py     # starts and waits for a client on stdin
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="bench-hardware", version="1.0.0")

# UNGUESSABLE ON PURPOSE. A model that invents an answer instead of calling the
# tool cannot produce these, so the assertion in 04 is about the tool round trip
# and not about the model's general knowledge.
SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"


@server.tool(description="The serial number of the bench appliance with this name")
def bench_serial(appliance: str) -> str:
    return f"The serial number of {appliance} is {SERIAL}."


@server.tool(description="The firmware version running on the bench appliance with this name")
def bench_firmware(appliance: str) -> str:
    return f"{appliance} runs firmware {FIRMWARE}."


if __name__ == "__main__":
    server.run("stdio")
