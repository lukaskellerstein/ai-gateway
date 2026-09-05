"""Test 1 — a plain chat completion through the OpenAI client.

The smallest thing that can work: no tools, no images. It proves the alias is
registered, the route reaches whichever engine is selected, and a multi-turn
conversation survives the trip.

    uv run 01_simple_call.py
    uv run 01_simple_call.py --model lms-26b
"""

import sys

from common import Gateway, answer_of, check, client_for, run, show

# `system` and not `developer`: the newer role is an OpenAI-model convention, and
# a local model behind the gateway does not know it.
CONVERSATION = [
    {"role": "system", "content": "You are a helpful assistant. Answer in one short sentence."},
    {"role": "user", "content": "Hey"},
    {"role": "assistant", "content": "Hello! How can I help you today?"},
    {"role": "user", "content": "What is the capital of France?"},
]


def scenario(gateway: Gateway, model: str) -> str:
    # THE BODY IS IDENTICAL ON BOTH PORTS except for `body_extras`, which is the
    # gateway's own calling contract from common.py — empty for LiteLLM, whose
    # route stores a `max_tokens`, and `max_tokens` for Envoy, which stores none.
    # This scenario does not know or care which it got.
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=CONVERSATION,
        **gateway.body_extras,
    )

    show("Full response", response)
    text = answer_of(response)
    print(f"--- Response text: ---\n{text}")

    check("paris" in text.lower(), f"expected Paris in the answer, got: {text!r}")
    return f"{response.usage.total_tokens} tokens, said {text!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 1 — plain chat completion"))
