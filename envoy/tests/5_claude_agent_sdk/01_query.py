"""01 query() — one shot, no session, no tools.

The smallest thing the SDK can do, and the first thing to check when anything
else here fails. It proves one fact only: the gateway's Anthropic route answers
and the reply reaches Python.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import agent_options, ask, report, run


async def scenario(model: str) -> str:
    answer = await ask("What is the capital of France?", agent_options(model))
    report("query", answer)

    if answer.is_error:
        raise AssertionError(f"the run reported an error after {answer.turns} turns")
    if not answer.says("paris"):
        raise AssertionError(f"expected Paris, got {answer.text.strip()!r}")
    return f"one shot: {answer.text.strip()[:60]!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
