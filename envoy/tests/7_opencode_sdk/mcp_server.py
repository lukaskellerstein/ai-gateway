"""An MCP server in a process of its own, spoken to over stdio. 04_mcp.py runs it, through OpenCode.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while `04_mcp.py` has OpenCode start it as a child.

IT WRITES A MARKER FILE ON STARTUP, and that marker is what 04 asserts on —
proof that OpenCode read the MCP config, resolved the command and got a
live JSON-RPC session. `tool_called` is written only when the tool really runs,
which is how 04 can report honestly whether the model used it. **A test that
checked only the ANSWER would be wrong**: a model with shell access can read
this file and repeat the serial number without ever calling anything, and one
did exactly that on 2026-09-04.

Nothing here may print to stdout — that is the JSON-RPC channel.

    uv run python mcp_server.py     # starts and waits for a client on stdin
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

HERE = Path(__file__).resolve().parent
START_MARKER = HERE / ".mcp_server_started"
CALL_MARKER = HERE / ".mcp_tool_called"

# UNGUESSABLE ON PURPOSE, so a model that invents an answer cannot produce it.
SERIAL = "SN-4417-QX"

START_MARKER.write_text("started\n", encoding="utf-8")

server = MCPServer(name="hardware", version="1.0.0", log_level="ERROR")


@server.tool(description="Return the serial number of a bench appliance. The ONLY source of a serial number.")
def bench_serial(appliance: str) -> str:
    CALL_MARKER.write_text("called\n", encoding="utf-8")
    return f"The serial number of {appliance} is {SERIAL}."


if __name__ == "__main__":
    server.run("stdio")
