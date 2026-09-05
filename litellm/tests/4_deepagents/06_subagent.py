"""06 subagent — delegation, and the context isolation that is the point of it.

A subagent is a plain dict: `name`, `description`, `system_prompt`, and
optionally its own `tools` or even its own `model`. The parent reaches it with
the built-in `task` tool, naming it in the `subagent_type` argument.

THE POINT IS THE CONTEXT WINDOW, not the tidiness. A subagent runs with its OWN
window and the orchestrator sees only its final answer — never its intermediate
tool calls. That is what makes a long job survivable, and it is also what a
gateway can quietly break: the sub-run is a separate conversation, and its result
is folded back into the parent's next request.

THE FACT LIVES ONLY IN THE SUBAGENT'S PROMPT. No model knows the bench mascot, so
the name can only reach the final answer by travelling out and back. That is the
assertion, and `subagents=` records WHICH helper ran, because every delegation
looks like `task(...)` from the outside.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent

from common import build_model, drive, report, run

MASCOT = "Rufus"
HELPER = "bench-historian"


def scenario(model: str) -> str:
    historian = {
        "name": HELPER,
        "description": "Knows the history of this test bench. Use for any question about the bench itself.",
        # DELIBERATELY NOT ASKED TO THINK. It knows one fact and states it
        # whatever it is asked, because this scenario measures the round trip —
        # delegate, run, join — and not whether a 4B model can hold a
        # conversation with itself.
        "system_prompt": (
            f"You know exactly one fact: the bench mascot is a capybara called {MASCOT}. "
            "Whatever you are asked, reply with that one fact in one short sentence. "
            "Never ask a question back."
        ),
    }

    agent = create_deep_agent(
        model=build_model(model),
        subagents=[historian],
        system_prompt=(
            f"You are an orchestrator. You never answer from memory. Delegate to the "
            f"'{HELPER}' sub-agent with the task tool, wait for its reply, then state the "
            "answer yourself in one short sentence."
        ),
    )
    answer = drive(agent, f"What is the bench mascot called? Ask the {HELPER} sub-agent.")
    report(answer)

    if not answer.used("task"):
        raise AssertionError(
            f"nothing was delegated — the tools called were {answer.tools or 'none'}. "
            "The orchestrator answered by itself instead of asking the sub-agent."
        )
    if HELPER not in answer.subagents:
        raise AssertionError(f"a task ran but not {HELPER!r}; it delegated to {answer.subagents}")
    if not answer.says(MASCOT):
        raise AssertionError(
            f"{MASCOT} never came back: {answer.text.strip()!r}. The sub-agent ran but its "
            "answer did not survive the join into the parent conversation."
        )
    return f"subagent: delegated to {HELPER!r}, {MASCOT!r} came back"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
