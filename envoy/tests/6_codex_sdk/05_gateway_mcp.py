"""05 MCP THROUGH THE GATEWAY — wired through `/mcp`; the same Codex bug hides the tool.

04 hands Codex a server of its own. This one hands it nothing but `MCP_URL`, the
gateway's `/mcp`, as a streamable-HTTP server, and the gateway forwards to a server
Codex never learns about: `mcp_server.py`, started here over HTTP on the port the
GATEWAY's config names. That is what "the MCP servers live behind the gateway"
means to a caller: move the server, and this file does not change.

WHAT THIS ASSERTS ON EVERY ALIAS is the wiring: Codex connected to the gateway, asked
it for its tools, and the gateway asked the server. The server writes
`.mcp_tools_listed` when a client lists its tools, and over HTTP its ONLY client is
the gateway. Measured 2026-10-07 on both gateways, so the marker cannot lie:

    no client, 60 s idle          no listing reached the server
    two client listings in a row  both reached it — neither gateway caches the list
    `initialize` alone            no listing

WHAT IT CANNOT ASSERT ON A LOCAL ALIAS is the call, for the reason 04 explains:
openai/codex#19871. Codex sends an MCP server to the model as ONE tool of type
`namespace`, and no local engine understands that shape. THE GATEWAY DOES NOT CHANGE
THAT: it renames the tools, and Codex builds the namespace out of whatever it is
given. So the call is printed on every run and asserted only on the aliases
settings.py names in GATEWAY_MCP_CALLS_THE_TOOL.

THAT SET IS EMPTY ON A GATEWAY WHOSE TOOL LIST CODEX CANNOT READ. Codex 0.155.1 lists
the tools, so the marker is written, and then discards a result it cannot parse —
the model is offered nothing, whatever the model. settings.py says when that is so.

`default_tools_approval_mode = "approve"` is set for the same reason as in 04 —
openai/codex#24135. A headless run has nobody to approve a call.

Everything specific to a gateway is in settings.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys
import tempfile

from common import Codex, START_MARKER, codex_config, gateway_mcp_server, report, run, start_thread
from settings import GATEWAY_MCP_CALLS_THE_TOOL, MCP_HEADERS, MCP_URL

BUG = "https://github.com/openai/codex/issues/19871"
LIST_MARKER = START_MARKER.with_name(".mcp_tools_listed")
CALL_MARKER = START_MARKER.with_name(".mcp_tool_called")


def scenario(model: str) -> str:
    for marker in (LIST_MARKER, CALL_MARKER):
        marker.unlink(missing_ok=True)

    # AN EMPTY WORKING DIRECTORY, so the model has nothing to read: no `mcp_server.py`
    # to copy the serial number out of, and no tree to search for a tool it cannot see.
    with (
        tempfile.TemporaryDirectory(prefix="codex-gateway-mcp-") as empty,
        gateway_mcp_server(),
        Codex(config=codex_config(model)) as codex,
    ):
        thread = start_thread(
            codex,
            model,
            cwd=empty,
            config={
                "mcp_servers": {
                    "gateway": {
                        "url": MCP_URL,
                        "http_headers": MCP_HEADERS,
                        # THE FIX FOR codex#24135 — see 04.
                        "default_tools_approval_mode": "approve",
                    }
                }
            },
        )
        # 04'S PROMPT, PLUS A WAY OUT. Without the last sentence `unsloth-gemma4-26b`
        # cannot see the tool and goes looking for it through a read-only shell: one
        # turn ran 10 minutes and 25 requests, another 40 s (2026-10-07). It also called
        # Codex's own `list_mcp_resources`, a FLAT tool it can see — that is the
        # `mcpToolCall` item such a run shows, and it is not the bench tool.
        answer = thread.run(
            "Call the `bench_serial` tool with appliance set to \"atlas\" and "
            "report exactly what it returned. If you cannot call it, say so in one "
            "sentence and stop; do not look for it anywhere else."
        )
    report("gateway mcp", answer)

    listed, called = LIST_MARKER.is_file(), CALL_MARKER.is_file()
    print(f"\n  tools listed through {MCP_URL}: {listed}")
    print(f"  tool really called: {called}")
    if not listed:
        raise AssertionError(
            f"Codex never listed the tools through {MCP_URL}. The `mcp_servers` config was not "
            "read, or the gateway did not forward the listing to the server."
        )
    if not called and model in GATEWAY_MCP_CALLS_THE_TOOL:
        raise AssertionError(
            f"{model} is in GATEWAY_MCP_CALLS_THE_TOOL and did not call the tool. Read the items line above."
        )
    if not called:
        print(f"  not called: on a local alias {BUG}, as in 04; on this gateway, see settings.py")

    if answer.status is not None and str(answer.status).endswith("failed"):
        raise AssertionError(f"the turn itself failed: {answer.error}")

    state = "and the model CALLED it" if called else "the model did not call it"
    return f"gateway mcp: tools listed through {MCP_URL}, {state}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
