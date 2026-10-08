"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. ENVOY.

Every other file in this folder is byte-identical to the same folder in
../../../litellm/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: this folder has no dependencies at all.
"""

from __future__ import annotations

import os

NAME = "envoy"

# 26000 is the data plane. The admin server on 26064 answers `/health` seconds before
# 26000 accepts a connection, so nothing here probes it.
ROOT_URL = "http://localhost:26000"
BASE_URL = f"{ROOT_URL}/v1"

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller; the OpenAI wire format
# still wants a bearer token, so something harmless goes in it.
API_KEY = "no-key-needed"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME. Qwen 3.8's template defaults to `xhigh`, where one
# agent step took 693 s and answered nothing (2026-09-30), and Envoy cannot store a
# default of its own (envoyproxy/ai-gateway#1985). Gemma ignores it. An empty
# AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE CEILING EVERY REQUEST MUST CARRY HERE. An AIGatewayRoute stores no token limit:
# with none sent, one prompt ran to 13946 tokens on Envoy where LiteLLM stopped at its
# route's 4096 (2026-09-04). 8192 is what LiteLLM's Unsloth and Ollama routes store.
# 2048 was too low for a model that thinks: Gemma 4 26B on Unsloth spent all of it
# thinking on run_benchmark.py's third turn and never answered (2026-09-30).
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
