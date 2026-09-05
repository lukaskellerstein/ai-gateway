"""04 MCP — the server is wired and offered, and a KNOWN CODEX BUG stops the model.

WHAT THIS ASSERTS, and it is deliberately the wiring rather than the model's
choice: Codex reads the `mcp_servers` config, spawns the server, completes the
JSON-RPC handshake and asks it for its tools. The server writes a marker file
when it starts, and that marker is the assertion.

    ┌─ measured on the wire, 2026-09-04 ────────────────────────────────────┐
    │ --> initialize            clientInfo "codex-mcp-client" 0.147.0       │
    │ <-- capabilities: tools…                                              │
    │ --> notifications/initialized                                         │
    │ --> tools/list                                                        │
    │ <-- tools: [bench_serial …]   with a full inputSchema                 │
    └───────────────────────────────────────────────────────────────────────┘

SO WHY DOES THE MODEL NOT CALL IT? A KNOWN, OPEN CODEX BUG:

    https://github.com/openai/codex/issues/19871
    "MCP tool invocation regressed for custom/local providers (Ollama Responses
     API) in v0.117.0+" — the model answers without making MCP calls even when
     the prompt requires them. Last known good runtime: 0.116.0.

WE MEASURED BOTH SIDES OF IT on 2026-09-04, same server, same prompt, same
`unsloth-4b`:

    codex-cli 0.116.0   the tool RAN.  "The serial number ... is SN-4417-QX."
    codex-cli 0.147.0   the tool never ran; the model shells out instead

0.116.0 is not usable here: its app-server protocol predates this SDK (it
rejects the `auto_review` reviewer and omits `thread.sessionId`), and Envoy
returns 400 for its payload — the class of bug in
https://github.com/envoyproxy/ai-gateway/issues/2586. Pinning it would cost the
SDK, one gateway and the newest-release policy, so we stay on the newest and
keep this note.

A SECOND OPEN BUG SITS BEHIND IT, and matters the moment the first is fixed:

    https://github.com/openai/codex/issues/24135
    there is no supported way to approve MCP tool calls non-interactively.
    `approval_policy="never"`, `tools_require_approval`, `trusted_mcp_servers`
    and per-server `approval_policy` are all SILENTLY IGNORED. A capable model
    calls the tool correctly and Codex answers "This action was rejected due to
    unacceptable risk" — verified through this gateway with a frontier model.

NEXT TIME: open both issues. If they are closed, run this file — it prints
whether the tool was really called. When that line says True, delete this note
and turn the informational check below into an assertion.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import (
    Codex,
    START_MARKER,
    STDIO_SERVER,
    codex_config,
    items_of,
    report,
    run,
    start_thread,
)

BUG = "https://github.com/openai/codex/issues/19871"
CALL_MARKER = START_MARKER.with_name(".mcp_tool_called")


def scenario(model: str) -> str:
    for marker in (START_MARKER, CALL_MARKER):
        marker.unlink(missing_ok=True)

    with Codex(config=codex_config(model)) as codex:
        thread = start_thread(
            codex,
            model,
            config={
                "mcp_servers": {
                    # `sys.executable` is THIS venv's interpreter, so the child
                    # gets the same dependencies without a PATH lookup.
                    "hardware": {"command": sys.executable, "args": [str(STDIO_SERVER)]}
                }
            },
        )
        answer = thread.run(
            "Call the `bench_serial` tool with appliance set to \"atlas\" and "
            "report exactly what it returned."
        )
    report("mcp", answer)

    if not START_MARKER.is_file():
        raise AssertionError(
            "Codex never started the MCP server. The `mcp_servers` config was not read, "
            f"or the command could not be resolved: {STDIO_SERVER}"
        )

    called = CALL_MARKER.is_file()
    print(f"\n  tool really called: {called}")
    if not called:
        print(f"  KNOWN CODEX BUG, open on 2026-09-04: {BUG}")
        print("  MCP tool invocation is regressed for custom providers on the Responses")
        print("  API from 0.117.0. Measured here: 0.116.0 calls it, 0.147.0 does not.")
        print("  Re-check the issue; when it is fixed, make this an assertion.")

    if answer.status is not None and str(answer.status).endswith("failed"):
        raise AssertionError(f"the turn itself failed: {answer.error}")

    state = "and the model CALLED it" if called else "the model did not call it (codex#19871)"
    return f"mcp: server started and tools offered, {state}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
