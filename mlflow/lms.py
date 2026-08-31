"""LMStudio (port 1234) — the whole endpoint list for this engine.

ONE ENGINE RUNS AT A TIME. `seed.py` loads THIS file when GATEWAY_ENGINE is `lms`,
and these endpoints are then the entire vocabulary the MLflow gateway serves. Its
twin on the other gateway is `litellm/lms.yaml` — the same three aliases, written
again, because neither gateway reads the other.

THE PRICE OF THAT INDEPENDENCE: an alias is two edits, one per gateway. Add it
here and not there, or there and not here, and the name answers on one port and
404s on the other with nothing in either log to say why.

WHAT MLFLOW HAS NO PLACE FOR, so it is absent here rather than faked: prices,
`max_tokens`, context windows and per-route timeouts. Those live in
`litellm/lms.yaml` and only there. MLflow carries one global timeout, set as
MLFLOW_GATEWAY_ROUTE_TIMEOUT_SECONDS in compose.yml.

THE MISSING `max_tokens` IS THE ONE THAT BITES. A chat endpoint here can emit a
reasoning block, and reasoning tokens come out of the SAME allowance as the reply
— so a request whose ceiling is too low returns EMPTY content with finish_reason
"length" and raises no error at all. A CALLER ON 25000 MUST SEND `max_tokens`
ITSELF, and keep it generous.

LMSTUDIO MUST BE HAND-LOADED, or a JIT load silently gives you 8192 context with
a 1 h TTL. `lms ps --json` is the truth, not the UI:

    lms load google/gemma-4-e4b         --context-length 131072 --parallel 1 --gpu max
    lms load google/gemma-4-26b-a4b-qat --context-length 262144 --parallel 1 --gpu max
"""

from __future__ import annotations

from gateway import Endpoint, env

LM_STUDIO = env("LM_STUDIO_API_BASE", "http://host.containers.internal:1234/v1")
LM_STUDIO_KEY = env("LM_STUDIO_API_KEY", "sk-lmstudio")  # LMStudio accepts any string

ENDPOINTS = [
    # Gemma 4 E4B — the small chat route. Tools AND vision both work, which is why
    # tests/ defaults to this row: one loaded model covers all three scenarios.
    Endpoint(
        name="lms-4b",
        provider="openai",
        model="google/gemma-4-e4b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # Gemma 4 26B A4B QAT — the large chat route. A mixture of experts with ~4B
    # active per token, so it answers at roughly small-model speed. `unsloth-26b`,
    # `ollama-26b` and `openrouter-26b` are the same weights on other engines:
    # change GATEWAY_ENGINE and re-run tests/ to compare them.
    #
    # It does NOT emit a reasoning block, while `unsloth-26b` on the identical
    # weights does (verified 2026-08-27). Thinking is decided per MODEL AND ENGINE.
    Endpoint(
        name="lms-26b",
        provider="openai",
        model="google/gemma-4-26b-a4b-qat",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # nomic-embed-text v1.5 at 768 dimensions, the Q4_K_M build at 84 MB.
    #
    # EMBEDDING VECTORS DO NOT MIX ACROSS MODELS OR BUILDS. Every engine serves the
    # same nomic v1.5 at 768 dims in a DIFFERENT build — this is Q4_K_M,
    # `unsloth-embed` is Q8_0, `ollama-embed` is F16 (measured 2026-08-31) — and
    # `openai-embed` is a different model at 1536 dims entirely. An index built
    # with one alias and queried with another returns quietly worse neighbours and
    # never errors. Record which alias built each index.
    Endpoint(
        name="lms-embed",
        provider="openai",
        model="text-embedding-nomic-embed-text-v1.5",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
]
