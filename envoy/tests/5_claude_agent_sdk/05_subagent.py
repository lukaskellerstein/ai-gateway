"""05 subagent — one agent delegating to another, through the same gateway.

`AgentDefinition` declares a named helper with its own system prompt and its own
tool list. The main agent reaches it with the delegation tool, and the helper's
whole conversation is a SEPARATE run against the gateway — so this scenario opens
two agent loops, not one.

WHY IT IS WORTH TESTING A GATEWAY WITH. Delegation multiplies every weakness: the
sub-run's transcript is summarised back into the parent's next request, so a
gateway that loses or reshapes a block fails on the join rather than on the call.
It is also the first scenario here where the model must choose to hand work over
instead of answering from its own knowledge.

THE FACT LIVES ONLY IN THE SUBAGENT'S PROMPT. No model knows the bench mascot, so
the name can only reach the final answer by travelling out to the subagent and
back. That is the assertion.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from claude_agent_sdk import AgentDefinition

from common import agent_options, ask, report, run

MASCOT = "Rufus"


async def scenario(model: str) -> str:
    answer = await ask(
        "Ask the bench-historian subagent what the bench mascot is called. "
        "Then state the name yourself in one short sentence.",
        agent_options(
            model,
            agents={
                "bench-historian": AgentDefinition(
                    description="Knows the history of this test bench. Use for any question about the bench itself.",
                    # THE SUBAGENT IS DELIBERATELY NOT ASKED TO THINK. It knows
                    # one fact and states it whatever it is asked, because this
                    # scenario measures the ROUND TRIP — delegate, run, join — and
                    # not whether a 4B model can hold a conversation with itself.
                    # Left open-ended, LMStudio's gemma answered a clarifying
                    # question instead of the fact and the run looped out of turns
                    # (measured 2026-09-04).
                    prompt=(
                        "You are the historian of this test bench. You know exactly one fact: "
                        f"the bench mascot is a capybara called {MASCOT}. "
                        "Whatever you are asked, reply with that one fact in one short "
                        "sentence. Never ask a question back."
                    ),
                    tools=[],
                    # FOREGROUND, EXPLICITLY. Left unset the CLI may start the
                    # helper in the background, and then the parent ends its turn
                    # with "I will tell you once the agent finishes" — a reply that
                    # never contains the answer. Measured on LiteLLM 2026-09-04,
                    # 1 run in 6.
                    background=False,
                )
            },
            # `tools` IS THE VISIBILITY LIST AND `allowed_tools` IS THE PERMISSION
            # LIST. They are not the same lever, and only the first one narrows
            # what the model can see. Left wide, the CLI also offers `SendMessage`
            # and `ListAgents` — the teammate tools — and a small model reaches for
            # those instead, then reports that no such teammate exists (measured on
            # LiteLLM, 2026-09-04, 2 runs in 3).
            tools=["Agent"],
            allowed_tools=["Agent"],
            # THE SUBAGENT'S OWN WORDS ARE NOT MIXED INTO THIS TRANSCRIPT. With
            # forwarding on, the helper's reply appears in the stream and the
            # assertion below would pass on text that never reached the parent.
            # Off, the mascot's name can only be here because the parent read the
            # sub-run's result and wrote it into its own answer — which is the
            # join this scenario exists to test.
            forward_subagent_text=False,
            system_prompt=(
                "You are an orchestrator. Delegate to a subagent rather than answering "
                "from memory. Wait for the subagent to reply, then give the answer "
                "yourself. Never end your turn promising a later answer."
            ),
            max_turns=8,
        ),
    )
    report("subagent", answer)

    if not (answer.used("Task") or answer.used("Agent")):
        raise AssertionError(
            f"nothing was delegated — the tools called were {answer.tools or 'none'}. "
            "The main agent answered by itself instead of asking the subagent."
        )
    if not answer.says(MASCOT):
        raise AssertionError(
            f"{MASCOT} never came back: {answer.text.strip()!r}. The subagent ran but its "
            "answer did not survive the join into the parent conversation."
        )
    return f"subagent: delegated, {MASCOT!r} came back"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
