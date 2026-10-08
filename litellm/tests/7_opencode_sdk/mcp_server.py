"""An MCP server in a process of its own. 04_mcp.py runs it over stdio, 06 over HTTP.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while 04 has OpenCode start it and 06 starts it itself.

    uv run python mcp_server.py                 # stdio: OpenCode spawns it as a child
    uv run python mcp_server.py --http 24090    # HTTP: 06 starts it, THE GATEWAY calls it

IT WRITES A MARKER FILE ON STARTUP, and that marker is what 04 asserts on —
proof that OpenCode read the MCP config, resolved the command and got a
live JSON-RPC session. `tool_called` is written only when the tool really runs,
which is how 04 and 06 can report honestly whether the model used it. **A test
that checked only the ANSWER would be wrong**: a model with shell access can read
this file and repeat the serial number without ever calling anything, and one
did exactly that on 2026-09-04.

Nothing here may print to stdout — over stdio that is the JSON-RPC channel.

OVER HTTP THE AGENT NEVER SEES THIS SERVER. The gateway's own config names it, on
the port given here, and OpenCode is handed only the gateway's `/mcp`. So the port
is not this file's choice: settings.py carries the one the gateway expects. It
binds 127.0.0.1; the gateway's container calls it as `host.containers.internal`
(Podman) or `host.docker.internal` (Docker), the same way it reaches the engines.

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

HERE = Path(__file__).resolve().parent
START_MARKER = HERE / ".mcp_server_started"
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

server = MCPServer(name="hardware", version="1.0.0", log_level="ERROR")


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
