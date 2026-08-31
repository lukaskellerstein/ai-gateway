"""Unsloth Studio (port 8888) — the whole endpoint list for this engine.

ONE ENGINE RUNS AT A TIME. `seed.py` loads THIS file when GATEWAY_ENGINE is
`unsloth`, and these endpoints are then the entire vocabulary the MLflow gateway
serves. Its twin on the other gateway is `litellm/unsloth.yaml` — the same three
aliases, written again, because neither gateway reads the other.

THE MODELS ARE THE SAME WEIGHTS `lms-*` AND `ollama-*` SERVE. Change
GATEWAY_ENGINE, re-run tests/, and the only thing that moved is the engine.

FOUR DIFFERENCES FROM LMSTUDIO, each of which has bitten:

1. IT NEEDS A KEY. Unsloth answers `401 Not authenticated` on every route,
   `/v1/models` included. The key is personal, so it arrives from the shell and
   `.env` stays blank. A blank key makes `gateway.py` SKIP all three endpoints
   rather than store a blank secret — so the name 404s here while LiteLLM keeps
   it and 401s on 24000. The seed says which endpoints it skipped and why.

2. IT SERVES ONE MODEL AT A TIME, and that limit SPANS chat and the embedder.
   Calling `unsloth-embed` UNLOADS `unsloth-26b`, and the next chat call swaps it
   back — measured at 14 s cold and 4.4 s warm. A retrieval loop that alternates
   embed and chat on this engine pays a swap per call. `Settings > API > Model
   auto-switch` must be ON, or the second alias you call returns 400 "No model
   loaded".

3. IT TURNS REASONING ON where LMStudio does not. Verified 2026-08-27:
   `unsloth-26b` returns a reasoning block that `lms-26b` — the identical
   gemma-4-26b-a4b-qat — does not. At max_tokens 60 the reply came back EMPTY
   with finish_reason `length`, the whole budget spent thinking; at 1000 it
   answered in 117.

4. MLFLOW HAS NOWHERE TO STORE `max_tokens`, SO POINT 3 IS THE CALLER'S PROBLEM.
   A caller on 25000 must send it, and keep it generous. Prices, context windows
   and per-route timeouts are absent here for the same reason — they live in
   `litellm/unsloth.yaml` and only there.

`GET /v1/status` on 8888 is this engine's truth, and it needs the key too.
"""

from __future__ import annotations

from gateway import Endpoint, env

UNSLOTH = env("UNSLOTH_API_BASE", "http://host.containers.internal:8888/v1")
UNSLOTH_KEY = env("UNSLOTH_API_KEY")  # required; a blank key skips every endpoint below

ENDPOINTS = [
    # `lms-4b`'s twin: Gemma 4 E4B, the small chat route, tools and vision working.
    Endpoint(
        name="unsloth-4b",
        provider="openai",
        model="unsloth/gemma-4-E4B-it-qat-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
    # `lms-26b`'s twin: the same gemma-4-26b-a4b-qat weights on a different engine.
    # This pair is the cleanest engine comparison in the repo — identical build,
    # identical model, so only the engine moves.
    Endpoint(
        name="unsloth-26b",
        provider="openai",
        model="unsloth/gemma-4-26B-A4B-it-qat-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
    # The Q8_0 build of the same nomic v1.5 the other local engines serve — more
    # fidelity per vector, and NOT interchangeable with theirs. `lms-embed` is
    # Q4_K_M, `ollama-embed` is F16, `openai-embed` is a different model at 1536
    # dims. See the note in lms.py.
    #
    # REMEMBER THE ONE-MODEL LIMIT: calling this evicts whichever chat model is
    # loaded, and the next chat call swaps it back.
    Endpoint(
        name="unsloth-embed",
        provider="openai",
        model="second-state/Nomic-embed-text-v1.5-Embedding-GGUF",
        secret="unsloth",
        api_base=UNSLOTH,
        api_key=UNSLOTH_KEY,
    ),
]
