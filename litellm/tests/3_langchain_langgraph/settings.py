"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. LITELLM.

Every other file in this folder is byte-identical to the same folder in
../../../envoy/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: these are values, and nothing else in the folder has to be
installed to read them.
"""

from __future__ import annotations

import os

NAME = "litellm"

# 24000, not 4000: the 2xxxx band keeps a probe from reaching a different project's
# gateway and going green.
ROOT_URL = "http://localhost:24000"

# ChatOpenAI's `base_url`. The client appends /chat/completions itself.
BASE_URL = f"{ROOT_URL}/v1"

# A virtual key from /key/generate — this laptop exports one from ~/Projects/.envrc.
# The master key is the fallback, and it has no ceiling.
API_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME — `reasoning_effort=` on ChatOpenAI puts it in the
# body. Qwen 3.8's template defaults to `xhigh`, where one agent step took 693 s and
# answered nothing (2026-09-30); LiteLLM stores `medium` on its Qwen routes, Envoy
# stores nothing, so a caller that sends the level gets the same answer on both. Gemma
# ignores it. An empty AI_GATEWAY_REASONING_EFFORT sends none: ChatOpenAI drops a None.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# NONE SENT ON THIS GATEWAY. LiteLLM stores a `max_tokens` on every local route, so a
# caller that sends none still gets a bounded reply — `length` at 4095 tokens, the
# route's 4096 (2026-09-03). ChatOpenAI leaves a None out of the body.
MAX_TOKENS: int | None = None

# ChatOpenAI TURNS STREAMED USAGE OFF BY ITSELF once `base_url` is set — langchain-openai
# 1.6.0 assumes a non-OpenAI server cannot count mid-stream — and a streamed reply then
# carries no token counts at all: no prompt, no cached, no thinking. This gateway sends
# them when asked. Only a streaming call reads it.
STREAM_USAGE = True

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE GATEWAY'S MCP ENDPOINT, and the ONE address run.py's demo 3 gives the agent.
# What answers behind it is ../../config/settings.yaml § mcp_servers.
MCP_URL = f"{ROOT_URL}/mcp"

# LiteLLM checks the caller on /mcp as on every route, and `x-litellm-api-key` is the
# header it always reads as its own key there (auth/user_api_key_auth_mcp.py:416).
MCP_HEADERS = {"x-litellm-api-key": f"Bearer {API_KEY}"}

# The port ../../config/settings.yaml expects `bench_hardware` on, so demo 3 starts
# mcp_server.py there. Envoy's is 26090, so both suites can run at the same time.
MCP_SERVER_PORT = 24090

# How the gateway renames a server's tools: `<server>-<tool>`
# (MCP_TOOL_PREFIX_SEPARATOR, litellm/proxy/_experimental/mcp_server/utils.py:53).
MCP_TOOL_PREFIX = "bench_hardware-"
