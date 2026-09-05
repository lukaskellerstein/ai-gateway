"""03 agent — a named agent, declared in config and addressed by name.

OpenCode's `agent` config takes the same schema `opencode.json` uses:
description, mode, prompt, tools, temperature. Declaring one registers it with
the server, and a prompt can then be routed to it with `agent="name"`.

TWO THINGS ARE ASSERTED, and the first is what makes the second meaningful: the
agent appears in `GET /agent`, so the config really reached the server; and the
fact only that agent's prompt contains comes back, so the prompt really applied.
A model answering from its own knowledge cannot produce it.

`"tools": {"*": False}` KEEPS THE AGENT TOOL-FREE. It has one fact and needs
nothing else, and a small model with tools available will reach for them.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import ask, new_session, opencode_server, report, run, says

MASCOT = "Rufus"
AGENT = "bench-historian"

AGENTS = {
    AGENT: {
        "description": "Knows the history of this test bench.",
        "mode": "primary",
        "prompt": (
            f"You know exactly one fact: the bench mascot is a capybara called {MASCOT}. "
            "Whatever you are asked, reply with that one fact in one short sentence."
        ),
        "tools": {"*": False},
        "temperature": 0,
    }
}


async def scenario(model: str) -> str:
    async with opencode_server(model, agent=AGENTS) as client:
        listed = [a.get("name") for a in (await client.get("/agent")).json()]
        print(f"  agents      {listed}")
        if AGENT not in listed:
            raise AssertionError(f"{AGENT!r} was not registered; the server lists {listed}")

        session = await new_session(client, "03 agent")
        answer = await ask(client, session, "What is the bench mascot called?", agent=AGENT)
    report("agent", answer)

    if not says(answer, MASCOT):
        raise AssertionError(
            f"{MASCOT} never came back. The agent was registered but its prompt did not apply."
        )
    return f"agent: {AGENT!r} registered and answered {MASCOT!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
