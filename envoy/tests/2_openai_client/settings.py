"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. ENVOY.

Every other file in this folder is byte-identical to the same folder in
../../../litellm/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

It also carries this gateway's CALLING CONTRACT, which `04_gateway_contract.py`
checks against the running gateway. Point a copy at another gateway and state that
gateway's contract in `CONTRACT` below; 04 then says whether it is true.

Standard library only.
"""

from __future__ import annotations

import os

NAME = "envoy"

# 26000 is the data plane. The admin server on 26064 answers `/health` seconds before
# 26000 accepts a connection, so nothing here probes it.
ROOT_URL = "http://localhost:26000"
BASE_URL = f"{ROOT_URL}/v1"

# What run_all.py probes before five scripts fail the same way. THE DATA PLANE, NOT
# THE ADMIN PORT: probing 26064 races the listener, and the first script then fails
# with a connection reset (2026-09-04). /v1/models needs no key.
HEALTH_URL = f"{BASE_URL}/models"

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller; the OpenAI client
# still demands a bearer token, so something harmless goes in it.
API_KEY = "no-key-needed"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL. It is
# the default because 03_multimodal.py needs vision and 02_tools_call.py needs tools
# from one small model.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME. Qwen 3.8's template defaults to `xhigh`, where one
# agent step took 693 s and answered nothing (2026-09-30), and Envoy cannot store a
# default of its own (envoyproxy/ai-gateway#1985). Gemma ignores it. An empty
# AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# NO RETRIES. The client silently retries a timeout or a 5xx twice by default, so a
# test would hide the failure it exists to find and a benchmark would time two
# requests as one.
MAX_RETRIES = 0

# THE CEILING EVERY REQUEST MUST CARRY HERE. An AIGatewayRoute stores no token limit:
# with none sent, one prompt ran to 13946 tokens on Envoy where LiteLLM stopped at its
# route's 4096 (2026-09-04). 8192 is what LiteLLM's Unsloth and Ollama routes store.
# 2048 was too low for a model that thinks: Gemma 4 26B on Unsloth spent all of it
# thinking on run_benchmark.py's third turn and never answered (2026-09-30), and 150
# tokens did not finish one sentence about an image (2026-08-27, `unsloth-gemma4-26b`).
MAX_TOKENS = 8192


def body_extras(alias: str) -> dict:
    """What every request body must carry on this gateway: a ceiling and the level.

    OpenAI's newer models REJECT `max_tokens` — `400 ... Use 'max_completion_tokens'
    instead` (2026-09-05) — and Envoy passes the body through untouched, so the caller
    names the field the upstream accepts.
    """
    ceiling = "max_completion_tokens" if alias.startswith("openai-") else "max_tokens"
    level = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}
    return {ceiling: MAX_TOKENS, **level}


# THIS GATEWAY'S CALLING CONTRACT — what a caller has to get right and cannot see in
# a response body. `04_gateway_contract.py` checks each line against the running
# gateway, so a failure reads "the table says X and the gateway did Y". THREE OF THE
# FOUR BOOLEANS ARE `False`, and 04 checks a `False` as hard as a `True`: an absence
# nobody checks is an absence somebody eventually assumes away. The LiteLLM copy of
# this file declares its own, and only `lists_models` matches. Verified 2026-09-04
# with `lms-gemma4-e4b`.
CONTRACT = {
    # The port refuses a connection on this machine's NETWORK address: compose publishes
    # it on 127.0.0.1 only, so no other machine can call the gateway (2026-10-07).
    "loopback_only": True,
    # A bogus Bearer token gets 200: `aigw run` has no caller authentication at all.
    # The key that matters is the one it sends UPSTREAM, out of a Secret in
    # ../../config/<engine>.yaml, and a caller never sees it.
    "checks_api_key": False,
    # GET /v1/models returns the alias list, built from the AIGatewayRoute rules — the
    # one line where this gateway matches LiteLLM.
    "lists_models": True,
    # `response.model` is the ENGINE'S own id (`google/gemma-4-e4b`), not the alias:
    # `modelNameOverride` rewrote it on the way out and nothing rewrites it back.
    "echoes_alias": False,
    # No /model/info route, and a route rule carries a request TIMEOUT but no token
    # ceiling — so nothing protects a caller who sends none, and `body_extras` sends
    # MAX_TOKENS. See the comment on it.
    "exposes_route_limits": False,
    # NONE. aigw cannot add a field to a request body (envoyproxy/ai-gateway#1985), so
    # a Qwen 3.8 route runs its template's own default, `xhigh`, for a caller who
    # sends no level. 05_reasoning_effort.py checks it.
    "default_effort": None,
}
