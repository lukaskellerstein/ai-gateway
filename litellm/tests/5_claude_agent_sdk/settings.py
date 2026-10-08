"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. LITELLM.

Every other file in this folder is byte-identical to the same folder in
../../../envoy/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

WHAT IS DIFFERENT ABOUT LITELLM is one function, `anthropic_alias()` below, and it
returns the alias unchanged, because there is nothing to work around. LiteLLM serves
POST /v1/messages beside its OpenAI routes and carries an agent conversation on the
ordinary alias. Envoy cannot: it translates Anthropic -> OpenAI onto the engine's
OpenAI schema and passes the reply's `thinking` blocks straight into the OpenAI
body, where a `content` part may only be `text` or `image_url`, and the engine
answers `400 messages.N.content.str`. Its copy of this file resolves a second,
`Anthropic`-schema alias instead. LiteLLM needs none — verified 2026-09-04, a
multi-turn request carrying a `thinking` block returned 200 on the plain
`unsloth-gemma4-e4b`.

Standard library only: it holds facts about the gateway, never client code.
"""

from __future__ import annotations

import os

NAME = "litellm"

# 24000, not 4000: the 2xxxx band keeps a probe from reaching a different project's
# gateway and going green.
ROOT_URL = "http://localhost:24000"

# The OpenAI surface: 07_thinking.py's baseline and the benchmark's warm-up.
BASE_URL = f"{ROOT_URL}/v1"

# THE ANTHROPIC SURFACE, and it is the ROOT: LiteLLM serves /v1/messages beside its
# OpenAI routes, and the CLI appends /v1/messages itself.
ANTHROPIC_BASE_URL = ROOT_URL

# A virtual key from /key/generate — this laptop exports one from ~/Projects/.envrc.
# The master key is the fallback, and it has no ceiling.
API_KEY = os.environ.get("AI_GATEWAY_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# WHAT `run_all.py` PROBES BEFORE IT STARTS. Liveliness and not readiness on purpose:
# these scenarios need the proxy to answer, not the database to be attached, and a
# suite that refuses to run over a missing database would hide the fact that
# completions keep working without one.
HEALTH_URL = f"{ROOT_URL}/health/liveliness"
START_HINT = "cd ../.. && podman compose up -d"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME. Qwen 3.8's template defaults to `xhigh`, where one
# agent step took 693 s and answered nothing (2026-09-30). Unset, the CLI sends `xhigh`
# itself as `output_config.effort` (measured 2026-09-30); LiteLLM stores `medium` on its
# Qwen routes, and a caller that states the level does not depend on which one wins.
# Gemma ignores it. An empty AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# WHAT THE `claude` CLI IS STARTED WITH. The SDK spawns it and it inherits this
# process's environment, so common.py copies these into os.environ BEFORE the first
# scenario runs; set later, they change nothing. It also REMOVES ANTHROPIC_API_KEY,
# which would otherwise send the prompt to api.anthropic.com.
CLI_ENVIRONMENT = {
    "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL,
    # Sent as `Authorization: Bearer`, which is what LiteLLM checks.
    "ANTHROPIC_AUTH_TOKEN": API_KEY,
    # The CLI's own request timeout. Its default hangs up while a local engine is still
    # reading the prompt, and then the gateway's `timeout: 3600` is wasted.
    "API_TIMEOUT_MS": str(int(REQUEST_TIMEOUT_SECONDS * 1000)),
    # THE TWO THAT KEEP THE PROMPT CACHE WORKING. A local engine reuses only the PREFIX
    # a prompt shares with the one before it. As shipped, the CLI writes a new
    # `<total_tokens>` line into its system prompt after every tool result — in front
    # of the tool list and every message — and puts a per-conversation billing suffix
    # at the very top. Measured with one live session per agent on LMStudio, both gateways,
    # 2026-09-30: the last turn reused 22% (Gemma 4 26B) and 0% (Qwen 3.8 27B) as
    # shipped, 76-93% with both set.
    "CLAUDE_CODE_TOTAL_TOKENS_REMINDER": "off",
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    # The level, in the CLI's own words — see REASONING_EFFORT.
    **({"CLAUDE_CODE_EFFORT_LEVEL": REASONING_EFFORT} if REASONING_EFFORT else {}),
}

# NOT SET: CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1. The CLI sends one request of its
# own per session — a session title, carrying the whole first message (2684 tokens in
# run_benchmark.py) — beside the first request. Here it costs little: LMStudio answered it
# in 9 tokens (2026-09-30). The variable stops it, but it also changes the prompt the
# conversation sends (no environment block, another `Read` description), so it is a
# choice for whoever copies this file, not a default.

# REASONING REACHES THE CALLER ON EVERY ENGINE, and it took a config line in
# ../../config/settings.yaml to make that true. It was a PER-ENGINE table until
# 2026-09-05 — unsloth False, lms and ollama True — and the table was a symptom, not a
# fact about engines.
#
# WHAT IT ACTUALLY WAS: `/v1/messages` picks its upstream route by PROVIDER, and
# `_RESPONSES_API_PROVIDERS = frozenset({"openai"})` sends anything on the `openai/`
# provider through the RESPONSES API bridge, which does not carry `reasoning_content`.
# Our engines split exactly on that line — `lms-*` is `lm_studio/` and never went
# through the bridge, `ollama-*` and `unsloth-*` are `openai/` and did.
# `use_chat_completions_url_for_anthropic_messages: true` forces the chat-completions
# path, where the adapter already falls back to `reasoning_content`. Measured on
# 1.99.1, unsloth-gemma4-e4b, after the flag: 6 streaming runs out of 6 carried
# thinking, against 0 out of 5 before.
#
# IT WAS NOT THE TWO ISSUES THAT WERE CLOSED. BerriAI/litellm#29518 and #27946 had
# both closed BEFORE any of this was measured, and neither fixes it; #29518's fix
# already shipped in 1.95.0. Do not read their closure as the cure.
THINKING_REACHES_CLIENT = True

# PRINTED BY 07_thinking.py ON EVERY RUN. Empty — nothing left to warn about.
THINKING_NOTE = ""


def body_extras(alias: str) -> dict:
    """What every OpenAI request body must carry on this gateway.

    Only the level here: LiteLLM stores a `max_tokens` on every local route, so a
    caller that sends none still gets a bounded reply.
    """
    return {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}


def anthropic_alias(alias: str) -> str:
    """The alias itself. LiteLLM speaks Anthropic on every route it serves.

    IT EXISTS SO THE SCENARIOS DO NOT HAVE TO KNOW THAT. Envoy's copy of this function
    resolves a second, pass-through alias and refuses to run without it; the scenarios
    call the same name and never learn which gateway answered.
    """
    return alias

# THE GATEWAY'S MCP ENDPOINT, and the ONE address 08_gateway_mcp.py gives the agent.
# What answers behind it is ../../config/settings.yaml § mcp_servers.
MCP_URL = f"{ROOT_URL}/mcp"

# LiteLLM checks the caller on /mcp as on every route, and `x-litellm-api-key` is the
# header it always reads as its own key there (auth/user_api_key_auth_mcp.py:416).
MCP_HEADERS = {"x-litellm-api-key": f"Bearer {API_KEY}"}

# The port ../../config/settings.yaml expects `bench_hardware` on, so 08 starts
# mcp_server.py there. Envoy's is 26090, so both suites can run at the same time.
MCP_SERVER_PORT = 24090

# How the gateway renames a server's tools: `<server>-<tool>`
# (MCP_TOOL_PREFIX_SEPARATOR, litellm/proxy/_experimental/mcp_server/utils.py:53).
MCP_TOOL_PREFIX = "bench_hardware-"
