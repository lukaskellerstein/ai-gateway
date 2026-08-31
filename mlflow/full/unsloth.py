"""Unsloth Studio (port 8888) — the FULL endpoints. Four: three chat models, one embedder.

This file declares `ENDPOINTS` and nothing else. `seed.py` loads it when
GATEWAY_MODELS is `full` and GATEWAY_ENGINE is `unsloth` or `all`. Its twin on the
other gateway is `litellm/full/unsloth.yaml` — the same four aliases, written
again, because neither gateway reads the other.

THE SECOND LOCAL ENGINE: same GPU, same weights, different engine. `unsloth-31b`
is `lms-31b`'s twin, `unsloth-26b` is `lms-26b`'s and `unsloth-4b` is `lms-4b`'s,
so a caller can put the two engines side by side without changing anything but
the alias. That comparison is the only reason these exist.

FOUR differences from every LMStudio route, each of which has bitten:

1. IT NEEDS A KEY. Unsloth answers `401 Not authenticated` on every route,
   `/v1/models` included. The key is personal, so it arrives from the shell and
   `.env` stays blank. A blank key makes `gateway.py` skip all four endpoints
   below, and MLflow then 404s on names LiteLLM still 401s on.
2. THE MODEL ID CARRIES A SLASH: `unsloth/gemma-4-31B-it-qat-GGUF` is the
   HuggingFace repo id, and it is what `GET /v1/models` returns.
3. NOTHING LOADS ON DEMAND UNLESS AUTO-SWITCH IS ON. Unsloth serves ONE model at
   a time. With `Settings > API > Model auto-switch` off, a request for a model
   that is not loaded returns 400 `No model loaded` — it does not queue and it
   does not load. With it on, a call to another alias here UNLOADS the current
   one and reads ~18 GB from disk first.
4. THESE WEIGHTS THINK HERE AND DO NOT THINK ON THEIR LMSTUDIO TWIN. Verified
   2026-08-27: `unsloth-26b` returns a `reasoning_content` block that `lms-26b` —
   the identical gemma-4-26b-a4b-qat — does not. At max_tokens 60 the reply was
   EMPTY with finish_reason `length`, the whole budget spent thinking; at 1000 it
   answered in 117. That is a fact about THESE WEIGHTS, not about the engines —
   `lms-4b` reasons on LMStudio too. MLflow has nowhere to store max_tokens, so
   the caller must send it.
"""

from __future__ import annotations

from gateway import Endpoint, env

UNSLOTH = env("UNSLOTH_API_BASE", "http://host.containers.internal:8888/v1")
UNSLOTH_KEY = env("UNSLOTH_API_KEY")

ENDPOINTS = [
    Endpoint(
        name="unsloth-31b",
        provider="openai",
        model="unsloth/gemma-4-31B-it-qat-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
    Endpoint(
        name="unsloth-26b",
        provider="openai",
        model="unsloth/gemma-4-26B-A4B-it-qat-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
    # `lms-4b`'s twin on the second engine, and the third leg of the E4B row — the
    # one size this repo carries on all three engines, which is why the starter
    # list uses it. QAT here, like every LMStudio route and unlike Ollama's plain
    # `gemma4:e4b` tag, so `unsloth-4b` against `lms-4b` isolates the engine
    # cleanly while either against `ollama-4b` also moves the quantisation.
    Endpoint(
        name="unsloth-4b",
        provider="openai",
        model="unsloth/gemma-4-E4B-it-qat-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
    # The embedding role on the second engine — the SAME nomic build as
    # `lms-embed-hq`, so that pair isolates the engine and nothing else.
    #
    # ONE MODEL AT A TIME SPANS CHAT AND EMBEDDINGS, and this is the trap. Calling
    # this alias UNLOADS `unsloth-26b` or `unsloth-31b`, and the next chat call
    # swaps it back — verified 2026-08-27. So a retrieval loop that alternates
    # embed and chat on THIS engine pays a model swap every single call. LMStudio
    # and Ollama both hold the embedder alongside a chat model and do not. Use
    # lms-embed or ollama-embed inside such a loop.
    Endpoint(
        name="unsloth-embed",
        provider="openai",
        model="second-state/Nomic-embed-text-v1.5-Embedding-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
]
