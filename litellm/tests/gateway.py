"""Where this gateway is, and which alias to call. LITELLM ONLY.

EVERY FOLDER UNDER tests/ IMPORTS THIS ONE FILE. There are seven of them, each its
own uv project with its own dependencies, and the three facts they all need — the
base URL, the key, the alias — must not be written down seven times. An alias
copied into seven files is seven places to forget when `GATEWAY_ENGINE` changes,
and nothing would report the ones you missed.

IT IMPORTS NOTHING BUT THE STANDARD LIBRARY, and that is a hard requirement rather
than a style choice: it has to import cleanly inside `1_http_client`'s venv, which
has no dependencies at all. That is why `../.env` is parsed by hand below instead
of with `python-dotenv`.

IT READS ONLY THIS PROJECT'S OWN FILES. Nothing here looks at ../../envoy. The
compose projects were split on 2026-09-03 so that any one of them can be deleted
without touching the others — `mlflow/` was, on 2026-09-04 — and a test helper that
reached across would undo exactly that.

    from gateway import ALIAS, API_KEY, BASE_URL

Add the two lines above to a new folder and it is wired up.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# This project's own .env — NOT a repo-root one, which no longer exists
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_ROOT = Path(__file__).resolve().parent


def _dotenv_value(name: str, default: str = "") -> str:
    """One value, with the SHELL WINNING over the file.

    That order is the design, and it is the same order `compose.yml` resolves in:
    `~/Projects/.envrc` exports the real provider keys, so the key lines in `.env`
    stay blank and no second plaintext copy exists to go stale after a rotation.

    A hand-rolled parser rather than `python-dotenv` because this module must
    import with no dependencies installed at all — see the note at the top.
    """
    from_shell = os.environ.get(name)
    if from_shell:
        return from_shell

    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("\"'")
    return default


# ---------------------------------------------------------------------------
# Where this gateway answers
# ---------------------------------------------------------------------------

NAME = "litellm"

# 24000, not 4000. Two other stacks hold ports on this machine and the failure the
# 2xxxx band avoids is not a loud bind error but the silent one: a probe against
# localhost:4000 that a DIFFERENT project's gateway answers, going green.
ROOT_URL = "http://localhost:24000"

# The OpenAI-compatible surface. `1_http_client` through `4_deepagents` and
# `7_opencode_sdk` all speak to this one.
BASE_URL = f"{ROOT_URL}/v1"

# THE ANTHROPIC SURFACE, for `5_claude_agent_sdk`. LiteLLM serves /v1/messages
# alongside the OpenAI routes, so the SDK's ANTHROPIC_BASE_URL is the ROOT — the
# CLI appends /v1/messages itself. `None` here would mean the gateway has no
# Anthropic route at all, and folder 5 would then refuse to run.
ANTHROPIC_BASE_URL = ROOT_URL

# THE RESPONSES SURFACE, for `6_codex_sdk`. Codex speaks the Responses API and
# nothing else — its `WireApi` enum has exactly one variant since the `chat` one
# was removed — so a gateway without /v1/responses cannot run Codex at all.
# Verified 2026-09-04: POST /v1/responses -> 200 on this gateway.
RESPONSES_BASE_URL = BASE_URL

# The master key mints virtual keys and has no ceiling, so AI_GATEWAY_KEY (a capped
# key from /key/generate) is preferred when the shell carries one.
API_KEY = (
    os.environ.get("AI_GATEWAY_KEY")
    or _dotenv_value("LITELLM_MASTER_KEY")
    or "sk-litellm-master"
)

# ---------------------------------------------------------------------------
# Which alias to call
# ---------------------------------------------------------------------------

# THE DEFAULT ALIAS FOLLOWS THE ENGINE THIS PROJECT IS SERVING. `GATEWAY_ENGINE` in
# ../.env names ONE engine, and the aliases of every other engine are not in the
# running config at all — so a fixed `lms-4b` default would fail with "model not
# found" on a perfectly healthy gateway.
#
# The chosen names are the small chat route on each engine: the one alias per engine
# that is both VISION- and TOOL-capable, which is what the agent folders need from a
# single loaded model.
#
# `openai` MAPPED TO NOTHING UNTIL 2026-09-05, on the belief that gpt-5.4-mini has
# no vision. IT DOES. `2_openai_client/03_multimodal.py` passes against it 4/4 —
# and that scenario sends a real base64 PNG and demands both "red" and a
# round-shape word back, so a model ignoring the image cannot pass it.
#
# The false claim cost more than a wrong comment: the `None` made gateway.py raise
# at IMPORT time for this engine, so EVERY folder died in 0.0 s and the openai
# engine could not be tested at all.
DEFAULT_MODEL_BY_ENGINE = {
    "lms": "lms-4b",
    "unsloth": "unsloth-4b",
    "ollama": "ollama-4b",
    "openrouter": "openrouter-26b",
    "openai": "openai-mini",
}

ENGINE = _dotenv_value("GATEWAY_ENGINE", "lms").strip()


def _default_alias() -> str:
    """The alias for whichever engine this project's `.env` names.

    AN UNRECOGNISED ENGINE IS AN ERROR, NOT A FALLBACK. Quietly defaulting to
    `lms-4b` was worse than failing: it produced "Invalid model name passed in
    model=lms-4b" from a perfectly healthy gateway serving a different engine,
    which reads as a broken gateway rather than a stale `.env`.
    """
    if ENGINE not in DEFAULT_MODEL_BY_ENGINE:
        raise SystemExit(
            f"GATEWAY_ENGINE is {ENGINE!r}, which is not an engine this project serves.\n"
            f"  It must be one of: {', '.join(DEFAULT_MODEL_BY_ENGINE)}.\n"
            "  One engine at a time — a list is not accepted.\n"
            "  Fix ../.env, or pass --model to choose an alias directly."
        )
    return DEFAULT_MODEL_BY_ENGINE[ENGINE]


ALIAS = os.environ.get("AI_GATEWAY_TEST_MODEL") or _default_alias()

# ---------------------------------------------------------------------------
# How to call it
# ---------------------------------------------------------------------------

# LMStudio prompt processing measures ~100 tok/s on this machine, so a large prompt
# needs minutes before its first token — the same fact that puts `timeout: 3600` on
# every chat route in ../config/. Retries are off everywhere here because a test
# that silently retries hides the failure it exists to find.
REQUEST_TIMEOUT_SECONDS = 3600.0

# The allowance a caller sends when it sends one. It has to clear a REASONING block:
# both `unsloth-*` chat routes, both `ollama-*` ones and `lms-4b` spend this budget
# on thinking before they write a word. A model that runs out mid-thought returns
# EMPTY content with `finish_reason: "length"` and raises nothing, which reads as a
# broken alias. 150 was not enough for a one-sentence answer about an image
# (verified 2026-08-27 on `unsloth-26b`).
MAX_TOKENS = 2048

# WHAT A CALLER MUST ADD TO EVERY REQUEST, and it is EMPTY on this gateway.
#
# LiteLLM stores a `max_tokens` on the route and every local route in ../config/
# carries one, so a caller who sends none still gets a bounded reply. Measured
# 2026-09-03, `lms-4b`, one "count from 1 to 3000" prompt with NO `max_tokens`:
# finish_reason "length" at 4095 completion tokens — the route's stored 4096.
#
# The two sibling gateways store nothing and their copies of this file carry
# `{"max_tokens": MAX_TOKENS}` instead. A script that spreads `**BODY_EXTRAS` is
# therefore correct on all three without knowing which one it is talking to.
BODY_EXTRAS: dict = {}
