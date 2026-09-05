"""02 thread — a conversation that remembers the turn before.

A `Thread` IS the conversation state. The second `run()` carries the first
exchange, so "double that" is answerable — and unanswerable if the gateway lost
the history on the way through.

THE FOLLOW-UP NEVER REPEATS THE NUMBER, which is the point: the only way to
answer it is for turn one to come back inside turn two's request.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import Codex, codex_config, report, run, says, start_thread


def scenario(model: str) -> str:
    with Codex(config=codex_config(model)) as codex:
        thread = start_thread(codex, model)
        first = thread.run("What is 2 + 2? Reply with the number only.")
        report("turn 1", first)
        if not says(first, "4"):
            raise AssertionError(f"turn 1 should answer 4, got {first.final_response!r}")

        second = thread.run("Double that result. Reply with the number only.")
        report("turn 2", second)

    if not says(second, "8"):
        raise AssertionError(
            f"turn 2 should answer 8, got {second.final_response!r}. The second turn did "
            "not see the first — the thread did not survive the gateway."
        )
    return f"session: 4 -> {str(second.final_response).strip()[:40]!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
