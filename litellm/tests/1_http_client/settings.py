"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. LITELLM.

Every other file in this folder is byte-identical to the same folder in
../../../envoy/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: this folder has no dependencies at all.
"""

from __future__ import annotations

import os

NAME = "litellm"

# 24000, not 4000: the 2xxxx band keeps a probe from reaching a different project's
# gateway and going green.
ROOT_URL = "http://localhost:24000"
BASE_URL = f"{ROOT_URL}/v1"

# A virtual key from /key/generate — this laptop exports one from ~/Projects/.envrc.
# The master key is the fallback, and it has no ceiling.
API_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME. Qwen 3.8's template defaults to `xhigh`, where one
# agent step took 693 s and answered nothing (2026-09-30); LiteLLM stores `medium` on
# its Qwen routes, Envoy stores nothing, so a caller that sends the level gets the same
# answer on both. Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0


def body_extras(alias: str) -> dict:
    """What every request body must carry on this gateway.

    Only the level here: LiteLLM stores a `max_tokens` on every local route, so a
    caller that sends none still gets a bounded reply.
    """
    return {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}
