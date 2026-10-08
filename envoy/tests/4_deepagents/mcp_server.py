"""An MCP server in a process of its own. 05_mcp.py runs it over stdio, 08 over HTTP.

NOT A TEST, AND THE RUNNER SKIPS IT: `run_all.py` globs `NN_*.py`, so this name
keeps it out of the suite while 05 and 08 start it themselves.

    uv run python mcp_server.py                 # stdio: 05 spawns it as a child
    uv run python mcp_server.py --http 24090    # HTTP: 08 starts it, THE GATEWAY calls it

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

OVER STDIO THE CLIENT SPAWNS THE COMMAND and the two speak JSON-RPC over this
process's stdin and stdout — which is why nothing here may ever print to stdout. A
stray `print()` corrupts the protocol and the agent sees the server fail to start.

OVER HTTP THE AGENT NEVER SEES THIS SERVER. The gateway's own config names it, on
the port given here, and the agent is handed only the gateway's `/mcp`. So the port
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

# `log_level` KEEPS ITS PER-REQUEST CHATTER OUT OF THE TEST OUTPUT. It goes to
# stderr, so it never corrupted the protocol — it just buried the result.
#
# THE HOST CHECK IS SET HERE AND NOT AT `run()`: in mcp 1.x the HTTP app reads it
# from the server's settings, which the constructor fills. Over stdio it is unused.
server = FastMCP(
    "bench-hardware",
    log_level="ERROR",
    transport_security=TransportSecuritySettings(allowed_hosts=GATEWAY_HOSTS),
)

# UNGUESSABLE ON PURPOSE. A model that invents an answer instead of calling the
# tool cannot produce these, so the assertions in 05 and 08 are about the tool round
# trip and not about the model's general knowledge.
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
    if sys.argv[1:2] == ["--http"]:
        server.settings.port = int(sys.argv[2])
        server.run("streamable-http")
    else:
        server.run("stdio")
