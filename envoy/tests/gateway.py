"""Where this gateway is, and which alias to call. ENVOY ONLY.

EVERY FOLDER UNDER tests/ IMPORTS THIS ONE FILE. There are seven of them, each its
own uv project with its own dependencies, and the three facts they all need — the
base URL, the key, the alias — must not be written down seven times. An alias
copied into seven files is seven places to forget when `GATEWAY_ENGINE` changes,
and nothing would report the ones you missed.

IT IMPORTS NOTHING BUT THE STANDARD LIBRARY, and that is a hard requirement rather
than a style choice: it has to import cleanly inside `1_http_client`'s venv, which
has no dependencies at all. That is why `../.env` is parsed by hand below instead
of with `python-dotenv`.

IT READS ONLY THIS PROJECT'S OWN FILES. Nothing here looks at ../../litellm. The
compose projects were split so that any one of them can be deleted without touching
the others — `mlflow/` was, on 2026-09-04 — and a test helper that reached across
would undo exactly that.

THIS GATEWAY IS NOT A COPY OF THE OTHER ONE: it serves the Responses API like
LiteLLM and translates the Anthropic API like LiteLLM, but it authenticates no
caller at all and echoes the upstream model id rather than the alias.

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

NAME = "envoy"

# 26000 is the DATA PLANE. 26064 below is the admin server, and the difference
# matters at startup: /health on 26064 goes green SECONDS BEFORE 26000 accepts a
# connection, so a probe there passes while the next call gets a connection reset.
ROOT_URL = "http://localhost:26000"
ADMIN_URL = "http://localhost:26064"

# The OpenAI-compatible surface.
BASE_URL = f"{ROOT_URL}/v1"

# THE ANTHROPIC SURFACE, for `5_claude_agent_sdk`. The path is /anthropic/v1/messages,
# so the SDK's ANTHROPIC_BASE_URL is ROOT + "/anthropic" — the CLI appends
# /v1/messages itself. Envoy TRANSLATES Anthropic onto the OpenAI backend rather
# than passing it through, which is where the extra environment variable that
# folder needs comes from.
ANTHROPIC_BASE_URL = f"{ROOT_URL}/anthropic"

# THE RESPONSES SURFACE, for `6_codex_sdk`. Codex speaks the Responses API and
# nothing else — its `WireApi` enum has exactly one variant since the `chat` one
# was removed. Verified 2026-09-04: POST /v1/responses -> 200 on this gateway.
RESPONSES_BASE_URL = BASE_URL

# A PLACEHOLDER, NOT A KEY. `aigw run` authenticates no caller of any kind — a
# bogus `Bearer sk-wrong` gets 200. The OpenAI client demands the argument, so
# something has to be here, and a name that says so beats a real-looking string.
# The key that DOES matter is the one the gateway sends UPSTREAM, out of a Secret
# in ../config/<engine>.yaml, and a caller never sees it.
API_KEY = "no-key-needed"

# ---------------------------------------------------------------------------
# Which alias to call
# ---------------------------------------------------------------------------

# THE DEFAULT ALIAS FOLLOWS THE ENGINE THIS PROJECT IS SERVING. `GATEWAY_ENGINE` in
# ../.env names ONE engine, and the aliases of every other engine have no
# AIGatewayRoute rule at all — so a fixed `lms-4b` default would 404 on a healthy
# gateway.
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
    `lms-4b` was worse than failing: an alias with no AIGatewayRoute rule gets a
    404 (verified 2026-09-04), which from a perfectly healthy gateway serving a
    different engine reads as a broken gateway rather than a stale `.env`.
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
# needs minutes before its first token — the same fact that sets `request: 60m` on
# both the route and the backend in ../config/<engine>.yaml. Retries are off
# everywhere here because a test that silently retries hides the failure it exists
# to find.
REQUEST_TIMEOUT_SECONDS = 3600.0

# THE ALLOWANCE EVERY CALLER SENDS, and on this gateway it is load-bearing — see
# BODY_EXTRAS below. It has to clear a REASONING block: both `unsloth-*` chat
# routes, both `ollama-*` ones and `lms-4b` spend this budget on thinking before
# they write a word. A model that runs out mid-thought returns EMPTY content with
# `finish_reason: "length"` and raises nothing, which reads as a broken alias. 150
# was not enough for a one-sentence answer about an image (verified 2026-08-27 on
# `unsloth-26b`).
#
# Raising it costs nothing when the model does not need it: generation stops at
# `stop`, not at the ceiling.
MAX_TOKENS = 2048

# WHAT A CALLER MUST ADD TO EVERY REQUEST, and here it is NOT OPTIONAL.
#
# Measured 2026-09-04, `lms-4b`, one "count from 1 to 3000" prompt sent with NO
# `max_tokens` in the body:
#
#   Envoy   26000   finish_reason "stop" at 13946 completion tokens — nothing
#                   bounded it; the model simply ran out of things to say
#   LiteLLM 24000   finish_reason "length" at 4095 — its route's stored 4096
#
# Same prompt, same alias, same weights: 3.4x the output and 3.4x the wait. The
# parameter behaves normally when it IS sent; what is missing is the DEFAULT — an
# AIGatewayRoute rule carries a request timeout but no token ceiling.
#
# AND THE PARAMETER IS NOT CALLED THE SAME THING EVERYWHERE. OpenAI's newer models
# REJECT `max_tokens` outright:
#
#   400 Unsupported parameter: 'max_tokens' is not supported with this model.
#       Use 'max_completion_tokens' instead.
#
# Measured 2026-09-05, `openai-mini`, all four `2_openai_client` scripts on 26000.
# LiteLLM renames it for you and never shows you this; **Envoy is a pass-through and
# does not**, so the caller has to send what the upstream actually accepts. That is
# a real difference in the CALLING CONTRACT, not a bug in either gateway, and it
# belongs here — the one file per project allowed to know such things.
#
# Keyed off the alias rather than a version number because the alias is what this
# project routes on, and `openai-*` is exactly the set that reaches api.openai.com.
BODY_EXTRAS: dict = (
    {"max_completion_tokens": MAX_TOKENS}
    if ALIAS.startswith("openai-")
    else {"max_tokens": MAX_TOKENS}
)
