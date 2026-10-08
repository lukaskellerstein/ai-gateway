"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. ENVOY.

Every other file in this folder is byte-identical to the same folder in
../../../litellm/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: `run_all.py` reads it to probe the gateway before any
scenario starts the Codex runtime.
"""

from __future__ import annotations

import os

NAME = "envoy"

# 26000 is the data plane. The admin server on 26064 answers `/health` seconds before
# 26000 accepts a connection, so nothing here probes it.
ROOT_URL = "http://localhost:26000"

# The OpenAI surface. Codex never calls it; the benchmark's warm-up does, because it
# loads the same engine the Responses route reaches.
BASE_URL = f"{ROOT_URL}/v1"

# THE RESPONSES SURFACE, and the only one Codex speaks: its `WireApi` has exactly one
# variant since `chat` was removed. Envoy passes /v1/responses through to the engine's
# own Responses route (POST -> 200, 2026-09-04).
RESPONSES_BASE_URL = BASE_URL

# WHAT `run_all.py` PROBES BEFORE IT STARTS, and it is the DATA PLANE: probing the
# admin port races the thing being tested, and the first scenario then fails with a
# connection reset.
HEALTH_URL = f"{ROOT_URL}/v1/models"
START_HINT = "cd ../.. && podman compose up -d"

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller; Codex still sends a
# bearer token from the environment variable common.py names, so something harmless
# goes in it.
API_KEY = "no-key-needed"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME — the `model_reasoning_effort` override, which
# Codex sends as `reasoning: {effort, summary: "auto"}` in every request (seen on the
# wire, 2026-09-30). Qwen 3.8's template defaults to `xhigh`, where one agent step took
# 693 s and answered nothing (2026-09-30), and Envoy cannot store a default of its own
# (envoyproxy/ai-gateway#1985). Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT
# sends none.
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

# THE CEILING A HAND-BUILT BODY MUST CARRY HERE. An AIGatewayRoute stores no token limit:
# with none sent, one prompt ran to 13946 tokens on Envoy where LiteLLM stopped at its
# route's 4096 (2026-09-04). 8192 is what LiteLLM's Unsloth and Ollama routes store.
# 2048 was too low for a model that thinks: Gemma 4 26B on Unsloth spent all of it
# thinking on run_benchmark.py's third turn and never answered (2026-09-30).
MAX_TOKENS = 8192


def body_extras(alias: str) -> dict:
    """What a hand-built request body must carry on this gateway: a ceiling and the level.

    Codex builds its own bodies; only the benchmark's warm-up is built here. OpenAI's
    newer models REJECT `max_tokens` — `400 ... Use 'max_completion_tokens' instead`
    (2026-09-05) — and Envoy passes the body through untouched, so the caller names the
    field the upstream accepts.
    """
    ceiling = "max_completion_tokens" if alias.startswith("openai-") else "max_tokens"
    level = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}
    return {ceiling: MAX_TOKENS, **level}

# THE GATEWAY'S MCP ENDPOINT, and the ONE address 05_gateway_mcp.py gives Codex.
# What answers behind it is the MCPRoute at the end of every ../../config/*.yaml.
MCP_URL = f"{ROOT_URL}/mcp"

# NOTHING TO SEND: Envoy checks no caller on /mcp, as on its LLM routes.
MCP_HEADERS: dict[str, str] = {}

# The port the `bench-hardware` Backend in ../../config/*.yaml names, so 05
# starts mcp_server.py there. LiteLLM's is 24090, so both suites can run at once.
MCP_SERVER_PORT = 26090

# THE ALIASES ON WHICH 05 ASSERTS THE CALL: NONE, ON ANY MODEL. Codex 0.155.1 lists this
# gateway's tools and then DROPS them, so the model is offered nothing. Envoy's
# tools/list result carries `"ttlMs":0,"cacheScope":""`, and Codex discards a result
# that carries `cacheScope` at all: "", "thisServer" and "allServers" were each dropped
# by a fake server, and `ttlMs` alone was kept. Measured 2026-10-07: the request Codex
# then sent had no `mcp__gateway` namespace, and `openrouter-gemma4-26b`, which calls
# the tool through LiteLLM, answered without it. 05's listing marker is still written.
GATEWAY_MCP_CALLS_THE_TOOL: frozenset[str] = frozenset()
