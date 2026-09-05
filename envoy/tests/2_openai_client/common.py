"""Shared plumbing for this project's test scripts. ENVOY ONLY.

Every script here answers one question: does this ONE kind of call work through
the Envoy AI Gateway on 26000? So each script owns a single `scenario` function
and nothing else — the argument parsing, the base URL, the timing and the
pass/fail printing all live here, once.

THIS SUITE DRIVES ONE GATEWAY, AND THAT IS NEW. Before the split there was one
`tests/` at the repo root that ran every script against both ports and proved the
two gateways shared a vocabulary: same alias, same messages, two base URLs. Each
gateway is a standalone compose project now, with its own `.env` and its own
engine word, so that comparison has no single owner and is no longer made. Nothing
here — and nothing anywhere in the repo — checks that `lms-4b` also answers on
24000. If you want that, call the other port by hand.

WHAT IS STILL WORTH DECLARING IS THIS GATEWAY'S OWN CALLING CONTRACT, and it is on
`Gateway` below as data. `04_gateway_contract.py` is the test that proves every
line of it is still true, so a failure reads "the table says X and the gateway did
Y" rather than "something is wrong".

THIS GATEWAY IS NOT A COPY OF THE OTHER ONE. It lists its models like LiteLLM
does, and then checks no caller key at all and echoes the upstream model id rather
than the alias — so a test that assumed "LiteLLM or not-LiteLLM" would be wrong
about it. That is why each project declares its own table.

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
from gateway import API_KEY, BASE_URL, BODY_EXTRAS, MAX_TOKENS, NAME, REQUEST_TIMEOUT_SECONDS  # noqa: E402

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
        What a caller MUST add. `max_tokens` here, and it is not optional — see
        the block comment on GATEWAY below.
    checks_api_key
        This gateway answers 200 to `Bearer sk-wrong`. `aigw run` has no caller
        authentication of any kind — the key in `api_key` is a placeholder the
        OpenAI client demands and nothing here reads. The key that DOES matter is
        the one the gateway sends UPSTREAM, out of a Secret in
        ../../config/<engine>.yaml, and a caller never sees it.
    lists_models
        `GET {base_url}/models` returns the alias list, built from the
        AIGatewayRoute rules — the one contract line where this gateway matches
        LiteLLM.
    echoes_alias
        `response.model` is the ENGINE'S OWN id (`google/gemma-4-e4b`), not the
        alias the caller sent — `modelNameOverride` rewrote it on the way out and
        nothing rewrites it back. Anything keying metrics or logs off
        `response.model` sees a different string from the one it asked for.
    exposes_route_limits
        There is no `/model/info` route, and an AIGatewayRoute rule carries a
        request TIMEOUT but no token ceiling, so there is nothing to read and
        nothing to protect a caller who sends none. This is the fact
        `body_extras` exists to work around.
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
# `body_extras` carries one here.
#
# Measured 2026-09-03, `lms-4b`, one prompt ("count from 1 to 3000") sent with NO
# `max_tokens` in the body:
#
#   Envoy   26000   finish_reason "stop"   at 13946 completion tokens — nothing
#                   bounded it; the model simply ran out of things to say
#   (LiteLLM, for contrast, stopped at 4095 on its stored route default on the
#    same prompt. Measured here 2026-09-04.)
#
# Same prompt, same alias, same weights: 3.4x the output and 3.4x the wait.
#
# The parameter itself behaves normally when it IS sent: the gateway truncates at
# `max_tokens: 16` and returns EMPTY content with finish_reason "length". What is
# missing is the DEFAULT — an AIGatewayRoute rule carries a request timeout but
# no token ceiling.
#
# SO ON 26000 YOU ALWAYS SEND `max_tokens` YOURSELF. Get it wrong downwards and a
# reasoning model spends the whole allowance thinking and returns empty content
# with no error at all — see `answer_of`.
GATEWAY = Gateway(
    name=NAME,
    base_url=BASE_URL,
    api_key=API_KEY,
    body_extras=BODY_EXTRAS,
    checks_api_key=False,
    lists_models=True,
    echoes_alias=False,
    exposes_route_limits=False,
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
        raise CheckFailed(
            f"empty content, finish_reason={choice.finish_reason!r}: the model spent its whole "
            f"token allowance ({MAX_TOKENS}) on a reasoning block ({len(thinking)} chars) and "
            "never started the reply. Raise MAX_TOKENS in common.py."
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
