"""Test 4 — the CALLING CONTRACT, and how the two gateways differ.

Scripts 01-03 prove the vocabulary is shared: same alias, same messages, two
ports. THIS ONE PROVES THE REST OF THE REQUEST IS NOT SHARED, and it is the test
to read first if a call works on 24000 and misbehaves on 25000.

Four differences, all measured rather than assumed:

    property               LiteLLM 24000            MLflow 25000
    ---------------------  -----------------------  --------------------------
    checks_api_key         401 on a bad key         200 — no key concept at all
    lists_models           GET /models -> the list  GET /models -> 404
    echoes_alias           response.model = alias   = the ENGINE'S model id
    exposes_route_limits   /model/info has          no such route — nothing
                           max_tokens per route     stores a ceiling

THE LAST ROW IS THE ONE THAT COSTS PEOPLE AN AFTERNOON. LiteLLM can store a
`max_tokens` on a route and every local route here does, so a caller who sends
none still gets a bounded reply. MLflow's endpoints are database rows with no
place to put one. Measured 2026-09-03 with `lms-4b` and one "count to 3000"
prompt carrying NO `max_tokens`:

    LiteLLM   finish_reason "length" at  4095 completion tokens
    MLflow    finish_reason "stop"   at 13961 completion tokens

Same prompt, same alias, same weights: 3.4x the output and 3.4x the wait, purely
because one gateway had a ceiling to fall back on and the other did not.

So `common.Gateway.body_extras` sends `max_tokens` to MLflow and nothing to
LiteLLM, and scripts 01-03 spread it into every request.

THE PARAMETER ITSELF IS NOT THE DIFFERENCE. Sent explicitly, both gateways honour
it identically — including the trap where a reasoning model spends the whole
allowance thinking and returns EMPTY content with finish_reason "length" and no
error. `check_low_ceiling_truncates` below asserts that on both.

THIS SCRIPT IS THE ONE PLACE ALLOWED TO CARE WHICH GATEWAY IT IS TALKING TO, and
even here it does not branch on the name: it reads the contract DECLARED in
common.py and checks reality against it. So the failure message is always "the
table says X and the gateway did Y", which is the sentence you want.

    uv run 04_gateway_contract.py
    uv run 04_gateway_contract.py --gateway mlflow
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

    Dropping the trailing `/v1` gives `http://localhost:24000` for LiteLLM and
    `http://localhost:25000/gateway/mlflow` for MLflow — so `/model/info` below
    is ONE probe sent to both, rather than two hand-written URLs.
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
        f"HTTP {status}. On MLflow 200 is correct — it has no key concept and never reads "
        "the header. On LiteLLM anything but 401 means the master key is not enforced.",
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
        "in mlflow/<engine>.py, not on the OpenAI surface.",
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
    """The half that is the SAME: an explicit ceiling behaves identically.

    Both gateways stop at `max_tokens` and return finish_reason "length". On a
    model that reasons the content is EMPTY as well, with no error raised — which
    is exactly the failure `body_extras` exists to keep you out of on 25000.
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
        f"{choice.finish_reason!r}. Both gateways must honour an explicit max_tokens "
        "identically — only the DEFAULT differs.",
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
