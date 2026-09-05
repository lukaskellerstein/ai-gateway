"""Test 3 — a multimodal call: one image plus a question.

The image travels as a base64 `data:` URL inside the message, so this is also the
test with a large request body. `test_image.png` is deliberately tiny and
deliberately unambiguous — 256x256, one red circle on a white background — so the
check can be exact without depending on how wordy the model is.

A model that is not vision-capable does NOT necessarily error here. It can ignore
the image part and answer from the text alone, which is why the check asks for
both the colour and the shape.

    uv run 03_multimodal.py
    uv run 03_multimodal.py --model lms-26b
"""

import sys

from common import Gateway, answer_of, check, client_for, encode_image, run, show

QUESTION = "What shape and what colour is in this image? Answer in one short sentence."
ROUND_WORDS = ("circle", "round", "dot", "sphere", "disc")


def scenario(gateway: Gateway, model: str) -> str:
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": QUESTION},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encode_image()}"},
                    },
                ],
            },
        ],
        # The per-gateway calling contract from common.py. It matters most here:
        # the request body is large, and a vision model that describes an image
        # often reasons first — so a missing ceiling on Envoy is the difference
        # between an answer and empty content.
        **gateway.body_extras,
    )

    show("Full response", response)
    text = answer_of(response)
    print(f"--- Response text: ---\n{text}")

    lowered = text.lower()
    check("red" in lowered, f"the model did not see the red colour: {text!r}")
    check(
        any(word in lowered for word in ROUND_WORDS),
        f"the model did not see the round shape: {text!r}",
    )
    return f"described the image as {text!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 3 — multimodal, image plus text"))
