"""04 MCP — a server in its own process, added at RUNTIME over the HTTP API.

`POST /mcp` registers an MCP server on a live OpenCode, which is the part worth
copying: nothing is written to any config file, and the server is spawned as a
child process spoken to over stdio.

THE BUILT-IN TOOLS ARE SWITCHED OFF FOR THIS PROMPT. `tools={"bash": False, …}`
leaves the model no way to answer except the MCP tool. Without it a small model
reaches for the shell — which is exactly how the Codex folder's MCP scenario
fails, and OpenCode gives us the lever Codex does not.

TWO MARKERS, NOT THE ANSWER. `mcp_server.py` writes one file when it starts and
another when the tool really runs. A model with shell access can read the serial
number out of the server's source and report it correctly without calling
anything — measured on 2026-09-04 — so an answer-only assertion would pass while
proving nothing.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import (
    CALL_MARKER,
    START_MARKER,
    STDIO_SERVER,
    ask,
    new_session,
    opencode_server,
    report,
    run,
    says,
)

SERIAL = "SN-4417-QX"


async def scenario(model: str) -> str:
    for marker in (START_MARKER, CALL_MARKER):
        marker.unlink(missing_ok=True)

    async with opencode_server(model) as client:
        added = await client.post(
            "/mcp",
            json={
                "name": "hardware",
                "config": {
                    "type": "local",
                    # `sys.executable` is THIS venv's interpreter, so the child
                    # gets the same dependencies without a PATH lookup.
                    "command": [sys.executable, str(STDIO_SERVER)],
                    "enabled": True,
                    "timeout": 60_000,
                },
            },
        )
        added.raise_for_status()
        print(f"  mcp status  {(await client.get('/mcp')).json()}")

        session = await new_session(client, "04 mcp")
        answer = await ask(
            client,
            session,
            'Use the bench_serial tool to get the serial number of the appliance named "atlas", '
            "then report exactly what it returned.",
            tools={"bash": False, "read": False, "glob": False, "grep": False},
        )
    report("mcp", answer)
    print(f"  markers     started={START_MARKER.is_file()} tool_called={CALL_MARKER.is_file()}")

    if not START_MARKER.is_file():
        raise AssertionError(
            f"OpenCode never started the MCP server. Check the command: {STDIO_SERVER}"
        )
    if not CALL_MARKER.is_file():
        raise AssertionError(
            "the MCP server started but its tool was never called — the model answered "
            "without it. The marker file is the proof; the words in the reply are not."
        )
    if not says(answer, SERIAL):
        raise AssertionError(f"{SERIAL} is missing from the reply, though the tool ran")
    return f"mcp: server started, tool called, {SERIAL} reported"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
