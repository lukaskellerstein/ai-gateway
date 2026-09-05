"""Test 4 — THIS GATEWAY'S CALLING CONTRACT, checked against what it really does.

Scripts 01-03 prove a kind of call works. This one proves the four claims
`common.Gateway` makes about HOW to call it, because every one of them is a thing
a caller has to get right and none of them is visible in a response body.

    property               LiteLLM 24000, and what is asserted here
    ---------------------  --------------------------------------------------
    checks_api_key   True  a bogus Bearer token gets 401, so the master key is
                           actually enforced
    lists_models     True  GET /models returns the alias list, so a caller can
                           discover the vocabulary over the OpenAI surface
    echoes_alias     True  response.model is the ALIAS that was sent, not the
                           engine's own model id
    exposes_route_limits
                     True  /model/info answers, so each route's stored
                           max_tokens and max_input_tokens can be read

THE LAST ROW IS THE ONE THAT MATTERS MOST, and it is why `body_extras` is empty
on this gateway. LiteLLM stores a `max_tokens` per route and every local route in
../../config/ carries one, so a caller who sends none still gets a bounded reply.
Measured 2026-09-03 with `lms-4b` and one "count to 3000" prompt carrying NO
`max_tokens`: finish_reason "length" at 4095 completion tokens — the
`max_tokens: 4096` on the route, doing its job.

(The Envoy gateway in ../../../envoy stores none, so its own copy of this test
declares `False` on that line and checks it the same way. That is the point: each
project declares and checks its own contract.)

AN EXPLICIT CEILING IS NOT THE DIFFERENCE. Sent by hand it is honoured normally —
including the trap where a reasoning model spends the whole allowance thinking
and returns EMPTY content with finish_reason "length" and no error at all.
`check_low_ceiling_truncates` below asserts that.

THIS SCRIPT NEVER BRANCHES ON A GATEWAY NAME. It reads the contract DECLARED in
common.py and checks reality against it, so a failure always reads "the table
says X and the gateway did Y", which is the sentence you want.

    uv run 04_gateway_contract.py
    uv run 04_gateway_contract.py --model lms-26b
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from common import Gateway, check, client_for, run

# Small on purpose. This script asserts SHAPES — status codes, which string comes
# back in `model`, whether a ceiling truncates — so it never needs a long reply,
# and every call here finishes in about a second.
TINY_CEILING = 16
PROMPT = "Explain in detail why the sky is blue."


def _root(base_url: str) -> str:
    """The gateway's own root, above the OpenAI-compatible surface.

    Dropping the trailing `/v1` gives `http://localhost:24000`, which is where
    `/model/info` lives — derived rather than written out a second time.
    """
    return base_url.rstrip("/").removesuffix("/v1")


def _status(url: str, *, key: str | None = None, body: dict | None = None) -> int:
    """The HTTP status, with an error status returned rather than raised.

    A 401 and a 404 are the ANSWERS this script is looking for, so urllib's habit
    of raising on them would turn every expected result into a traceback.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def ceiling(gateway: Gateway) -> dict:
    """The explicit token ceiling, under whatever name this gateway's upstream wants.

    IT IS READ FROM THE DECLARED CONTRACT, never branched on the gateway's name.
    `body_extras` already carries the right key — `max_tokens` almost everywhere,
    `max_completion_tokens` for `openai-*`, whose newer models reject the old name
    with `400 unsupported_parameter` (measured 2026-09-05, `openai-mini` on 26000).
    LiteLLM renames it upstream and declares no extras at all, so the fallback here
    is what that project uses.
    """
    return {next(iter(gateway.body_extras), "max_tokens"): TINY_CEILING}


def check_api_key(gateway: Gateway, model: str) -> str:
    """Does a deliberately wrong key get rejected?"""
    status = _status(
        f"{gateway.base_url}/chat/completions",
        key="sk-definitely-not-a-real-key",
        body={"model": model, **ceiling(gateway), "messages": [{"role": "user", "content": "hi"}]},
    )
    rejected = status == 401
    check(
        rejected == gateway.checks_api_key,
        f"common.py declares checks_api_key={gateway.checks_api_key}, but a bogus key got "
        f"HTTP {status}. Anything but 401 means the master key is NOT being enforced and "
        "every caller is unauthenticated.",
    )
    return f"bad key -> {status}"


def check_model_listing(gateway: Gateway, _model: str) -> str:
    """Can a caller discover the vocabulary over the OpenAI surface?"""
    status = _status(f"{gateway.base_url}/models", key=gateway.api_key)
    lists = status == 200
    check(
        lists == gateway.lists_models,
        f"common.py declares lists_models={gateway.lists_models}, but GET /models returned "
        f"HTTP {status}. This is how a caller discovers the vocabulary without reading "
        "../../config/<engine>.yaml.",
    )
    return f"GET /models -> {status}"


def check_route_limits(gateway: Gateway, _model: str) -> str:
    """Does the gateway store a per-route ceiling a caller could rely on?

    This is the structural form of the `max_tokens` difference, and it is cheap:
    one GET, against a generation that would take minutes to bound empirically.
    """
    status = _status(f"{_root(gateway.base_url)}/model/info", key=gateway.api_key)
    exposes = status == 200
    check(
        exposes == gateway.exposes_route_limits,
        f"common.py declares exposes_route_limits={gateway.exposes_route_limits}, but "
        f"/model/info returned HTTP {status}. This is what decides whether a caller who "
        "sends no max_tokens is protected — see body_extras in common.py.",
    )
    return f"/model/info -> {status}"


def check_model_echo(gateway: Gateway, model: str) -> str:
    """Is `response.model` the alias the caller sent, or the engine's own id?

    It matters for anything that keys a metric, a log line or a cost report off
    `response.model`: one request produces two different strings.
    """
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Say hi."}],
        **ceiling(gateway),
    )
    echoed = response.model
    check(
        (echoed == model) == gateway.echoes_alias,
        f"common.py declares echoes_alias={gateway.echoes_alias}, but the caller sent "
        f"model={model!r} and the reply carried model={echoed!r}.",
    )
    return f"sent {model!r}, got {echoed!r}"


def check_low_ceiling_truncates(gateway: Gateway, model: str) -> str:
    """An explicit ceiling is honoured, whatever the route's stored default is.

    The gateway stops at `max_tokens` and returns finish_reason "length". On a
    model that reasons the content is EMPTY as well, with no error raised — which
    is why the stored route default in ../../config/ is set generously.
    """
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        **ceiling(gateway),
    )
    choice = response.choices[0]
    check(
        choice.finish_reason == "length",
        f"a {TINY_CEILING}-token ceiling should truncate, but finish_reason was "
        f"{choice.finish_reason!r}. An explicit max_tokens must be honoured exactly; "
        "only the DEFAULT is a per-gateway matter.",
    )
    return f"max_tokens={TINY_CEILING} -> finish_reason={choice.finish_reason!r}"


CHECKS = (
    ("api key", check_api_key),
    ("model listing", check_model_listing),
    ("route limits", check_route_limits),
    ("model echo", check_model_echo),
    ("explicit ceiling", check_low_ceiling_truncates),
)


def scenario(gateway: Gateway, model: str) -> str:
    summaries = []
    for label, function in CHECKS:
        result = function(gateway, model)
        print(f"--- {label:18s} {result}")
        summaries.append(f"{label}: {result}")
    return " | ".join(summaries)


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 4 — the per-gateway calling contract"))
