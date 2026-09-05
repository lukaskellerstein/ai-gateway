"""An MCP server in a process of its own, spoken to over stdio. 05_mcp.py runs it.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while `05_mcp.py` starts it as a child process.

WRITTEN AGAINST `FastMCP`, THE mcp 1.x API — and folder 5's copy of this file is
written against `MCPServer`, the 2.x replacement. THE PROTOCOL DOES NOT CARE, and
that was measured rather than assumed: this folder's mcp 1.29.1 client discovered
and called folder 5's mcp 2.1.1 server across two venvs without complaint
(2026-09-04). Version skew is a Python packaging concern, not a wire concern.

SO WHY TWO FILES? Because `05_mcp.py` spawns this server with `sys.executable` —
THIS folder's interpreter — which keeps the folder copyable on its own. That
interpreter is pinned to `mcp<2`, because `langchain-mcp-adapters` imports
`mcp.shared.context.RequestContext` and mcp 2.x removed it; without the pin the
CLIENT fails at import, before any server starts. Reaching into folder 5's venv
for one shared file would trade that self-containment for forty saved lines.

THE CLIENT SPAWNS THE COMMAND and the two speak JSON-RPC over this process's
stdin and stdout — which is why nothing here may ever print to stdout. A stray
`print()` corrupts the protocol and the agent sees the server fail to start.

    uv run python mcp_server.py     # starts and waits for a client on stdin
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# `log_level` KEEPS ITS PER-REQUEST CHATTER OUT OF THE TEST OUTPUT. It goes to
# stderr, so it never corrupted the protocol — it just buried the result.
server = FastMCP("bench-hardware", log_level="ERROR")

# UNGUESSABLE ON PURPOSE. A model that invents an answer instead of calling the
# tool cannot produce these, so the assertion in 05 is about the tool round trip
# and not about the model's general knowledge.
SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"


@server.tool()
def bench_serial(appliance: str) -> str:
    """The serial number of the bench appliance with this name."""
    return f"The serial number of {appliance} is {SERIAL}."


@server.tool()
def bench_firmware(appliance: str) -> str:
    """The firmware version running on the bench appliance with this name."""
    return f"{appliance} runs firmware {FIRMWARE}."


if __name__ == "__main__":
    server.run("stdio")
