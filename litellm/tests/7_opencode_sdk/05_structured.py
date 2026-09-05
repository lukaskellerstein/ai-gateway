"""05 structured output — a JSON schema the reply must satisfy.

OpenCode passes `format` through to the model's structured-output layer, so this
is the scenario that proves the gateway forwards that part of the request rather
than quietly dropping it.

THE RESULT IS NOT IN THE TEXT PARTS. OpenCode validates the reply against the
schema and puts the parsed object in `info.structured`; the text parts may hold
a plain sentence, or nothing. Reading the text and calling `json.loads` on it
fails even when everything worked — which is exactly what happened the first
time this was written. A schema failure shows up as `info.error` with the name
`StructuredOutputError`.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import ask, new_session, opencode_server, report, run, text_of

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
    "required": ["city", "country"],
    "additionalProperties": False,
}


async def scenario(model: str) -> str:
    async with opencode_server(model) as client:
        session = await new_session(client, "05 structured")
        answer = await ask(
            client,
            session,
            # THE PROMPT ASKS FOR THE SHAPE AS WELL AS THE ANSWER. OpenCode
            # validates the reply against the schema and fails the turn when it
            # does not match — `StructuredOutputError ... retries: 0`, seen on a
            # bare question. The gateway is not at fault: the same schema through
            # `response_format` on the OpenAI route returned clean JSON 3 times
            # out of 3 on both gateways (measured 2026-09-04).
            "What is the capital of France? Reply with a JSON object containing "
            "exactly the keys \"city\" and \"country\", and nothing else.",
            # `retryCount` IS NOT OPTIONAL WITH A SMALL MODEL. OpenCode validates
            # the reply against the schema and, without retries, one malformed
            # attempt fails the run — `StructuredOutputError ... retries: 0`,
            # measured on LiteLLM 2026-09-04. Two retries made it deterministic.
            format={"type": "json_schema", "schema": SCHEMA, "retryCount": 2},
        )
    report("structured", answer)

    info = answer.get("info") or {}
    error = info.get("error") or {}
    if error.get("name") == "StructuredOutputError":
        raise AssertionError(f"the model failed schema validation: {error.get('data')}")

    parsed = info.get("structured")
    print(f"  structured  {parsed!r}")
    if not isinstance(parsed, dict):
        raise AssertionError(
            f"info.structured is {parsed!r} — the schema was not applied. The text was "
            f"{text_of(answer).strip()[:120]!r}"
        )

    for key in ("city", "country"):
        if key not in parsed:
            raise AssertionError(f"{key!r} is missing from the structured reply: {parsed!r}")
    if "paris" not in str(parsed["city"]).lower():
        raise AssertionError(f"expected Paris in city, got {parsed!r}")
    return f"structured: {parsed}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
