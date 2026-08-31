"""Test 1 — a plain chat completion through the OpenAI client.

The smallest thing that can work: no tools, no images. It proves the alias is
registered, the route reaches LMStudio, and a multi-turn conversation survives
the trip.

    uv run 01_simple_call.py
    uv run 01_simple_call.py --gateway litellm --model lms-qwen
"""

import sys

from common import MAX_TOKENS, Gateway, answer_of, check, client_for, run, show

# `system` and not `developer`: the newer role is an OpenAI-model convention, and
# a local model behind the gateway does not know it.
CONVERSATION = [
    {"role": "system", "content": "You are a helpful assistant. Answer in one short sentence."},
    {"role": "user", "content": "Hey"},
    {"role": "assistant", "content": "Hello! How can I help you today?"},
    {"role": "user", "content": "What is the capital of France?"},
]


def scenario(gateway: Gateway, model: str) -> str:
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=CONVERSATION,
        max_tokens=MAX_TOKENS,
    )

    show("Full response", response)
    text = answer_of(response)
    print(f"--- Response text: ---\n{text}")

    check("paris" in text.lower(), f"expected Paris in the answer, got: {text!r}")
    return f"{response.usage.total_tokens} tokens, said {text!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 1 — plain chat completion"))
