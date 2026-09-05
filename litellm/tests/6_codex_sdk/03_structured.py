"""03 structured output — a JSON schema the reply must satisfy.

`output_schema` goes straight to the model's structured-output layer, so this is
the scenario that proves the gateway forwards that part of the Responses API
rather than quietly dropping it. A gateway that drops it still returns a
sentence, which is why the assertion parses the reply instead of reading it.

OPENAI-STRICT SCHEMAS NEED `additionalProperties: false` AND EVERY PROPERTY IN
`required`. A schema straight out of `model_json_schema()` has neither and is
rejected.

THE LOCAL ENGINES DO NOT ENFORCE THE SCHEMA, so the prompt asks for the shape
too. Called directly with `text.format`, LMStudio and Unsloth both returned
prose (measured 2026-09-04). `output_schema` is still sent — this scenario
proves the gateway FORWARDS it — but the assertion cannot lean on enforcement
that the engine does not provide.

AND BECAUSE NOTHING ENFORCES IT, HOW THE MODEL DECORATES THE ANSWER VARIES RUN
TO RUN. The same alias returned a bare object, a ```json fence, and a sentence
before the object on different runs of the same prompt (measured on LMStudio,
2026-09-04 and 2026-09-05). So the reply is SEARCHED for its first JSON object
rather than parsed whole. A fence-only strip was tried first and was
intermittent — it passed six runs out of six and still failed in the matrix.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import json
import sys

from common import Codex, codex_config, report, run, start_thread

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
    "required": ["city", "country"],
    "additionalProperties": False,
}


def first_json_object(text: str) -> dict | None:
    """The first JSON object in `text`, or None if it carries none.

    IT MUST NOT MASK THE FAILURE THIS SCENARIO EXISTS TO FIND. A gateway that
    DROPPED `output_schema` returns a plain sentence — "The capital of France is
    Paris." — which holds no object at all, so this still returns None and the
    caller still fails. What it forgives is only the decoration the model adds
    around a correct answer.
    """
    decoder = json.JSONDecoder()
    for start, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def scenario(model: str) -> str:
    with Codex(config=codex_config(model)) as codex:
        thread = start_thread(codex, model)
        answer = thread.run(
            # THE PROMPT ASKS FOR THE SHAPE AS WELL AS THE ANSWER, and it has to.
            # Measured 2026-09-04: neither LMStudio nor Unsloth ENFORCES a schema
            # on `/v1/responses` — called directly with `text.format`, both returned
            # prose. So `output_schema` alone leaves it to the model, and a bare
            # question passed on unsloth and failed on lms with
            # "The capital of France is Paris."
            "What is the capital of France? Reply with a JSON object containing "
            'exactly the keys "city" and "country", and nothing else.',
            output_schema=SCHEMA,
        )
    report("structured", answer)

    raw = str(answer.final_response or "").strip()
    parsed = first_json_object(raw)
    if parsed is None:
        raise AssertionError(
            f"the reply carries no JSON object, so the schema was not applied: {raw[:160]!r}"
        )

    for key in ("city", "country"):
        if key not in parsed:
            raise AssertionError(f"{key!r} is missing from the structured reply: {parsed!r}")
    if "paris" not in str(parsed["city"]).lower():
        raise AssertionError(f"expected Paris in city, got {parsed!r}")
    return f"structured: {parsed}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
