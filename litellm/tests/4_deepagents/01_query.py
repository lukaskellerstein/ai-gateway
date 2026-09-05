"""01 one shot — a deep agent with nothing added, answering one question.

The smallest thing a deep agent can do, and the first thing to check when
anything else here fails. It proves the harness starts, the gateway answers, and
the reply reaches Python.

NOTE WHAT IS ALREADY THERE. Even with no tools of your own, the agent is holding
a todo list, a virtual filesystem and a subagent spawner — about a dozen tool
schemas in front of every turn. A model that answers a plain question here
without reaching for any of them is behaving correctly.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent

from common import build_model, drive, report, run


def scenario(model: str) -> str:
    agent = create_deep_agent(
        model=build_model(model),
        system_prompt="You are a helpful assistant. Answer in one short sentence.",
    )
    answer = drive(agent, "What is the capital of France?")
    report(answer)

    if not answer.says("paris"):
        raise AssertionError(f"expected Paris, got {answer.text.strip()!r}")
    return f"one shot: {answer.text.strip()[:60]!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
