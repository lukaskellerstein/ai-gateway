"""An MCP server in a process of its own. Scenario 04 runs it over stdio, 08 over HTTP.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while 04 and 08 start it themselves.

    uv run python mcp_server.py                 # stdio: 04 spawns it as a child
    uv run python mcp_server.py --http 24090    # HTTP: 08 starts it, THE GATEWAY calls it

STDIO IS THE TRANSPORT REAL MCP SERVERS USE. The client spawns the command, and
the two speak JSON-RPC over the child's stdin and stdout — which is why this file
must never print anything to stdout. A stray `print()` here corrupts the protocol
and the agent sees the server fail to start.

OVER HTTP THE AGENT NEVER SEES THIS SERVER. The gateway's own config names it, on
the port given here, and the agent is handed only the gateway's `/mcp`. So the port
is not this file's choice: settings.py carries the one the gateway expects.

IT BINDS 127.0.0.1, so nothing off this machine reaches it. The gateway runs in a
container and calls it as `host.containers.internal` (Podman) or
`host.docker.internal` (Docker) — the same way it reaches the three engines.

THE ALLOWED HOSTS ARE THE TRAP. On 127.0.0.1 the SDK switches on DNS-rebinding
protection and accepts only `Host: 127.0.0.1`, `localhost` and `[::1]`, so the
gateway's request carries a host it refuses with a 421. Both container names are
added below, and the protection stays on. EACH NAME IS LISTED TWICE because the two
gateways send it differently, measured 2026-10-07: LiteLLM sends
`host.containers.internal:24090`, Envoy sends `host.docker.internal` with NO port,
and a `name:*` pattern matches only a host that carries one.

It is written against `mcp` 2.x, where FastMCP became `MCPServer`.
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

server = MCPServer(name="bench-hardware", version="1.0.0", log_level="ERROR")

# UNGUESSABLE ON PURPOSE. A model that invents an answer instead of calling the
# tool cannot produce these, so the assertions in 04 and 08 are about the tool round
# trip and not about the model's general knowledge.
SERIAL = "SN-4417-QX"
FIRMWARE = "8.3.1-rc4"

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


@server.tool(description="The serial number of the bench appliance with this name")
def bench_serial(appliance: str) -> str:
    return f"The serial number of {appliance} is {SERIAL}."


@server.tool(description="The firmware version running on the bench appliance with this name")
def bench_firmware(appliance: str) -> str:
    return f"{appliance} runs firmware {FIRMWARE}."


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
