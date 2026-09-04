"""Test 4 — THIS GATEWAY'S CALLING CONTRACT, checked against what it really does.

Scripts 01-03 prove a kind of call works. This one proves the four claims
`common.Gateway` makes about HOW to call it. FOUR OF THEM ARE `False`, and this
script exists to prove they are still false — an absence nobody checks is an
absence somebody eventually assumes away.

    property                MLflow 25000, and what is asserted here
    ----------------------  -------------------------------------------------
    checks_api_key   False  a bogus Bearer token gets 200. MLflow has no key
                            concept and never reads the header
    lists_models     False  GET /models returns 404. The vocabulary lives in
                            the MLflow UI and in ../config/<engine>.py
    echoes_alias     False  response.model is the ENGINE'S own model id, not
                            the alias that was sent
    exposes_route_limits
                     False  there is no /model/info route, because nothing
                            stores a per-route ceiling

THE LAST ROW IS THE ONE THAT COSTS PEOPLE AN AFTERNOON, and it is why
`body_extras` carries `max_tokens` here. MLflow's endpoints are database rows
with no place to put a default. Measured 2026-09-03 with `lms-4b` and one "count
to 3000" prompt carrying NO `max_tokens`: finish_reason "stop" at 13961
completion tokens — nothing bounded it.

(The LiteLLM gateway in ../../litellm stops at 4095 on the same prompt, off its
stored route default. Its own copy of this test asserts the opposite of this
table, which is the point: each project declares and checks its own contract.)

AN EXPLICIT CEILING IS HONOURED NORMALLY — including the trap where a reasoning
model spends the whole allowance thinking and returns EMPTY content with
finish_reason "length" and no error at all. `check_low_ceiling_truncates` below
asserts that. What is missing is only the DEFAULT.

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

    Dropping the trailing `/v1` gives `http://localhost:25000/gateway/mlflow`,
    which is where `/model/info` WOULD live — derived rather than written out a
    second time. It 404s here, and that is the assertion.
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


def check_api_key(gateway: Gateway, model: str) -> str:
    """Does a deliberately wrong key get rejected?"""
    status = _status(
        f"{gateway.base_url}/chat/completions",
        key="sk-definitely-not-a-real-key",
        body={"model": model, "max_tokens": TINY_CEILING, "messages": [{"role": "user", "content": "hi"}]},
    )
    rejected = status == 401
    check(
        rejected == gateway.checks_api_key,
        f"common.py declares checks_api_key={gateway.checks_api_key}, but a bogus key got "
        f"HTTP {status}. 200 is correct here — MLflow has no key concept and never reads the "
        "header. A 401 would mean something in front of it started checking.",
    )
    return f"bad key -> {status}"


def check_model_listing(gateway: Gateway, _model: str) -> str:
    """Can a caller discover the vocabulary over the OpenAI surface?"""
    status = _status(f"{gateway.base_url}/models", key=gateway.api_key)
    lists = status == 200
    check(
        lists == gateway.lists_models,
        f"common.py declares lists_models={gateway.lists_models}, but GET /models returned "
        f"HTTP {status}. MLflow has no such route: its endpoint list lives in its own UI and "
        "in ../config/<engine>.py, not on the OpenAI surface.",
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
        max_tokens=TINY_CEILING,
    )
    echoed = response.model
    check(
        (echoed == model) == gateway.echoes_alias,
        f"common.py declares echoes_alias={gateway.echoes_alias}, but the caller sent "
        f"model={model!r} and the reply carried model={echoed!r}.",
    )
    return f"sent {model!r}, got {echoed!r}"


def check_low_ceiling_truncates(gateway: Gateway, model: str) -> str:
    """An explicit ceiling is honoured. Only the DEFAULT is missing here.

    The gateway stops at `max_tokens` and returns finish_reason "length". On a
    model that reasons the content is EMPTY as well, with no error raised — which
    is exactly the failure `body_extras` exists to keep a caller out of.
    """
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        max_tokens=TINY_CEILING,
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
