"""Ollama (port 11434) — the whole endpoint list for this engine.

ONE ENGINE RUNS AT A TIME. `seed.py` loads THIS file when GATEWAY_ENGINE is
`ollama`, and these endpoints are then the entire vocabulary the MLflow gateway
serves. Its twin on the other gateway is `litellm/ollama.yaml` — the same three
aliases, written again, because neither gateway reads the other.

THE LEAST FUSSY ENGINE: it loads on demand, holds several models at once, and
needs no key at all. Four notes anyway:

1. THE KEY IS IGNORED, AND ONE IS SET ANYWAY. Ollama never reads Authorization.
   `sk-ollama` is here only because `gateway.py` skips any endpoint whose key is
   empty, and a skipped endpoint is an alias that silently never reaches MLflow.

2. IT EVICTS AN IDLE MODEL AFTER 5 MINUTES by default, so the second call of a
   session can be as slow as the first. `ollama ps` says what is resident;
   `ollama list` only says what is on disk. OLLAMA_KEEP_ALIVE changes it.

3. THE BUILD IS NOT ITS TWINS' BUILD. These tags are Q4_K_M — quantised AFTER
   training — while the LMStudio and Unsloth routes are QAT, trained around the
   quantisation. So an `ollama-*` route against its twin measures ENGINE AND
   BUILD together. Say which you are claiming.

4. IT THINKS ON WEIGHTS ITS LMSTUDIO TWIN DOES NOT, and MLflow has nowhere to
   store `max_tokens` — so a caller on 25000 must send one, generously. A ceiling
   set too low returns EMPTY content with finish_reason "length" and no error.
   Prices, context windows and per-route timeouts are absent here for the same
   reason: they live in `litellm/ollama.yaml` and only there.

Pull what this file names before calling it:

    ollama pull gemma4:e4b && ollama pull gemma4:26b && ollama pull nomic-embed-text
"""

from __future__ import annotations

from gateway import Endpoint, env

OLLAMA = env("OLLAMA_API_BASE", "http://host.containers.internal:11434/v1")
OLLAMA_KEY = "sk-ollama"  # ignored by Ollama; see note 1

ENDPOINTS = [
    # `lms-4b`'s twin: Gemma 4 E4B, the small chat route, tools and vision working.
    # `gemma4:latest` is the SAME model — one digest, two tags — but `latest` moves
    # on the next pull, so the explicit `:e4b` is used.
    Endpoint(
        name="ollama-4b",
        provider="openai",
        model="gemma4:e4b",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
    # `lms-26b`'s twin: the 26B mixture of experts, the large chat route. Q4_K_M
    # here against QAT on the other two local engines, so this pair moves the build
    # as well as the engine.
    Endpoint(
        name="ollama-26b",
        provider="openai",
        model="gemma4:26b",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
    # The same nomic-embed-text v1.5 MODEL the other local engines serve, at 768
    # dimensions on a 2048 window (verified 2026-08-27 from GET /api/show) — but
    # the F16 build at 274 MB, against `lms-embed`'s Q4_K_M at 84 MB and
    # `unsloth-embed`'s Q8_0 at 146 MB (measured 2026-08-31). It is the most
    # accurate of the three and the heaviest. VECTORS DO NOT MIX ACROSS BUILDS —
    # see the note in lms.py.
    Endpoint(
        name="ollama-embed",
        provider="openai",
        model="nomic-embed-text",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
]
