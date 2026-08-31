"""Shared plumbing for the gateway test scripts.

Every script here answers one question: does this ONE kind of call work through
the gateway? So each script owns a single `scenario` function and nothing else —
the argument parsing, the two base URLs, the timing and the pass/fail printing
all live here, once.

The point of the two gateways is that the caller's vocabulary does not change:
same OpenAI client, same alias in `model`, different `base_url`. That is exactly
what `GATEWAYS` below encodes, and it is why a scenario never names a gateway.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_PATH = Path(__file__).resolve().parent / "test_image.png"

# The repo's own .env, so LITELLM_MASTER_KEY is picked up without exporting it.
# `override=False` on purpose: a value already in the shell wins, the same way
# compose resolves the shell environment before this file.
load_dotenv(REPO_ROOT / ".env", override=False)

# THE DEFAULT ALIAS FOLLOWS THE ENGINE THE STACK IS SERVING. `GATEWAY_ENGINE` in
# .env names ONE engine, and the aliases of every other engine are not in the config
# at all — so a fixed `lms-4b` default would fail with "model not found" on a
# perfectly healthy stack.
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
    """The scenario alias for whichever engine `.env` names.

    AN UNRECOGNISED ENGINE IS AN ERROR, NOT A FALLBACK. Quietly defaulting to
    `lms-4b` was worse than failing: it produced "Invalid model name passed in
    model=lms-4b" from a perfectly healthy stack serving a different engine, which
    reads as a broken gateway rather than a stale `.env`. `all` used to be valid
    and is exactly the value people still have written down.
    """
    engine = os.environ.get("GATEWAY_ENGINE", "lms").strip()
    if engine not in DEFAULT_MODEL_BY_ENGINE:
        raise SystemExit(
            f"GATEWAY_ENGINE is {engine!r}, which is not an engine this repo serves.\n"
            f"  It must be one of: {', '.join(DEFAULT_MODEL_BY_ENGINE)}.\n"
            "  One engine at a time — a list and the old `all` are no longer accepted.\n"
            "  Fix .env, or pass --model to choose an alias directly."
        )
    if DEFAULT_MODEL_BY_ENGINE[engine] is None:
        raise SystemExit(
            f"GATEWAY_ENGINE is {engine!r}, which has no alias that passes every scenario "
            "here:\n  gpt-5.4-mini has no vision, so 03_multimodal.py cannot pass.\n"
            "  Pass --model openai-mini explicitly and expect that one to fail."
        )
    return DEFAULT_MODEL_BY_ENGINE[engine]


DEFAULT_MODEL = os.environ.get("AI_GATEWAY_TEST_MODEL") or _default_model()

# LMStudio prompt processing measures ~100 tok/s on this machine, so a large
# prompt needs minutes before its first token — the same fact that puts
# `timeout: 3600` on every chat route in litellm/. Retries are off because a test
# that silently retries hides the failure it exists to find.
REQUEST_TIMEOUT_SECONDS = 3600.0

# One allowance for every script, and it has to clear a REASONING block. Both
# `unsloth-*` chat routes, both `ollama-*` ones and `lms-4b` spend this same budget
# on thinking before they write a word. A model that runs out mid-thought returns
# EMPTY content with `finish_reason: "length"` and raises nothing, which reads as a
# broken alias. 150 was not enough for a one-sentence answer about an image
# (verified 2026-08-27 on `unsloth-26b`).
#
# Raising it costs nothing when the model does not need it: generation stops at
# `stop`, not at the ceiling.
MAX_TOKENS = 2048


class CheckFailed(AssertionError):
    """A call succeeded but the answer was not what the scenario required."""


@dataclass(frozen=True)
class Gateway:
    name: str
    base_url: str
    api_key: str


# The master key mints virtual keys and has no ceiling, so AI_GATEWAY_KEY (a
# capped key from /key/generate) is preferred when the shell carries one.
_LITELLM_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

GATEWAYS: dict[str, Gateway] = {
    "litellm": Gateway("litellm", "http://localhost:24000/v1", _LITELLM_KEY),
    # The MLflow gateway has NO key at all. The OpenAI client refuses to build
    # without one, so this string is a placeholder that MLflow never reads.
    "mlflow": Gateway("mlflow", "http://localhost:25000/gateway/mlflow/v1", "no-key-needed"),
}


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
            f"{MAX_TOKENS}-token allowance on a reasoning block ({len(thinking)} chars) and never "
            "started the reply. Raise MAX_TOKENS in common.py."
        )
    raise CheckFailed(f"the model returned empty content, finish_reason={choice.finish_reason!r}")


def show(title: str, response: object) -> None:
    """Print the whole response, then let the scenario print the part it checks."""
    print(f"--- {title}: ---")
    print(response.to_json() if hasattr(response, "to_json") else response)


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--gateway",
        choices=[*GATEWAYS, "both"],
        default="both",
        help="which gateway to drive (default: both)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"alias to call (default: {DEFAULT_MODEL})")
    return parser.parse_args()


def running_gateways() -> list[str]:
    """The gateways this `.env` actually starts, from compose's own COMPOSE_PROFILES.

    A stack brought up with `COMPOSE_PROFILES=mlflow` has no LiteLLM at all, and
    driving 24000 there produces a connection error that says nothing about the
    change being tested. Unset means "not configured": every gateway is tried and
    the health check in run_all.py reports whichever is down.
    """
    profiles = {word.strip() for word in os.environ.get("COMPOSE_PROFILES", "").split(",") if word.strip()}
    if not profiles:
        return list(GATEWAYS)
    chosen = [name for name in GATEWAYS if name in profiles or "all" in profiles]
    return chosen or list(GATEWAYS)


def selected(name: str) -> list[Gateway]:
    if name != "both":
        return [GATEWAYS[name]]
    return [GATEWAYS[chosen] for chosen in running_gateways()]


def run(scenario: Callable[[Gateway, str], str], description: str) -> int:
    """Drive one scenario across the chosen gateways. Returns a process exit code."""
    args = parse_args(description)
    results: list[tuple[str, bool, str, float]] = []

    for gateway in selected(args.gateway):
        print(f"\n{'=' * 70}\n{description}\n{gateway.name} -> {gateway.base_url}  model={args.model}\n{'=' * 70}")
        started = time.perf_counter()
        try:
            summary = scenario(gateway, args.model)
            results.append((gateway.name, True, summary, time.perf_counter() - started))
        except Exception as error:  # noqa: BLE001 — a failing test reports, it does not crash
            # The class name matters: CheckFailed is a wrong answer, anything
            # else is a transport or gateway failure, and they are fixed in
            # different places.
            results.append((gateway.name, False, f"{type(error).__name__}: {error}", time.perf_counter() - started))

    print(f"\n{'-' * 70}")
    for name, passed, summary, seconds in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name:8s} {seconds:6.1f}s  {summary}")
    return 0 if all(passed for _, passed, _, _ in results) else 1
