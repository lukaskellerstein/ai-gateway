"""07 thinking — a reasoning model, and the bug this whole folder was built around.

TWO THINGS ARE CHECKED HERE, and the first is a regression guard.

**A thinking-enabled conversation must survive turn two.** The model reasons, the
gateway returns the reasoning as a `thinking` block, and the SDK sends that block
back inside the next request. That round trip is what used to fail: on Envoy's
translated route the block lands in an OpenAI body, where a `content` part may
only be `text` or `image_url`, and the ENGINE answers
`400 messages.N.content.str`. It failed about one run in five, because the model
reasons on some replies and not others.

The follow-up says "double that result" and never repeats the number, so it can
only be answered if turn one — thinking block and all — came back intact.

**And the reasoning either reaches the caller or it does not.** That is a real
difference between the two gateways, so it is DECLARED as
`THINKING_REACHES_CLIENT` in common.py and checked here rather than described in
prose. Measured 2026-09-04 on the same engine with the same prompt:

    Envoy    the `-anthropic` alias does not translate, so the engine's own
             thinking block arrives whole
    LiteLLM  `/v1/chat/completions` gives 1115 characters of `reasoning_content`
             and `/v1/messages` gives `content: []` — an EMPTY 200

A failure here reads "the table says X and the gateway did Y", which is the same
contract this suite applies to the OpenAI surface in
`../2_openai_client/04_gateway_contract.py`.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import (
    THINKING_NOTE,
    THINKING_REACHES_CLIENT,
    ClaudeSDKClient,
    agent_options,
    reasoning_baseline,
    report,
    run,
    turn,
)

PRODUCT = "391"
DOUBLED = "782"


async def scenario(model: str) -> str:
    options = agent_options(
        model,
        # ASKED FOR EXPLICITLY, not left to the CLI's default. The point of this
        # scenario is a reply that CARRIES reasoning, so the budget is stated.
        thinking={"type": "enabled", "budget_tokens": 1024},
        system_prompt="Think step by step, then answer with the number only.",
    )
    async with ClaudeSDKClient(options=options) as client:
        first = await turn(client, "What is 17 * 23? Think it through.")
        report("turn 1", first)
        second = await turn(client, "Now double that result. Reply with the number only.")
        report("turn 2", second)

    if not first.says(PRODUCT):
        raise AssertionError(f"turn 1 should answer {PRODUCT}, got {first.text.strip()!r}")
    if not second.says(DOUBLED):
        raise AssertionError(
            f"turn 2 should answer {DOUBLED}, got {second.text.strip()!r}. The reasoning "
            "turn did not survive the round trip — this is the failure the pass-through "
            "alias exists to prevent."
        )

    # WHAT THE ROUTE PRODUCES BEFORE ANY TRANSLATION. Without it this scenario
    # cannot tell a gateway that LOST the reasoning from a model that never made
    # any, and it reported the second as the first on `openrouter-26b`.
    baseline = reasoning_baseline(model)
    reached = first.thinking_chars > 0
    print(f"  {'baseline':12s} {baseline} chars of reasoning_content on /v1/chat/completions")

    if baseline == 0:
        # NOTHING TO CARRY, so there is nothing to lose and nothing to assert.
        # This is NOT a skip: the two-turn round trip above was checked in full,
        # which is the half of this scenario that does not need reasoning.
        return (
            f"thinking: {PRODUCT} -> {DOUBLED} across two turns; this route produces no "
            "reasoning at all, so the gateway had nothing to carry"
        )

    if reached != THINKING_REACHES_CLIENT:
        raise AssertionError(
            f"common.py declares THINKING_REACHES_CLIENT={THINKING_REACHES_CLIENT} and this "
            f"gateway returned {first.thinking_chars} characters of thinking, while the same "
            f"route produced {baseline} characters on /v1/chat/completions. The reasoning "
            "EXISTS and the Anthropic route lost it — check "
            "`use_chat_completions_url_for_anthropic_messages` in ../../config/settings.yaml "
            "before assuming the declaration is stale."
        )

    carried = f"{first.thinking_chars} chars reached the client, {baseline} upstream"
    # THE WARNING IS PRINTED WHETHER OR NOT THE ROW IS GREEN. A known upstream bug
    # that only shows up in a source comment is a bug nobody re-checks.
    if THINKING_NOTE:
        print(f"\n  NOTE  {THINKING_NOTE}")
    return f"thinking: {PRODUCT} -> {DOUBLED} across two turns, {carried}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
