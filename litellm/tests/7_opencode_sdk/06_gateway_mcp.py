"""06 MCP THROUGH THE GATEWAY — OpenCode is given ONE address, and it is the gateway's.

04 has OpenCode spawn a server of its own. This one registers nothing but
`MCP_URL`, the gateway's `/mcp`, as a `remote` MCP server, and the gateway forwards
to a server OpenCode never learns about: `mcp_server.py`, started here over HTTP on
the port the GATEWAY's config names. That is what "the MCP servers live behind the
gateway" means to a caller: move the server, and this file does not change.

THE BUILT-IN TOOLS ARE SWITCHED OFF FOR THIS PROMPT, as in 04, so the model has no
way to answer except the tool behind the gateway.

THE SERVER'S MARKER IS THE PROOF, as in 04: `.mcp_tool_called` is written only when
the tool really runs, and over HTTP the server's ONLY client is the gateway. THE
PREFIX IS THE SECOND PROOF: the tool the session called carries the gateway's
`<server><sep><tool>`, behind OpenCode's own `gateway_`. It is read from the
session's messages, because `/experimental/tool/ids` lists only OpenCode's built-in
tools and never an MCP one (opencode 1.18.30, 2026-10-07).

Everything specific to a gateway is in settings.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import CALL_MARKER, ask, gateway_mcp_server, new_session, opencode_server, report, run, says, tools_of
from settings import MCP_HEADERS, MCP_TOOL_PREFIX, MCP_URL

SERIAL = "SN-4417-QX"


async def scenario(model: str) -> str:
    CALL_MARKER.unlink(missing_ok=True)

    with gateway_mcp_server():
        async with opencode_server(model) as client:
            added = await client.post(
                "/mcp",
                json={
                    "name": "gateway",
                    "config": {
                        "type": "remote",
                        "url": MCP_URL,
                        "headers": MCP_HEADERS,
                        "enabled": True,
                        "timeout": 60_000,
                    },
                },
            )
            added.raise_for_status()
            print(f"  mcp status  {(await client.get('/mcp')).json()}")

            session = await new_session(client, "06 gateway mcp")
            answer = await ask(
                client,
                session,
                'Use the bench_serial tool to get the serial number of the appliance named "atlas", '
                "then report exactly what it returned.",
                tools={"bash": False, "read": False, "glob": False, "grep": False},
            )
            messages = (await client.get(f"/session/{session}/message")).json()
    called = [name for message in messages for name in tools_of(message)]
    report("gateway mcp", answer)
    print(f"  session     tools called={called}")
    print(f"  marker      tool_called={CALL_MARKER.is_file()}")

    if not CALL_MARKER.is_file():
        raise AssertionError(
            f"the tool behind {MCP_URL} was never called — the model answered without it. "
            "The marker file is the proof; the words in the reply are not."
        )
    if not any(f"{MCP_TOOL_PREFIX}bench_serial" in name for name in called):
        raise AssertionError(f"no tool named {MCP_TOOL_PREFIX}bench_serial was called; the session called {called or 'nothing'}")
    if not says(answer, SERIAL):
        raise AssertionError(f"{SERIAL} is missing from the reply, though the tool ran")
    return f"gateway mcp: tool called through {MCP_URL}, {SERIAL} reported"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
