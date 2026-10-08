"""The MCP server behind the gateway. run.py's demo 3 starts it over HTTP.

NOT RUN BY HAND, and not a demo: run.py starts it on the port the GATEWAY's config
names and stops it when demo 3 is done.

    uv run python mcp_server.py --http 24090    # what run.py runs

THE AGENT NEVER SEES THIS SERVER. The gateway's own config names it, on the port
given here, and the agent is handed only the gateway's `/mcp`. So the port is not
this file's choice: settings.py carries the one the gateway expects. It binds
127.0.0.1; the gateway's container calls it as `host.containers.internal` (Podman)
or `host.docker.internal` (Docker), the same way it reaches the three engines.

THE ALLOWED HOSTS ARE THE TRAP. On 127.0.0.1 the SDK switches on DNS-rebinding
protection and accepts only `Host: 127.0.0.1`, `localhost` and `[::1]`, so the
gateway's request carries a host it refuses with a 421. Both container names are
added below, and the protection stays on. EACH NAME IS LISTED TWICE because the two
gateways send it differently, measured 2026-10-07: LiteLLM sends
`host.containers.internal:24090`, Envoy sends `host.docker.internal` with NO port,
and a `name:*` pattern matches only a host that carries one.

WRITTEN AGAINST `FastMCP`, THE mcp 1.x API, because `langchain-mcp-adapters` caps
this folder's venv at `mcp<2`. The wire does not care: folder 4 measured a 1.x
client against a 2.x server (2026-09-04).
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

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

# `log_level` keeps per-request chatter out of run.py's output. THE HOST CHECK IS SET
# HERE AND NOT AT `run()`: in mcp 1.x the HTTP app reads it from the server's
# settings, which the constructor fills.
server = FastMCP(
    "bench-hardware",
    log_level="ERROR",
    transport_security=TransportSecuritySettings(allowed_hosts=GATEWAY_HOSTS),
)

# UNGUESSABLE ON PURPOSE. A model that invents an answer instead of calling the
# tool cannot produce it, so demo 3's check is about the tool round trip and not
# about the model's general knowledge.
SERIAL = "SN-4417-QX"


@server.tool()
def bench_serial(appliance: str) -> str:
    """The serial number of the bench appliance with this name."""
    return f"The serial number of {appliance} is {SERIAL}."


if __name__ == "__main__":
    if sys.argv[1:2] != ["--http"]:
        sys.exit("usage: mcp_server.py --http PORT")
    server.settings.port = int(sys.argv[2])
    server.run("streamable-http")
