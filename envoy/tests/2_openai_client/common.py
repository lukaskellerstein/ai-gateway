"""Shared plumbing for this folder's test scripts.

Every script here answers one question: does this ONE kind of call work through
the gateway settings.py names? So each script owns a single `scenario` function and
nothing else — the argument parsing, the client, the timing and the pass/fail
printing all live here, once.

THIS SUITE DRIVES ONE GATEWAY. Before the split there was one `tests/` at the repo
root that ran every script against both ports and proved the two gateways shared a
vocabulary. Each gateway is a standalone compose project now, so that comparison has
no single owner and is no longer made: nothing here checks that an alias answering on
this gateway also answers on the other. Call both ports by hand when it matters.

WHAT IS WORTH DECLARING IS THE GATEWAY'S OWN CALLING CONTRACT, and it is data:
`CONTRACT` in settings.py, carried on `Gateway` below. `04_gateway_contract.py` is
the test that proves every line of it is still true, so a failure reads "the table
says X and the gateway did Y" rather than "something is wrong".

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS. Everything specific — the URL, the
key, the alias, the ceiling, the contract — is in settings.py.
"""

from __future__ import annotations

import argparse
import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from settings import API_KEY, BASE_URL, CONTRACT, MAX_RETRIES, MODEL, NAME, REQUEST_TIMEOUT_SECONDS, body_extras

IMAGE_PATH = Path(__file__).resolve().parent / "test_image.png"


class CheckFailed(AssertionError):
    """A call succeeded but the answer was not what the scenario required."""


@dataclass(frozen=True)
class Gateway:
    """THE CONTRACT FOR CALLING THIS GATEWAY, declared as data.

    A scenario spreads `**gateway.body_extras` into its request and reads nothing
    else, so it cannot grow gateway-specific behaviour by accident. The values, and
    the measurement behind each, are in settings.py; what each one MEANS is here.

    body_extras
        What every request body must carry for THIS alias: the thinking level, plus a
        ceiling on a gateway that stores none. `settings.body_extras(model)`.
    checks_api_key
        True: a wrong Bearer token gets 401. False: the gateway reads no caller key.
    lists_models
        `GET {base_url}/models` returns the alias list.
    echoes_alias
        True: `response.model` is the alias the caller sent. False: it is the
        engine's own id, so anything keying a metric or a log line off
        `response.model` sees a different string from the one it asked for.
    exposes_route_limits
        True: `/model/info` reports each route's stored `max_tokens`, so a caller
        who sends none still gets a bounded reply. False: nothing stores one, and
        `body_extras` has to carry it.
    loopback_only
        True: the gateway answers on 127.0.0.1 only, and this machine's network
        address refuses the port. False: any machine on the network can call it.
    default_effort
        The thinking level a Qwen 3.8 route runs at when the caller sends NONE, or
        None when the gateway stores none and the template's own `xhigh` applies.
        05_reasoning_effort.py checks it, not 04 — the default alias is a Gemma,
        whose template ignores the level.
    """

    name: str
    base_url: str
    api_key: str
    body_extras: dict
    checks_api_key: bool
    lists_models: bool
    echoes_alias: bool
    exposes_route_limits: bool
    loopback_only: bool
    default_effort: str | None


def gateway_for(model: str) -> Gateway:
    """The contract for calling `model` on the gateway settings.py names.

    Built per alias rather than once at import: on a gateway that passes the body
    through untouched, the ceiling's NAME depends on the alias — see
    `settings.body_extras`.
    """
    return Gateway(name=NAME, base_url=BASE_URL, api_key=API_KEY, body_extras=body_extras(model), **CONTRACT)


def client_for(gateway: Gateway) -> OpenAI:
    return OpenAI(
        base_url=gateway.base_url,
        api_key=gateway.api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


def encode_image(path: Path = IMAGE_PATH) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def reasoning_of(message) -> str:
    """`reasoning_content` is not an OpenAI field, so the SDK keeps it as an extra."""
    extra = getattr(message, "model_extra", None) or {}
    return str(getattr(message, "reasoning_content", None) or extra.get("reasoning_content") or "")


def answer_of(response) -> str:
    """The reply text — and a named error for the empty-because-still-thinking case.

    "Empty content" has two very different causes and one of them is not a bug in
    the gateway at all. Saying which one it was turns a confusing failure into an
    instruction.
    """
    choice = response.choices[0]
    text = (choice.message.content or "").strip()
    if text:
        return text

    thinking = reasoning_of(choice.message)
    if thinking:
        # The allowance is the ceiling in `body_extras` where the gateway stores
        # none, or the route's stored `max_tokens` where it does. This function
        # cannot know which, so it names both places.
        raise CheckFailed(
            f"empty content, finish_reason={choice.finish_reason!r}: the model spent its whole "
            f"token allowance on a reasoning block ({len(thinking)} chars) and never started the "
            "reply. Raise the ceiling in settings.body_extras, or the route's stored `max_tokens`."
        )
    raise CheckFailed(f"the model returned empty content, finish_reason={choice.finish_reason!r}")


def show(title: str, response: object) -> None:
    """Print the whole response, then let the scenario print the part it checks."""
    print(f"--- {title}: ---")
    print(response.to_json() if hasattr(response, "to_json") else response)


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=MODEL, help=f"alias to call (default: {MODEL})")
    return parser.parse_args()


def run(scenario: Callable[[Gateway, str], str], description: str) -> int:
    """Drive one scenario against this gateway. Returns a process exit code."""
    args = parse_args(description)
    gateway = gateway_for(args.model)

    print(f"\n{'=' * 70}\n{description}\n{gateway.name} -> {gateway.base_url}  model={args.model}\n{'=' * 70}")
    started = time.perf_counter()
    try:
        summary, passed = scenario(gateway, args.model), True
    except Exception as error:  # noqa: BLE001 — a failing test reports, it does not crash
        # The class name matters: CheckFailed is a wrong answer, anything else is
        # a transport or gateway failure, and they are fixed in different places.
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {gateway.name:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1
