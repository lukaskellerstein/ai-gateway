"""Shared plumbing for this project's test scripts. LITELLM ONLY.

Every script here answers one question: does this ONE kind of call work through
the LiteLLM gateway on 24000? So each script owns a single `scenario` function and
nothing else — the argument parsing, the base URL, the timing and the pass/fail
printing all live here, once.

THIS SUITE DRIVES ONE GATEWAY, AND THAT IS NEW. Before the split there was one
`tests/` at the repo root that ran every script against both ports and proved the
two gateways shared a vocabulary: same alias, same messages, two base URLs. Each
gateway is a standalone compose project now, with its own `.env` and its own
engine word, so that comparison has no single owner and is no longer made. Nothing
here — and nothing anywhere in the repo — checks that `lms-4b` also answers on
26000. If you want that, call both ports by hand.

WHAT IS STILL WORTH DECLARING IS THIS GATEWAY'S OWN CALLING CONTRACT, and it is on
`Gateway` below as data. `04_gateway_contract.py` is the test that proves every
line of it is still true, so a failure reads "the table says X and the gateway did
Y" rather than "something is wrong".

THE BASE URL, THE KEY AND THE ALIAS COME FROM `../gateway.py` and are not repeated
here. Seven folders under ../ need those same three facts, and an alias written
down seven times is six places to forget when `GATEWAY_ENGINE` changes. What stays
here is only what is true of THIS folder: the contract table and the OpenAI client.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

# The three shared facts, one level up. `../gateway.py` reads ../../.env itself
# with no dependency on `python-dotenv`, because it also has to import inside
# `1_http_client`, whose venv is empty.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway import ALIAS as DEFAULT_MODEL  # noqa: E402
from gateway import API_KEY, BASE_URL, BODY_EXTRAS, NAME, REQUEST_TIMEOUT_SECONDS  # noqa: E402

IMAGE_PATH = Path(__file__).resolve().parent / "test_image.png"


class CheckFailed(AssertionError):
    """A call succeeded but the answer was not what the scenario required."""


@dataclass(frozen=True)
class Gateway:
    """THE CONTRACT FOR CALLING THIS GATEWAY, declared as data.

    A scenario spreads `**gateway.body_extras` into its request and reads nothing
    else, so it cannot grow gateway-specific behaviour by accident.

    Fields, and the measurement behind each (all verified 2026-09-03, `lms-4b`):

    body_extras
        What a caller MUST add. EMPTY here: LiteLLM stores a `max_tokens` on the
        route and every local route in ../../config/ does, so a caller who sends none
        still gets a bounded reply. See the block comment on GATEWAY below.
    checks_api_key
        LiteLLM answers 401 to `Bearer sk-wrong`. Anything else means the master
        key is not being enforced.
    lists_models
        `GET {base_url}/models` returns the alias list.
    echoes_alias
        `response.model` is the ALIAS the caller sent (`lms-4b`), not the engine's
        own id. Anything keying metrics or logs off `response.model` gets the name
        it asked for.
    exposes_route_limits
        `/model/info` reports each route's stored `max_tokens` and
        `max_input_tokens`.
    """

    name: str
    base_url: str
    api_key: str
    body_extras: dict
    checks_api_key: bool
    lists_models: bool
    echoes_alias: bool
    exposes_route_limits: bool


# WHO OWNS `max_tokens` — the one difference a caller feels most, and the reason
# `BODY_EXTRAS` in ../gateway.py is EMPTY here rather than a copy of MAX_TOKENS.
#
# Measured 2026-09-03, `lms-4b`, one prompt ("count from 1 to 3000") sent with NO
# `max_tokens` in the body:
#
#   LiteLLM 24000   finish_reason "length" at  4095 completion tokens — the
#                   `max_tokens: 4096` that config/lms.yaml stores on the route
#
# Scripts 01-03 therefore run against the STORED ROUTE DEFAULT, which is worth
# testing: it is what every caller who forgets `max_tokens` actually gets.
# `openai-mini` is the one route here that stores none — OpenAI's own default
# applies there, which is generous.
#
# THE FOUR BOOLEANS ARE THIS FOLDER'S ALONE. They are the calling contract
# 04_gateway_contract.py checks, and no other folder under ../ needs them, so they
# are declared here rather than in ../gateway.py.
GATEWAY = Gateway(
    name=NAME,
    base_url=BASE_URL,
    api_key=API_KEY,
    body_extras=BODY_EXTRAS,
    checks_api_key=True,
    lists_models=True,
    echoes_alias=True,
    exposes_route_limits=True,
)


def client_for(gateway: Gateway) -> OpenAI:
    return OpenAI(
        base_url=gateway.base_url,
        api_key=gateway.api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )


def encode_image(path: Path = IMAGE_PATH) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def _reasoning_of(message) -> str:
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

    thinking = _reasoning_of(choice.message)
    if thinking:
        # The allowance is NOT necessarily MAX_TOKENS: a scenario here sends no
        # ceiling and gets the route's stored `max_tokens` instead. So name the
        # place rather than a number this function cannot know.
        raise CheckFailed(
            f"empty content, finish_reason={choice.finish_reason!r}: the model spent its whole "
            f"token allowance on a reasoning block ({len(thinking)} chars) and never started the "
            "reply. Raise the route's `max_tokens` in ../../config/<engine>.yaml."
        )
    raise CheckFailed(f"the model returned empty content, finish_reason={choice.finish_reason!r}")


def show(title: str, response: object) -> None:
    """Print the whole response, then let the scenario print the part it checks."""
    print(f"--- {title}: ---")
    print(response.to_json() if hasattr(response, "to_json") else response)


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"alias to call (default: {DEFAULT_MODEL})")
    return parser.parse_args()


def run(scenario: Callable[[Gateway, str], str], description: str) -> int:
    """Drive one scenario against this gateway. Returns a process exit code."""
    args = parse_args(description)

    print(f"\n{'=' * 70}\n{description}\n{GATEWAY.name} -> {GATEWAY.base_url}  model={args.model}\n{'=' * 70}")
    started = time.perf_counter()
    try:
        summary, passed = scenario(GATEWAY, args.model), True
    except Exception as error:  # noqa: BLE001 — a failing test reports, it does not crash
        # The class name matters: CheckFailed is a wrong answer, anything else is
        # a transport or gateway failure, and they are fixed in different places.
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {GATEWAY.name:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1
