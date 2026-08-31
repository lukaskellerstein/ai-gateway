"""Unsloth Studio (port 8888) — the STARTER endpoints. Two: one chat model, one embedder.

This file declares `ENDPOINTS` and nothing else. `seed.py` loads it when
GATEWAY_MODELS is `starter` and GATEWAY_ENGINE is `unsloth` or `all`. Its twin on
the other gateway is `litellm/starter/unsloth.yaml` — the same two aliases,
written again, because neither gateway reads the other.

IT REQUIRES A KEY, unlike the other two engines: every route answers 401 without
one, `/v1/models` included. The key is personal, so it arrives from the shell and
the line in `.env` stays blank. A BLANK KEY FAILS TWICE, DIFFERENTLY: `gateway.py`
skips both endpoints below with "no API key in the environment" and MLflow never
gets them, while LiteLLM keeps the aliases and 401s at call time — so the same
name 404s on 25000 and 401s on 24000.

The model ids carry their own slash: `unsloth/gemma-4-E4B-it-qat-GGUF` is the
HuggingFace repo id, and it is what `GET /v1/models` returns.

UNSLOTH SERVES ONE MODEL AT A TIME, and that limit spans chat and the embedder:
calling `unsloth-embed` unloads `unsloth-4b`, and the next chat call swaps it
back. `Settings > API > Model auto-switch` must be ON or the second alias you
call returns 400 "No model loaded". Use `lms-embed` or `ollama-embed` inside a
retrieval loop.
"""

from __future__ import annotations

from gateway import Endpoint, env

UNSLOTH = env("UNSLOTH_API_BASE", "http://host.containers.internal:8888/v1")
UNSLOTH_KEY = env("UNSLOTH_API_KEY")

ENDPOINTS = [
    Endpoint(
        name="unsloth-4b",
        provider="openai",
        model="unsloth/gemma-4-E4B-it-qat-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
    # The Q8_0 build of the same nomic v1.5 the other two engines serve — more
    # fidelity per vector, and NOT interchangeable with theirs.
    Endpoint(
        name="unsloth-embed",
        provider="openai",
        model="second-state/Nomic-embed-text-v1.5-Embedding-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
]
