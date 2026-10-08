"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. LITELLM.

Every other file in this folder is byte-identical to the same folder in
../../../envoy/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

It also carries this gateway's CALLING CONTRACT, which `04_gateway_contract.py`
checks against the running gateway. Point a copy at another gateway and state that
gateway's contract in `CONTRACT` below; 04 then says whether it is true.

Standard library only.
"""

from __future__ import annotations

import os

NAME = "litellm"

# 24000, not 4000: the 2xxxx band keeps a probe from reaching a different project's
# gateway and going green.
ROOT_URL = "http://localhost:24000"
BASE_URL = f"{ROOT_URL}/v1"

# What run_all.py probes before five scripts fail the same way. LiteLLM's /health
# needs the master key; /health/liveliness does not, and only asks "is it answering".
HEALTH_URL = f"{ROOT_URL}/health/liveliness"

# A virtual key from /key/generate — this laptop exports one from ~/Projects/.envrc.
# The master key is the fallback, and it has no ceiling.
API_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL. It is
# the default because 03_multimodal.py needs vision and 02_tools_call.py needs tools
# from one small model.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME. Qwen 3.8's template defaults to `xhigh`, where one
# agent step took 693 s and answered nothing (2026-09-30); LiteLLM stores `medium` on
# its Qwen routes, Envoy stores nothing, so a caller that sends the level gets the same
# answer on both. Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# NO RETRIES. The client silently retries a timeout or a 5xx twice by default, so a
# test would hide the failure it exists to find and a benchmark would time two
# requests as one.
MAX_RETRIES = 0


def body_extras(alias: str) -> dict:
    """What every request body must carry on this gateway.

    Only the level here: LiteLLM stores a `max_tokens` on every local route, so a
    caller that sends none still gets a bounded reply — see `exposes_route_limits`.
    """
    return {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}


# THIS GATEWAY'S CALLING CONTRACT — what a caller has to get right and cannot see in
# a response body. `04_gateway_contract.py` checks each line against the running
# gateway, so a failure reads "the table says X and the gateway did Y". The Envoy
# copy of this file declares its own, and only `lists_models` matches. Verified
# 2026-09-03 with `lms-gemma4-e4b` unless dated otherwise.
CONTRACT = {
    # The port refuses a connection on this machine's NETWORK address: compose publishes
    # it on 127.0.0.1 only, so no other machine can call the gateway (2026-10-07).
    "loopback_only": True,
    # A bogus Bearer token gets 401: the master key is enforced.
    "checks_api_key": True,
    # GET /v1/models returns the alias list, so a caller can discover the vocabulary.
    "lists_models": True,
    # `response.model` is the ALIAS that was sent, not the engine's own id, so a
    # metric or a log line keyed off it gets the name it asked for.
    "echoes_alias": True,
    # /model/info reports each route's stored `max_tokens` and `max_input_tokens`.
    # THE ONE A CALLER FEELS MOST, and why `body_extras` sends no ceiling: one "count
    # to 3000" prompt with NO `max_tokens` stopped at 4095 completion tokens,
    # finish_reason "length" — the route's stored 4096. Envoy, storing none, ran the
    # same prompt to 13946 (2026-09-04).
    "exposes_route_limits": True,
    # The level a Qwen 3.8 route runs at when a caller sends NONE. Both Qwen routes
    # store `reasoning_effort: medium`, because the template's own default is `xhigh`
    # (2026-09-30, no level, `max_tokens` 1: 62 prompt tokens before, 24 after).
    # 05_reasoning_effort.py checks it.
    "default_effort": "medium",
}
