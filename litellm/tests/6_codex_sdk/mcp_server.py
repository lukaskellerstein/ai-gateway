"""An MCP server in a process of its own. 04_mcp.py runs it over stdio, 05 over HTTP.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while 04 has Codex start it and 05 starts it itself.

    uv run python mcp_server.py                 # stdio: Codex spawns it as a child
    uv run python mcp_server.py --http 24090    # HTTP: 05 starts it, THE GATEWAY calls it

IT WRITES MARKER FILES, and the markers are what 04 and 05 assert on:

    .mcp_server_started   this process started. Over stdio that proves Codex read
                          the `mcp_servers` config and spawned the command
    .mcp_tools_listed     a client asked for the tools. Over HTTP the only client
                          is the GATEWAY, so this proves Codex reached the server
                          THROUGH it — 05's wiring assertion
    .mcp_tool_called      the tool really ran

**A test that checked only the ANSWER would be wrong**: a model with shell access
can read this file and repeat the serial number without ever calling anything, and
one did exactly that on 2026-09-04.

Nothing here may print to stdout — over stdio that is the JSON-RPC channel.

OVER HTTP THE AGENT NEVER SEES THIS SERVER. The gateway's own config names it, on
the port given here, and Codex is handed only the gateway's `/mcp`. So the port is
not this file's choice: settings.py carries the one the gateway expects. It binds
127.0.0.1; the gateway's container calls it as `host.containers.internal` (Podman)
or `host.docker.internal` (Docker), the same way it reaches the three engines.

THE ALLOWED HOSTS ARE THE TRAP. On 127.0.0.1 the SDK switches on DNS-rebinding
protection and accepts only `Host: 127.0.0.1`, `localhost` and `[::1]`, so the
gateway's request carries a host it refuses with a 421. Both container names are
added below, and the protection stays on. EACH NAME IS LISTED TWICE because the two
gateways send it differently, measured 2026-10-07: LiteLLM sends
`host.containers.internal:24090`, Envoy sends `host.docker.internal` with NO port,
and a `name:*` pattern matches only a host that carries one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import Tool

HERE = Path(__file__).resolve().parent
START_MARKER = HERE / ".mcp_server_started"
LIST_MARKER = HERE / ".mcp_tools_listed"
CALL_MARKER = HERE / ".mcp_tool_called"

# UNGUESSABLE ON PURPOSE, so a model that invents an answer cannot produce it.
SERIAL = "SN-4417-QX"

# The SDK's own three, plus the two names a container gives this host — with and
# without a port.
GATEWAY_HOSTS = [
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "host.containers.internal",
    "host.containers.internal:*",
    "host.docker.internal",
    "host.docker.internal:*",
]

START_MARKER.write_text("started\n", encoding="utf-8")


class BenchServer(MCPServer):
    """`MCPServer`, with a marker written whenever a client lists the tools."""

    async def list_tools(self) -> list[Tool]:
        LIST_MARKER.write_text("listed\n", encoding="utf-8")
        return await super().list_tools()


server = BenchServer(name="hardware", version="1.0.0", log_level="ERROR")


@server.tool(description="Return the serial number of a bench appliance. The ONLY source of a serial number.")
def bench_serial(appliance: str) -> str:
    CALL_MARKER.write_text("called\n", encoding="utf-8")
    return f"The serial number of {appliance} is {SERIAL}."


if __name__ == "__main__":
    if sys.argv[1:2] == ["--http"]:
        server.run(
            "streamable-http",
            host="127.0.0.1",
            port=int(sys.argv[2]),
            transport_security=TransportSecuritySettings(allowed_hosts=GATEWAY_HOSTS),
        )
    else:
        server.run("stdio")
