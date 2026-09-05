"""02 ClaudeSDKClient() — a session that remembers the turn before.

THE ONE THAT CATCHES A BROKEN GATEWAY. A one-shot proves a route exists; a
follow-up proves the whole conversation survives the round trip, which is where a
gateway that translates protocols breaks.

The follow-up says "double that result" and NEVER REPEATS THE NUMBER, so the only
way to answer it is for the first exchange to come back inside the second
request. If the gateway drops, reshapes or rejects any block of the assistant's
own reply, this is the file that goes red.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import ClaudeSDKClient, agent_options, report, run, turn


async def scenario(model: str) -> str:
    async with ClaudeSDKClient(options=agent_options(model)) as client:
        first = await turn(client, "What is 2 + 2? Reply with the number only.")
        report("turn 1", first)
        if not first.says("4"):
            raise AssertionError(f"turn 1 should answer 4, got {first.text.strip()!r}")

        second = await turn(client, "Double that result. Reply with the number only.")
        report("turn 2", second)

    if not second.says("8"):
        raise AssertionError(
            f"turn 2 should answer 8, got {second.text.strip()!r}. The second turn did "
            "not see the first — the session did not survive the gateway."
        )
    return f"session: 4 -> {second.text.strip()[:40]!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
