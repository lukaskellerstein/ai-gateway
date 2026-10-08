"""How this folder calls the gateway — THE ONE FILE TO EDIT WHEN YOU COPY IT. ENVOY.

Every other file in this folder is byte-identical to the same folder in
../../../litellm/tests, and none of them names a port, a key or a model. They read
this file. So to use this folder in another project: copy it, edit this file.

WHAT IS DIFFERENT ABOUT ENVOY is one function, `anthropic_alias()` below. Envoy
serves /anthropic/v1/messages by TRANSLATING Anthropic -> OpenAI onto the engine's
OpenAI schema, and that translation cannot carry an agent conversation. The reason
is not the gateway:

    `thinking` blocks. Envoy builds one into every reply out of the engine's
    `reasoning_content`. Claude Code stores the reply and sends it back on the next
    turn, the translator passes the block straight into the OpenAI body, and the
    ENGINE rejects it —

        400 messages.N.content.str: Input should be a valid string

    which reads like "content must be a string" and means "no branch of the content
    union matched". Measured 2026-09-04 DIRECT ON THE ENGINE, port 8888, with no
    gateway in the path at all: byte-identical error. Unsloth, LMStudio and Ollama
    all reject it, because an OpenAI `content` part may only be `text` or
    `image_url`.

    It was intermittent, which is worse than broken: the engine emits
    `reasoning_content` on some replies and not others, so a one-shot usually passed
    and an agent run failed about one time in five.

THE CURE IS THE `-anthropic` PASS-THROUGH ALIAS, and it is already in
../../config/<engine>.yaml. It points at an `AIServiceBackend` whose schema is
`Anthropic`, so the body reaches the engine UNTRANSLATED. All three local engines
serve POST /v1/messages themselves — verified 2026-09-04, 200 from each — so there
is nothing to bridge and no block to mangle. `anthropic_alias()` resolves the
caller's alias to that route and REFUSES TO RUN without it, because a run that
silently used the translated path would go red at random later.

`MAX_THINKING_TOKENS=0` USED TO BE REQUIRED HERE AND NO LONGER IS. It existed to stop
`400 thinking.type` from the same translator; on the pass-through path the engine
accepts Claude Code's `thinking` field as sent. Verified 2026-09-04: a multi-turn
session with the variable unset now completes.

Standard library only: it holds facts about the gateway, never client code.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

NAME = "envoy"

# 26000 is the data plane. The admin server on 26064 answers `/health` seconds before
# 26000 accepts a connection, so nothing here probes it.
ROOT_URL = "http://localhost:26000"

# The OpenAI surface: 07_thinking.py's baseline and the benchmark's warm-up.
BASE_URL = f"{ROOT_URL}/v1"

# THE ANTHROPIC SURFACE. The path is /anthropic/v1/messages, so the base is ROOT +
# "/anthropic" — the CLI appends /v1/messages itself.
ANTHROPIC_BASE_URL = f"{ROOT_URL}/anthropic"

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller; the CLI still wants a
# token to send, so something harmless goes in it.
API_KEY = "no-key-needed"

# WHAT `run_all.py` PROBES BEFORE IT STARTS, and on Envoy it is the DATA PLANE. aigw's
# admin server on 26064 answers /health several seconds BEFORE the listener on 26000
# accepts a connection, so probing the admin port races the thing being tested and
# the first scenario then fails with a connection reset (measured 2026-09-04).
# /v1/models needs no key and only answers once 26000 is really up.
HEALTH_URL = f"{ROOT_URL}/v1/models"
START_HINT = "cd ../.. && podman compose up -d"

# Callers name an alias, never a model. `lms-gemma4-e4b` is served by the `lms`,
# `all` and `lukas` configs; any other alias is `--model` or AI_GATEWAY_MODEL.
MODEL = os.environ.get("AI_GATEWAY_MODEL") or "lms-gemma4-e4b"

# SEND THE THINKING LEVEL EVERY TIME. Qwen 3.8's template defaults to `xhigh`, where one
# agent step took 693 s and answered nothing (2026-09-30), and Envoy cannot store a
# default of its own (envoyproxy/ai-gateway#1985). Unset, the CLI sends `xhigh` itself
# as `output_config.effort` (measured 2026-09-30). Gemma ignores it. An empty
# AI_GATEWAY_REASONING_EFFORT sends none.
REASONING_EFFORT = os.environ.get("AI_GATEWAY_REASONING_EFFORT", "medium") or None

# A local engine can read a long prompt for minutes before its first token.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE CEILING EVERY OPENAI REQUEST MUST CARRY HERE. An AIGatewayRoute stores no token
# limit: with none sent, one prompt ran to 13946 tokens on Envoy where LiteLLM stopped
# at its route's 4096 (2026-09-04). 8192 is what LiteLLM's Unsloth and Ollama routes
# store. 2048 was too low for a model that thinks: Gemma 4 26B on Unsloth spent all of
# it thinking on run_benchmark.py's third turn and never answered (2026-09-30). The CLI
# sends its own `max_tokens` on every Anthropic request.
MAX_TOKENS = 8192

# WHAT THE `claude` CLI IS STARTED WITH. The SDK spawns it and it inherits this
# process's environment, so common.py copies these into os.environ BEFORE the first
# scenario runs; set later, they change nothing. It also REMOVES ANTHROPIC_API_KEY,
# which would otherwise send the prompt to api.anthropic.com.
CLI_ENVIRONMENT = {
    "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL,
    # The placeholder above: Envoy checks no caller.
    "ANTHROPIC_AUTH_TOKEN": API_KEY,
    # The CLI's own request timeout. Its default hangs up while a local engine is still
    # reading the prompt, and then the route's `request: 60m` is wasted.
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
# own per session — a session title, carrying the whole first message (2685 tokens in
# run_benchmark.py) — beside the first request. Through the pass-through alias LMStudio
# wrote 2852 and then 3927 tokens for it, and the first request waited 38 s and 52 s
# for its first token, against 2.75 s with the variable set (2026-09-30). It also
# changes the prompt the conversation sends (no environment block, another `Read`
# description), so it is a choice for whoever copies this file, not a default.

# ENVOY PASSES THE ENGINE'S REASONING THROUGH, because the `-anthropic` alias does not
# translate: the engine's own `/v1/messages` reply reaches the caller as it was
# written. Verified 2026-09-04 on all three local engines — unsloth 8 runs in 8,
# LMStudio 1033 characters, Ollama 891.
THINKING_REACHES_CLIENT = True

# PRINTED BY 07_thinking.py ON EVERY RUN. Nothing to warn about on this gateway — the
# pass-through alias carries the engine's reasoning whole.
THINKING_NOTE = ""


def body_extras(alias: str) -> dict:
    """What every OpenAI request body must carry on this gateway: a ceiling and the level.

    OpenAI's newer models REJECT `max_tokens` — `400 ... Use 'max_completion_tokens'
    instead` (2026-09-05) — and Envoy passes the body through untouched, so the caller
    names the field the upstream accepts.
    """
    ceiling = "max_completion_tokens" if alias.startswith("openai-") else "max_tokens"
    level = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}
    return {ceiling: MAX_TOKENS, **level}


def anthropic_alias(alias: str) -> str:
    """The alias that reaches the engine UNTRANSLATED — see the note at the top.

    ASKED AT RUNTIME, NEVER ASSUMED. ../../config/<engine>.yaml is edited by hand and
    the answer is different per engine, so the gateway is the only honest source.

    A MISSING ROUTE IS A HARD FAILURE, not a skip. Every local engine can serve one, so
    its absence is an unfinished config file and the message says which file and what
    to add.
    """
    if alias.endswith("-anthropic"):
        return alias

    candidate = f"{alias}-anthropic"
    try:
        with urllib.request.urlopen(f"{ROOT_URL}/v1/models", timeout=10) as response:
            listed = {row["id"] for row in json.load(response).get("data", [])}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"cannot list the aliases on {ROOT_URL}/v1/models: {error}") from error

    if candidate in listed:
        return candidate

    raise SystemExit(
        f"{candidate!r} is not among the aliases this gateway serves.\n"
        f"  The Claude Agent SDK cannot run on {alias!r} alone. Envoy translates\n"
        "  Anthropic -> OpenAI for that route, and the engine rejects the `thinking`\n"
        "  blocks the replies carry — 400 messages.N.content.str, intermittently.\n"
        f"  Add a {candidate!r} rule to ../../config/<engine>.yaml pointing at an\n"
        "  `Anthropic`-schema AIServiceBackend. config/unsloth.yaml is the worked\n"
        "  example, and README.md § The pass-through alias explains the shape."
    )

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
