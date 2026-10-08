"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. LITELLM.

Every other file in this folder is byte-identical to the same folder in
../../../envoy/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: `run_all.py` reads it to probe the gateway before any
scenario starts the Codex runtime.
"""

from __future__ import annotations

import os

NAME = "litellm"

# 24000, not 4000: the 2xxxx band keeps a probe from reaching a different project's
# gateway and going green.
ROOT_URL = "http://localhost:24000"

# The OpenAI surface. Codex never calls it; the benchmark's warm-up does, because it
# loads the same engine the Responses route reaches.
BASE_URL = f"{ROOT_URL}/v1"

# THE RESPONSES SURFACE, and the only one Codex speaks: its `WireApi` has exactly one
# variant since `chat` was removed. LiteLLM serves /v1/responses beside the chat
# routes (POST -> 200, 2026-09-04).
RESPONSES_BASE_URL = BASE_URL

# What run_all.py probes before four scenarios fail the same way. Liveliness, not
# readiness: Codex needs the proxy to answer, not the database to be attached —
# completions keep working without one.
HEALTH_URL = f"{ROOT_URL}/health/liveliness"
START_HINT = "cd ../.. && podman compose up -d"

# A virtual key from /key/generate — this laptop exports one from ~/Projects/.envrc.
# The master key is the fallback, and it has no ceiling. Codex reads it from an environment
# variable that common.py names, never from its own config.
API_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME — the `model_reasoning_effort` override, which
# Codex sends as `reasoning: {effort, summary: "auto"}` in every request (seen on the
# wire, 2026-09-30). Qwen 3.8's template defaults to `xhigh`, where one agent step took
# 693 s and answered nothing (2026-09-30); LiteLLM stores `medium` on its Qwen routes,
# Envoy stores nothing, so a caller that sends the level gets the same answer on both.
# Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token. Codex
# takes this as the provider's `stream_idle_timeout_ms`, whose own default is five
# minutes of silence.
REQUEST_TIMEOUT_SECONDS = 3600.0

# WHEN CODEX COMPACTS. It summarises a conversation that nears this many tokens, and
# for a model it does not know it assumes a small default and compacts far too early:
# an agent that forgets things mid-task, and a summary that replaces the prefix the
# engine had cached. Set it to what the alias really holds.
CONTEXT_WINDOW = 122880


def body_extras(alias: str) -> dict:
    """What a hand-built request body must carry on this gateway.

    Codex builds its own bodies; only the benchmark's warm-up is built here. The level
    alone: LiteLLM stores a `max_tokens` on every local route, so a caller that sends
    none still gets a bounded reply.
    """
    return {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}

# THE GATEWAY'S MCP ENDPOINT, and the ONE address 05_gateway_mcp.py gives Codex.
# What answers behind it is ../../config/settings.yaml § mcp_servers.
MCP_URL = f"{ROOT_URL}/mcp"

# LiteLLM checks the caller on /mcp as on every route, and `x-litellm-api-key` is the
# header it always reads as its own key there (auth/user_api_key_auth_mcp.py:416).
MCP_HEADERS = {"x-litellm-api-key": f"Bearer {API_KEY}"}

# The port ../../config/settings.yaml expects `bench_hardware` on, so 05 starts
# mcp_server.py there. Envoy's is 26090, so both suites can run at the same time.
MCP_SERVER_PORT = 24090

# THE ALIASES ON WHICH 05 ASSERTS THE CALL. `openrouter-gemma4-26b` called the tool
# through /mcp here (one paid run, 2026-10-07), and it is the alias 04 asserts too.
# No local alias, because of openai/codex#19871. It bills, so a free `run_all.py`
# never runs it — `--model openrouter-gemma4-26b` does.
GATEWAY_MCP_CALLS_THE_TOOL = frozenset({"openrouter-gemma4-26b"})
