"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. LITELLM.

Every other file in this folder is byte-identical to the same folder in
../../../envoy/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

Standard library only: `run_all.py` reads it before any scenario starts OpenCode.
"""

from __future__ import annotations

import os

NAME = "litellm"

# 24000, not 4000: the 2xxxx band keeps a probe from reaching a different project's
# gateway and going green.
ROOT_URL = "http://localhost:24000"

# THE ONE SURFACE OPENCODE USES. `@ai-sdk/openai-compatible` appends
# /chat/completions to it.
BASE_URL = f"{ROOT_URL}/v1"

# WHAT `run_all.py` PROBES BEFORE IT STARTS. Liveliness and not readiness on purpose:
# these scenarios need the proxy to answer, not the database to be attached, and a
# suite that refused to run over a missing database would hide the fact that
# completions keep working without one.
HEALTH_URL = f"{ROOT_URL}/health/liveliness"
START_HINT = "cd ../.. && podman compose up -d"

# A virtual key from /key/generate — this laptop exports one from ~/Projects/.envrc.
# The master key is the fallback, and it has no ceiling.
API_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME — as the model option `reasoningEffort`, which
# `@ai-sdk/openai-compatible` writes into every body as `reasoning_effort` (checked
# against a stub provider, 2026-09-30). Qwen 3.8's template defaults to `xhigh`, where
# one agent step took 693 s and answered nothing (2026-09-30); LiteLLM stores `medium`
# on its Qwen routes, Envoy stores nothing, so a caller that sends the level gets the
# same answer on both. Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token, and
# OpenCode puts its own system prompt and eight tool schemas in front of every one:
# about 5600 of the 7205 prompt tokens of run_benchmark.py's first request, the rest being
# the task (`lms-gemma4-26b`, 2026-09-30).
REQUEST_TIMEOUT_SECONDS = 3600.0

# NO CEILING IS SET HERE, AND NEITHER GATEWAY NEEDS ONE FROM THIS FILE. OpenCode sends
# `max_tokens` on every request by itself: 32000, its default for a model it has no
# catalogue entry for — which also overrides the 4096 LiteLLM stores on a local route
# (stub provider, OpenCode 1.18.30, 2026-09-30).

# THE PROVIDER ID MUST BE ONE NO OTHER OPENCODE CONFIG USES. OpenCode MERGES the config
# this folder hands it over ~/.config/opencode, model by model, and that file on this
# machine declares `ai-gateway-litellm` and `ai-gateway-envoy` with the same aliases.
# Under the plain gateway name every request inherited the file's `limit.output` and
# carried `max_tokens: 8192` instead of 32000 (stub provider, 2026-09-30).
PROVIDER_ID = f"ai-gateway-{NAME}-tests"

# WHAT `opencode serve` RUNS WITH, on top of this shell's environment.
#
# `OPENCODE_DISABLE_CLAUDE_CODE` stops OpenCode reading Claude Code's files. Without it
# ~/.claude/CLAUDE.md went into the system prompt as "Instructions from: ..." and every
# skill under ~/.claude/skills into its skill list, so the prompt depended on who ran
# it: 19048 characters of system prompt with them, 9628 without (stub provider,
# OpenCode 1.18.30, 2026-09-30). It is this folder's `setting_sources=[]`.
#
# NOT AN EMPTY XDG_CONFIG_HOME, which would also drop ~/.config/opencode: OpenCode then
# installs its plugin SDK into the empty directory and ignored SIGTERM until that
# finished (2026-09-30). The provider id above is enough to keep that file out of the
# request; its plugins still load, and they only watch.
OPENCODE_ENVIRONMENT = {"OPENCODE_DISABLE_CLAUDE_CODE": "1"}

# THE GATEWAY'S MCP ENDPOINT, and the ONE address 06_gateway_mcp.py gives OpenCode.
# What answers behind it is ../../config/settings.yaml § mcp_servers.
MCP_URL = f"{ROOT_URL}/mcp"

# LiteLLM checks the caller on /mcp as on every route, and `x-litellm-api-key` is the
# header it always reads as its own key there (auth/user_api_key_auth_mcp.py:416).
MCP_HEADERS = {"x-litellm-api-key": f"Bearer {API_KEY}"}

# The port ../../config/settings.yaml expects `bench_hardware` on, so 06 starts
# mcp_server.py there. Envoy's is 26090, so both suites can run at the same time.
MCP_SERVER_PORT = 24090

# How the gateway renames a server's tools: `<server>-<tool>`
# (MCP_TOOL_PREFIX_SEPARATOR, litellm/proxy/_experimental/mcp_server/utils.py:53).
MCP_TOOL_PREFIX = "bench_hardware-"
