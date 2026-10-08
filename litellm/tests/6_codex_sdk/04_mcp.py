"""04 MCP — wired, offered and pre-approved; a KNOWN CODEX BUG hides the tool from local engines.

WHAT THIS ASSERTS ON EVERY ALIAS is the wiring: Codex reads the `mcp_servers`
config, spawns the server, completes the JSON-RPC handshake and asks it for its
tools. The server writes a marker file when it starts, and that marker is the
assertion.

    ┌─ measured on the wire, 2026-09-04 ────────────────────────────────────┐
    │ --> initialize            clientInfo "codex-mcp-client" 0.147.0       │
    │ <-- capabilities: tools…                                              │
    │ --> notifications/initialized                                         │
    │ --> tools/list                                                        │
    │ <-- tools: [bench_serial …]   with a full inputSchema                 │
    └───────────────────────────────────────────────────────────────────────┘

WHAT IT ASSERTS ON `openrouter-gemma4-26b` ONLY is the CALL: the server's second
marker, written when the tool really runs. Two things stood between the model
and that marker. One is fixed here, one is not.

1. FIXED — THE APPROVAL.  https://github.com/openai/codex/issues/24135

    A headless run has nobody to approve an MCP call. `approval_policy="never"`,
    `tools_require_approval`, `trusted_mcp_servers` and a per-server
    `approval_policy` are all SILENTLY IGNORED: on 2026-09-04 a frontier model
    called the tool correctly and Codex answered "This action was rejected due
    to unacceptable risk". THE KEY THAT WORKS is per server, and it is set below:

        default_tools_approval_mode = "approve"

    Measured 2026-09-23 — codex 0.155.1, `openrouter-gemma4-26b`, approval policy
    `never`, read-only sandbox, an empty CODEX_HOME, THE SAME ON BOTH GATEWAYS:

        items=userMessage,mcpToolCall,agentMessage   status=completed
        tool really called: True        <- the SERVER's marker, not the answer

    The issue is still open upstream, because it asks for a CLI flag. NOT
    MEASURED: the same run WITHOUT the key on 0.155.1 — it costs money, and the
    2026-09-04 refusal is the "before". GUARDED BY: this file on
    `openrouter-gemma4-26b`. Delete the key and that run goes red — it is a paid run,
    so nothing free proves the key is still there.

2. NOT FIXED — THE SHAPE CODEX SENDS.  https://github.com/openai/codex/issues/19871

    From 0.117.0 Codex sends a whole MCP server as ONE tool of type `namespace`:

        {"type": "namespace", "name": "mcp__hardware",
         "tools": [{"type": "function", "name": "bench_serial", …}]}

    The OpenRouter route understands that shape — see above. NO LOCAL ENGINE
    DOES, so the model never sees `bench_serial` as something it can call. It
    shells out, or reads the serial number out of `mcp_server.py`. MEASURED
    2026-09-21 with ONE `/v1/responses` call per shape, no Codex in the path,
    `unsloth-gemma4-26b`, the same on both gateways:

        "type": "namespace"     a plain message, no call
        a flat "function"       function_call {"appliance": "atlas"}

    SO THE GATEWAY AND THE ENGINE ARE FINE, and nothing in Codex turns the shape
    off. `model_providers.<id>` has no such capability in 0.155.1 or in
    0.156.0-alpha.16; `features.non_prefixed_mcp_tool_names` only renames the
    namespace to `hardware` (tested); an empty CODEX_HOME, which cuts the
    request to 13 tools, changes nothing either. Upstream closed both fixes
    unmerged — openai/codex#28271 and #29602. The issue that tracks the real
    fix is https://github.com/openai/codex/issues/26234.

    THE FIXES THAT "WORK" ARE PROXIES: they flatten the tools on the way out and
    restore the names on the way back. That is a shim between Codex and the
    gateway, and this repo proves a gap rather than shimming it.

    The last runtime that sent flat tools is 0.116.0, and it ran this tool on
    2026-09-04. It is not an option: PyPI has no `openai-codex` 0.116.x, so the
    Python SDK cannot drive it.

SO THE RESULT DEPENDS ON THE ALIAS, and this file prints it on every run:

    openrouter-gemma4-26b      tool really called: True      and ASSERTED
    any local alias     tool really called: False     codex#19871, informational

NEXT TIME: open #19871 and #26234. If either is closed, run this file on a LOCAL
alias. When that line says True there too, delete the note above, add the alias
to CALLS_THE_TOOL — or drop the set and assert for everyone.

Everything specific to a gateway is in settings.py. THIS FILE IS BYTE-IDENTICAL
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

# THE ALIASES WHOSE BACKEND UNDERSTANDS CODEX'S `namespace` TOOL SHAPE, measured
# with this file on BOTH gateways, 2026-09-23. On these the call is asserted; on
# every other alias it is reported. Exact names, not a prefix: `openrouter-gemma4-26b-free`
# and the two `openai-*` chat aliases were never run through Codex, and a paid
# alias is not something to guess about.
CALLS_THE_TOOL = frozenset({"openrouter-gemma4-26b"})


def scenario(model: str) -> str:
    for marker in (START_MARKER, CALL_MARKER):
        marker.unlink(missing_ok=True)

    with Codex(config=codex_config(model)) as codex:
        thread = start_thread(
            codex,
            model,
            config={
                "mcp_servers": {
                    "hardware": {
                        # `sys.executable` is THIS venv's interpreter, so the child
                        # gets the same dependencies without a PATH lookup.
                        "command": sys.executable,
                        "args": [str(STDIO_SERVER)],
                        # THE FIX FOR codex#24135. Nobody is there to approve a
                        # call in a headless run, and without this line Codex
                        # rejects it. It covers THIS server's tools only; the
                        # sandbox and `deny_all` still hold for everything else.
                        "default_tools_approval_mode": "approve",
                    }
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
    if not called and model in CALLS_THE_TOOL:
        raise AssertionError(
            f"{model} called this tool on 2026-09-23 and did not now. Either the "
            "`default_tools_approval_mode` key above was removed (codex#24135 is back), "
            "or the model no longer sees `namespace` tools. Read the items line above."
        )
    if not called:
        print(f"  KNOWN CODEX BUG, still open on 2026-09-23: {BUG}")
        print("  Codex sends an MCP server as ONE tool of type `namespace`. No local engine")
        print("  understands that shape, so the model never sees the tool. Measured on both")
        print("  gateways: the same tool as a flat function IS called. Approval is not the")
        print("  blocker any more. When a LOCAL alias prints True, add it to CALLS_THE_TOOL.")

    if answer.status is not None and str(answer.status).endswith("failed"):
        raise AssertionError(f"the turn itself failed: {answer.error}")

    state = "and the model CALLED it" if called else "the model did not call it (codex#19871)"
    return f"mcp: server started and tools offered, {state}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
