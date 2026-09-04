"""Shared plumbing for this project's test scripts. MLFLOW ONLY.

Every script here answers one question: does this ONE kind of call work through
the MLflow AI Gateway on 25000? So each script owns a single `scenario` function
and nothing else — the argument parsing, the base URL, the timing and the
pass/fail printing all live here, once.

THIS SUITE DRIVES ONE GATEWAY, AND THAT IS NEW. Before the split there was one
`tests/` at the repo root that ran every script against both ports and proved the
two gateways shared a vocabulary: same alias, same messages, two base URLs. Each
gateway is a standalone compose project now, with its own `.env` and its own
engine word, so that comparison has no single owner and is no longer made. Nothing
here — and nothing anywhere in the repo — checks that `lms-4b` also answers on
24000. If you want that, call both ports by hand.

WHAT IS STILL WORTH DECLARING IS THIS GATEWAY'S OWN CALLING CONTRACT, and it is on
`Gateway` below as data. `04_gateway_contract.py` is the test that proves every
line of it is still true, so a failure reads "the table says X and the gateway did
Y" rather than "something is wrong".

FOUR OF THE FIVE LINES IN THAT TABLE ARE `False` HERE, and none of them is a
defect: MLflow's endpoints are database rows, and there is nowhere in a row to put
a key, a price, a ceiling or a model listing.
"""

from __future__ import annotations

import argparse
import base64
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# This project's own .env, one level up — NOT a repo-root one, which no longer
# exists. `override=False` on purpose: a value already in the shell wins, the same
# way compose resolves the shell environment before the file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_PATH = Path(__file__).resolve().parent / "test_image.png"
load_dotenv(PROJECT_ROOT / ".env", override=False)

# THE DEFAULT ALIAS FOLLOWS THE ENGINE THIS PROJECT IS SERVING. `GATEWAY_ENGINE` in
# ./.env names ONE engine, and the endpoints of every other engine are not seeded
# at all — so a fixed `lms-4b` default would 404 on a perfectly healthy gateway.
#
# The chosen names are the small chat route on each engine: the one alias per engine
# that is both VISION- and TOOL-capable, which is what all three scripts here need
# from a single loaded model. Override for a one-off run with --model, or
# permanently with AI_GATEWAY_TEST_MODEL.
#
# `openai` MAPS TO NOTHING ON PURPOSE. gpt-5.4-mini has no vision, so
# 03_multimodal.py cannot pass against it, and a default that always fails one of
# three scripts reads as a broken gateway. Pass --model openai-mini explicitly and
# expect that script to fail.
DEFAULT_MODEL_BY_ENGINE = {
    "lms": "lms-4b",
    "unsloth": "unsloth-4b",
    "ollama": "ollama-4b",
    "openrouter": "openrouter-26b",
    "openai": None,  # no vision; see above
}


def _default_model() -> str:
    """The scenario alias for whichever engine this project's `.env` names.

    AN UNRECOGNISED ENGINE IS AN ERROR, NOT A FALLBACK. Quietly defaulting to
    `lms-4b` was worse than failing: it produced a 404 from a perfectly healthy
    gateway serving a different engine, which reads as a broken gateway rather
    than a stale `.env`.
    """
    engine = os.environ.get("GATEWAY_ENGINE", "lms").strip()
    if engine not in DEFAULT_MODEL_BY_ENGINE:
        raise SystemExit(
            f"GATEWAY_ENGINE is {engine!r}, which is not an engine this project serves.\n"
            f"  It must be one of: {', '.join(DEFAULT_MODEL_BY_ENGINE)}.\n"
            "  One engine at a time — a list is not accepted.\n"
            "  Fix ../.env, or pass --model to choose an alias directly."
        )
    if DEFAULT_MODEL_BY_ENGINE[engine] is None:
        raise SystemExit(
            f"GATEWAY_ENGINE is {engine!r}, which has no alias that passes every scenario "
            "here:\n  gpt-5.4-mini has no vision, so 03_multimodal.py cannot pass.\n"
            "  Pass --model openai-mini explicitly and expect that one to fail."
        )
    return DEFAULT_MODEL_BY_ENGINE[engine]


DEFAULT_MODEL = os.environ.get("AI_GATEWAY_TEST_MODEL") or _default_model()

# LMStudio prompt processing measures ~100 tok/s on this machine, so a large prompt
# needs minutes before its first token — the same fact that sets
# MLFLOW_GATEWAY_ROUTE_TIMEOUT_SECONDS to 3600 in ../compose.yml. Retries are off
# because a test that silently retries hides the failure it exists to find.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE ALLOWANCE EVERY SCENARIO SENDS, and on this gateway it is load-bearing —
# see `body_extras` below. It has to clear a REASONING block: both `unsloth-*` chat
# routes, both `ollama-*` ones and `lms-4b` spend this budget on thinking before
# they write a word. A model that runs out mid-thought returns EMPTY content with
# `finish_reason: "length"` and raises nothing, which reads as a broken alias. 150
# was not enough for a one-sentence answer about an image (verified 2026-08-27 on
# `unsloth-26b`).
#
# Raising it costs nothing when the model does not need it: generation stops at
# `stop`, not at the ceiling.
MAX_TOKENS = 2048


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
        MLflow answers 200 to `Bearer sk-wrong`. It has no key concept at all, so
        the one in `api_key` is a placeholder the OpenAI client demands and MLflow
        never reads.
    lists_models
        `GET {base_url}/models` returns 404. A caller cannot discover this
        gateway's vocabulary over the OpenAI surface; it is in the MLflow UI and
        in ../config/<engine>.py.
    echoes_alias
        `response.model` is the ENGINE'S OWN id (`google/gemma-4-e4b`), not the
        alias the caller sent. Anything keying metrics or logs off
        `response.model` sees a different string from the one it asked for.
    exposes_route_limits
        There is no `/model/info` route and nothing stores a ceiling, so there is
        nothing to read and nothing to protect a caller who sends none. This is
        the fact `body_extras` exists to work around.
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
#   MLflow  25000   finish_reason "stop"   at 13961 completion tokens — nothing
#                   bounded it; the model simply ran out of things to say
#   (LiteLLM, for contrast, stopped at 4095 on its stored route default.)
#
# Same prompt, same alias, same weights: 3.4x the output and 3.4x the wait.
#
# The parameter itself behaves normally when it IS sent: the gateway truncates at
# `max_tokens: 16` and returns EMPTY content with finish_reason "length". What is
# missing is the DEFAULT — MLflow's endpoints are database rows with no place to
# put one.
#
# SO ON 25000 YOU ALWAYS SEND `max_tokens` YOURSELF. Get it wrong downwards and a
# reasoning model spends the whole allowance thinking and returns empty content
# with no error at all — see `answer_of`.
GATEWAY = Gateway(
    name="mlflow",
    base_url="http://localhost:25000/gateway/mlflow/v1",
    api_key="no-key-needed",
    body_extras={"max_tokens": MAX_TOKENS},
    checks_api_key=False,
    lists_models=False,
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
