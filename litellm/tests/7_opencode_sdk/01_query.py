"""01 one shot — a fresh OpenCode session, one question.

The smallest thing OpenCode can do. It proves the server starts, the custom
provider resolves, the gateway answers, and the reply reaches Python.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import ask, new_session, opencode_server, report, run, says


async def scenario(model: str) -> str:
    async with opencode_server(model) as client:
        session = await new_session(client, "01 one shot")
        answer = await ask(client, session, "What is the capital of France? One short sentence.")
    report("query", answer)

    if not says(answer, "paris"):
        raise AssertionError(f"expected Paris, got {answer!r}")
    return "one shot: answered Paris"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
