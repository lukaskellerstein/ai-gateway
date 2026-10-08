"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. ENVOY.

Every other file in this folder is byte-identical to the same folder in
../../../litellm/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: `run_all.py` reads it before any scenario loads LangChain.
"""

from __future__ import annotations

import os

NAME = "envoy"

# 26000 is the data plane. The admin server on 26064 answers `/health` seconds before
# 26000 accepts a connection, so nothing here probes it.
ROOT_URL = "http://localhost:26000"
BASE_URL = f"{ROOT_URL}/v1"

# WHAT `run_all.py` PROBES BEFORE IT STARTS, and it is the DATA PLANE: probing the
# admin port races the thing being tested, and the first scenario then fails with a
# connection reset.
HEALTH_URL = f"{ROOT_URL}/v1/models"
START_HINT = "cd ../.. && podman compose up -d"

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller; ChatOpenAI still wants
# an `api_key`, so something harmless goes in it.
API_KEY = "no-key-needed"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME — `reasoning_effort=` on ChatOpenAI puts it in
# every body. Qwen 3.8's template defaults to `xhigh`, where one agent step took 693 s
# and answered nothing (2026-09-30), and Envoy cannot store a default of its own
# (envoyproxy/ai-gateway#1985). Gemma ignores it. An empty
# AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token, and a deep
# agent's harness puts several thousand tokens in front of every one.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE CEILING EVERY REQUEST MUST CARRY HERE. An AIGatewayRoute stores no token limit:
# with none sent, one prompt ran to 13946 tokens on Envoy where LiteLLM stopped at its
# route's 4096 (2026-09-04). 8192 is what LiteLLM's Unsloth and Ollama routes store.
# 2048 was too low for a model that thinks: Gemma 4 26B on Unsloth spent all of it
# thinking on run_benchmark.py's third turn and never answered (2026-09-30).
#
# langchain-openai 1.6.0 sends `max_tokens=` as `max_completion_tokens` on every
# request, which OpenAI's newer models require and LMStudio honours: a ceiling of 12
# came back `finish_reason: length` at 11 tokens through 26000 (2026-09-30).
MAX_TOKENS: int | None = 8192

# THE GATEWAY'S MCP ENDPOINT, and the ONE address 08_gateway_mcp.py gives the agent.
# What answers behind it is the MCPRoute at the end of every ../../config/*.yaml.
MCP_URL = f"{ROOT_URL}/mcp"

# NOTHING TO SEND: Envoy checks no caller on /mcp, as on its LLM routes.
MCP_HEADERS: dict[str, str] = {}

# The port the `bench-hardware` Backend in ../../config/*.yaml names, so 08 starts
# mcp_server.py there. LiteLLM's is 24090, so both suites can run at the same time.
MCP_SERVER_PORT = 26090

# How the gateway renames a backend's tools: `<backend>__<tool>`. The backend is
# `bench-hardware` and not `bench_hardware` because a Kubernetes name allows no
# underscore.
MCP_TOOL_PREFIX = "bench-hardware__"
