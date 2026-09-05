"""02 session — a conversation that remembers the turn before.

A session id IS the conversation. The second prompt carries the first exchange,
so "double that" is answerable — and unanswerable if the gateway lost the
history on the way through. The follow-up never repeats the number.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import ask, new_session, opencode_server, report, run, says


async def scenario(model: str) -> str:
    async with opencode_server(model) as client:
        session = await new_session(client, "02 session")
        first = await ask(client, session, "What is 2 + 2? Reply with the number only.")
        report("turn 1", first)
        if not says(first, "4"):
            raise AssertionError(f"turn 1 should answer 4, got {first!r}")

        second = await ask(client, session, "Double that result. Reply with the number only.")
        report("turn 2", second)

    if not says(second, "8"):
        raise AssertionError(
            "turn 2 should answer 8. The second turn did not see the first — the "
            "session did not survive the gateway."
        )
    return "session: 4 -> 8 in one session"
if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
