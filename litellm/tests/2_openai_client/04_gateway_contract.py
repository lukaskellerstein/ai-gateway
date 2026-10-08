"""Test 4 — THIS GATEWAY'S CALLING CONTRACT, checked against what it really does.

Scripts 01-03 prove a kind of call works. This one proves the five claims `CONTRACT`
in settings.py makes about HOW to call the gateway, because every one of them is a
thing a caller has to get right and none of them is visible in a response body.

    property               what is asserted
    ---------------------  --------------------------------------------------
    checks_api_key         a bogus Bearer token gets 401 exactly when True
    lists_models           GET /models answers 200 exactly when True
    echoes_alias           response.model is the alias sent exactly when True
    exposes_route_limits   /model/info answers 200 exactly when True
    loopback_only          this machine's network address refuses the port
                           exactly when True

A `False` is checked as hard as a `True`: an absence nobody checks is an absence
somebody eventually assumes away. The two gateways in this repo agree on TWO of the
five — `lists_models` and `loopback_only` — and each project's settings.py says
which, with the measurement behind it.

THE LAST ROW IS THE ONE THAT COSTS PEOPLE AN AFTERNOON. A gateway that stores a
`max_tokens` per route bounds a caller who sends none; one that stores nothing lets
the reply run. One "count to 3000" prompt with no ceiling stopped at 4095 completion
tokens on LiteLLM's stored 4096 and ran to 13946 on Envoy (2026-09-04, `lms-gemma4-e4b`).
Where nothing is stored, `body_extras` in settings.py carries the ceiling.

AN EXPLICIT CEILING IS HONOURED NORMALLY — including the trap where a reasoning
model spends the whole allowance thinking and returns EMPTY content with
finish_reason "length" and no error at all. `check_low_ceiling_truncates` below
asserts that. Only the DEFAULT is a per-gateway matter.

THIS SCRIPT NEVER BRANCHES ON A GATEWAY NAME. It reads the contract DECLARED in
settings.py and checks reality against it, so a failure always reads "the table
says X and the gateway did Y", which is the sentence you want.

    uv run 04_gateway_contract.py
    uv run 04_gateway_contract.py --model lms-gemma4-26b
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import Gateway, check, client_for, run

# Small on purpose. This script asserts SHAPES — status codes, which string comes
# back in `model`, whether a ceiling truncates — so it never needs a long reply,
# and every call here finishes in about a second.
TINY_CEILING = 16
PROMPT = "Explain in detail why the sky is blue."


def _root(base_url: str) -> str:
    """The gateway's own root, above the OpenAI-compatible surface.

    Dropping the trailing `/v1` gives the root, which is where `/model/info` lives
    on a gateway that has one — derived rather than written out a second time.
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
    with `400 unsupported_parameter` (measured 2026-09-05, `openai-gpt54-mini` on 26000).
    A gateway that stores a ceiling per route sends none in `body_extras`, so the
    fallback is the name it renames upstream for you.
    """
    # BY NAME, not the first key: `body_extras` also carries `reasoning_effort`, and
    # that must never become the ceiling's name.
    names = ("max_completion_tokens", "max_tokens")
    return {next((name for name in names if name in gateway.body_extras), "max_tokens"): TINY_CEILING}


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
        f"settings.py declares checks_api_key={gateway.checks_api_key}, but a bogus key got "
        f"HTTP {status}. 401 means the gateway enforces a key; anything else means it reads "
        "none and every caller is unauthenticated.",
    )
    return f"bad key -> {status}"


def check_model_listing(gateway: Gateway, _model: str) -> str:
    """Can a caller discover the vocabulary over the OpenAI surface?"""
    status = _status(f"{gateway.base_url}/models", key=gateway.api_key)
    lists = status == 200
    check(
        lists == gateway.lists_models,
        f"settings.py declares lists_models={gateway.lists_models}, but GET /models returned "
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
        f"settings.py declares exposes_route_limits={gateway.exposes_route_limits}, but "
        f"/model/info returned HTTP {status}. This is what decides whether a caller who "
        "sends no max_tokens is protected — see body_extras in settings.py.",
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
        f"settings.py declares echoes_alias={gateway.echoes_alias}, but the caller sent "
        f"model={model!r} and the reply carried model={echoed!r}.",
    )
    return f"sent {model!r}, got {echoed!r}"


def _network_address() -> str | None:
    """This machine's address on its network, or None when it has none.

    A UDP `connect` sends nothing. It only asks the kernel which interface would
    carry the packet, and that interface's address is the one another machine
    calls. 192.0.2.1 is TEST-NET-1, reserved for documentation and never routed.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))
        except OSError:
            return None
        address = str(probe.getsockname()[0])
    return None if address.startswith("127.") else address


def check_loopback_only(gateway: Gateway, _model: str) -> str:
    """Can another machine reach the gateway, or only this one?

    The port is tried on this machine's NETWORK address, which is what another
    machine would call. Compose decides it: `"24000:4000"` publishes on every
    interface, `"127.0.0.1:24000:4000"` on this machine only. A machine with no
    network address has nothing to reach from outside, and the row says so.
    """
    port = urllib.parse.urlsplit(gateway.base_url).port
    address = _network_address()
    if address is None or port is None:
        return "not tried: this machine has no network address"
    with socket.socket() as probe:
        probe.settimeout(3)
        reachable = probe.connect_ex((address, port)) == 0
    check(
        (not reachable) == gateway.loopback_only,
        f"settings.py declares loopback_only={gateway.loopback_only}, but {address}:{port} "
        f"{'ACCEPTED' if reachable else 'refused'} a connection. Another machine on this "
        "network calls that address — see `ports:` in ../../compose.yml.",
    )
    return f"{address}:{port} -> {'open' if reachable else 'refused'}"


def check_low_ceiling_truncates(gateway: Gateway, model: str) -> str:
    """An explicit ceiling is honoured, whatever the gateway stores or does not.

    The gateway stops at `max_tokens` and returns finish_reason "length". On a
    model that reasons the content is EMPTY as well, with no error raised — which
    is why a route's stored default, and the ceiling in `body_extras`, are generous.
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
    ("loopback only", check_loopback_only),
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
