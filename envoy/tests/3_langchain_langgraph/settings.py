"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. ENVOY.

Every other file in this folder is byte-identical to the same folder in
../../../litellm/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: these are values, and nothing else in the folder has to be
installed to read them.
"""

from __future__ import annotations

import os

NAME = "envoy"

# 26000 is the data plane. The admin server on 26064 answers `/health` seconds before
# 26000 accepts a connection, so nothing here probes it.
ROOT_URL = "http://localhost:26000"

# ChatOpenAI's `base_url`. The client appends /chat/completions itself.
BASE_URL = f"{ROOT_URL}/v1"

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller; ChatOpenAI still
# demands an `api_key`, so something harmless goes in it.
API_KEY = "no-key-needed"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME — `reasoning_effort=` on ChatOpenAI puts it in the
# body. Qwen 3.8's template defaults to `xhigh`, where one agent step took 693 s and
# answered nothing (2026-09-30), and Envoy cannot store a default of its own
# (envoyproxy/ai-gateway#1985). Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT
# sends none: ChatOpenAI drops a None.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# THE CEILING EVERY REQUEST MUST CARRY HERE. An AIGatewayRoute stores no token limit:
# with none sent, one prompt ran to 13946 tokens on Envoy where LiteLLM stopped at its
# route's 4096 (2026-09-04). 8192 is what LiteLLM's Unsloth and Ollama routes store.
# 2048 was too low for a model that thinks: Gemma 4 26B on Unsloth spent all of it
# thinking on run_benchmark.py's third turn and never answered (2026-09-30).
# ChatOpenAI SENDS IT AS `max_completion_tokens` for every model — the name OpenAI's
# newer models demand, so no per-alias switch is needed — and LMStudio honours that
# name: `length` at 39 tokens under a ceiling of 40, through Envoy (2026-09-30).
MAX_TOKENS: int | None = 8192

# ChatOpenAI TURNS STREAMED USAGE OFF BY ITSELF once `base_url` is set — langchain-openai
# 1.6.0 assumes a non-OpenAI server cannot count mid-stream — and a streamed reply then
# carries no token counts at all: no prompt, no cached, no thinking. This gateway sends
# them when asked. Only a streaming call reads it.
STREAM_USAGE = True

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE GATEWAY'S MCP ENDPOINT, and the ONE address run.py's demo 3 gives the agent.
# What answers behind it is the MCPRoute at the end of every ../../config/*.yaml.
MCP_URL = f"{ROOT_URL}/mcp"

# NOTHING TO SEND: Envoy checks no caller on /mcp, as on its LLM routes.
MCP_HEADERS: dict[str, str] = {}

# The port the `bench-hardware` Backend in ../../config/*.yaml names, so demo 3
# starts mcp_server.py there. LiteLLM's is 24090, so both suites can run at once.
MCP_SERVER_PORT = 26090

# How the gateway renames a backend's tools: `<backend>__<tool>`. The backend is
# `bench-hardware` and not `bench_hardware` because a Kubernetes name allows no
# underscore.
MCP_TOOL_PREFIX = "bench-hardware__"
