"""Ollama (port 11434) — the STARTER endpoints. Two: one chat model, one embedder.

This file declares `ENDPOINTS` and nothing else. `seed.py` loads it when
GATEWAY_MODELS is `starter` and GATEWAY_ENGINE is `ollama` or `all`. Its twin on
the other gateway is `litellm/starter/ollama.yaml` — the same two aliases,
written again, because neither gateway reads the other.

The least fussy engine: it loads on demand, holds several models at once, and
needs no key at all. Three notes anyway:

  THE KEY IS IGNORED, AND ONE IS SET ANYWAY. Ollama never reads Authorization.
  `sk-ollama` is here only because `gateway.py` skips any endpoint whose key is
  empty, and a skipped endpoint is an alias that silently never reaches MLflow.

  IT EVICTS AN IDLE MODEL AFTER 5 MINUTES by default, so the second call of a
  session can be as slow as the first. `ollama ps` says what is resident;
  `ollama list` only says what is on disk. OLLAMA_KEEP_ALIVE changes it.

  THE BUILD IS NOT ITS TWINS' BUILD. `gemma4:e4b` is Q4_K_M — quantised after
  training — while the LMStudio and Unsloth routes are QAT, trained around the
  quantisation. So `ollama-4b` against either of them measures ENGINE AND BUILD
  together. Say which you are claiming.

Pull what this file names before calling it:

    ollama pull gemma4:e4b && ollama pull nomic-embed-text
"""

from __future__ import annotations

from gateway import Endpoint, env

OLLAMA = env("OLLAMA_API_BASE", "http://host.containers.internal:11434/v1")

ENDPOINTS = [
    Endpoint(
        name="ollama-4b",
        provider="openai",
        model="gemma4:e4b",
        secret="ollama",
        api_base=OLLAMA,
        api_key="sk-ollama",
    ),
    # The same MODEL as `lms-embed` and `unsloth-embed` — nomic-embed-text v1.5,
    # 768 dimensions, a 2048 window — but NOT THE SAME BUILD. This one is F16 at
    # 274 MB, against `lms-embed`'s Q4_K_M at 84 MB and `unsloth-embed`'s Q8_0 at
    # 146 MB (measured 2026-08-31, `ollama show` and `lms ls --json`). All three
    # embedders in this list are a different quantisation, so none is a drop-in
    # twin of another — see the note in starter/lms.py for what that costs an
    # index.
    Endpoint(
        name="ollama-embed",
        provider="openai",
        model="nomic-embed-text",
        secret="ollama",
        api_base=OLLAMA,
        api_key="sk-ollama",
    ),
]
