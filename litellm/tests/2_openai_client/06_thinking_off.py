"""Test 6 — a `-fast` alias answers with thinking OFF, where its base alias thinks.

THIS IS ALSO THE EXAMPLE OF CALLING ONE: the caller changes the model name and
nothing else. The two calls of each pair below differ only in `model`. The gateway
stores the switch on the route, so a client written for `unsloth-gemma4-26b` gets
the fast answer by asking for `unsloth-gemma4-26b-fast`.

EACH UNSLOTH ROUTE OBEYS A DIFFERENT FIELD, which is why both routes are checked:
chat completions obeys `enable_thinking`, /v1/responses — Codex's route — obeys
`chat_template_kwargs`, and the route stores both. Delete either and one half of
this script goes red. The caller's own thinking level from `body_extras` goes along,
as an agent's would, and must not turn thinking back on.

THE BASE ALIAS IS THE WITNESS: the same name without `-fast`, asked the same
question. If it does not think either, an empty reasoning block on the fast alias
proves nothing, and this fails rather than passes.

Measured 2026-10-04, `unsloth-gemma4-26b`, both gateways: 14 completion tokens and
no reasoning on `-fast`; 264–437 with a reasoning block on the base.

    uv run 06_thinking_off.py --model unsloth-gemma4-26b-fast
"""

import sys

from common import Gateway, check, client_for, reasoning_of, run

FAST_SUFFIX = "-fast"

QUESTION = "A train leaves at 09:47 and arrives at 13:12. How long is the trip? Answer in one short line."

# Room for the base alias to think and still answer; the fast one uses about 14.
CEILING = 2048

# The ceiling is set here, so it may not also come from `body_extras`.
OWN_FIELDS = ("max_tokens", "max_completion_tokens")


def chat(gateway: Gateway, model: str) -> tuple[int, int]:
    """Reasoning characters and completion tokens of one chat completion."""
    extras = {key: value for key, value in gateway.body_extras.items() if key not in OWN_FIELDS}
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": QUESTION}],
        max_tokens=CEILING,
        **extras,
    )
    return len(reasoning_of(response.choices[0].message)), response.usage.completion_tokens


def responses(gateway: Gateway, model: str) -> tuple[int, int]:
    """Reasoning items and output tokens of one /v1/responses call, as Codex sends it."""
    level = gateway.body_extras.get("reasoning_effort")
    response = client_for(gateway).responses.create(
        model=model,
        input=QUESTION,
        max_output_tokens=CEILING,
        **({"reasoning": {"effort": level}} if level else {}),
    )
    reasoning = sum(1 for item in response.output if item.type == "reasoning")
    return reasoning, response.usage.output_tokens


def scenario(gateway: Gateway, model: str) -> str:
    if not model.endswith(FAST_SUFFIX):
        return f"not applicable: {model} is not a `{FAST_SUFFIX}` alias"
    base = model.removesuffix(FAST_SUFFIX)

    results = []
    for route, call in (("chat", chat), ("responses", responses)):
        fast_reasoning, fast_tokens = call(gateway, model)
        base_reasoning, base_tokens = call(gateway, base)
        print(f"--- {route}: {model} reasoning={fast_reasoning} tokens={fast_tokens}; "
              f"{base} reasoning={base_reasoning} tokens={base_tokens} ---")
        check(
            base_reasoning > 0,
            f"{route}: {base} did not think either, so an empty block on {model} proves nothing. "
            "Run this against an engine that thinks by default, such as Unsloth.",
        )
        check(
            fast_reasoning == 0,
            f"{route}: {model} still thought ({fast_reasoning}, {fast_tokens} tokens). The route must "
            "store BOTH `enable_thinking: false` and `chat_template_kwargs` — chat obeys one, "
            "/v1/responses the other. See ../../config/<engine>.yaml.",
        )
        results.append(f"{route} {fast_tokens} vs {base_tokens} tokens")
    return f"thinking is off on {model}, on on {base}: " + ", ".join(results)


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 6 — a -fast alias answers with thinking off"))
