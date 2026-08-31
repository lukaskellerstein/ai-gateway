"""Ollama (port 11434) — the FULL endpoints. Four: three chat models, one embedder.

This file declares `ENDPOINTS` and nothing else. `seed.py` loads it when
GATEWAY_MODELS is `full` and GATEWAY_ENGINE is `ollama` or `all`. Its twin on the
other gateway is `litellm/full/ollama.yaml` — the same four aliases, written
again, because neither gateway reads the other.

THE THIRD LOCAL ENGINE. `ollama-31b` and `ollama-26b` complete the pair the
`unsloth-*` aliases started: one model, three engines, so lms-31b / unsloth-31b /
ollama-31b differ in the engine and nothing else.

FOUR differences from the routes on the other engines:

1. THE MODEL ID CARRIES A COLON, not a slash: `gemma4:31b`.
2. IT IGNORES THE KEY, and one is set anyway. Ollama never reads Authorization;
   `sk-ollama` is here only because `gateway.py` skips an endpoint whose key is
   empty, and a skipped endpoint is an alias that silently never reaches MLflow.
3. IT LOADS ON DEMAND AND HOLDS SEVERAL MODELS AT ONCE, the opposite of Unsloth's
   one-at-a-time swap. The cost moves to the first call on a cold model, which
   reads ~19 GB from disk before its first token. Ollama then evicts a model after
   5 minutes idle by default, so the SECOND call of a session can be as slow as
   the first. `ollama ps` is the truth about what is resident — not `ollama list`,
   which only says what is on disk.
4. THE BUILD IS NOT ITS TWINS' BUILD. LMStudio and Unsloth both run QAT weights;
   these tags are Q4_K_M, quantised AFTER training. Ollama's library does carry
   `gemma4:31b-it-qat` and `gemma4:26b-a4b-it-qat` and they are not what is pulled
   here. So an ollama-31b vs lms-31b difference measures ENGINE AND QUANTISATION
   TOGETHER. Say which you are claiming, or pull the -it-qat tags first.

It thinks on weights its LMStudio twin does not — verified 2026-08-27, `/api/show`
reports `thinking` in capabilities. MLflow has nowhere to store max_tokens, so a
caller on 25000 must send it or risk empty content with finish_reason "length".

Pull what this file names before calling it:

    ollama pull gemma4:31b && ollama pull gemma4:26b
    ollama pull gemma4:e4b && ollama pull nomic-embed-text
"""

from __future__ import annotations

from gateway import Endpoint, env

OLLAMA = env("OLLAMA_API_BASE", "http://host.containers.internal:11434/v1")
OLLAMA_KEY = "sk-ollama"

ENDPOINTS = [
    Endpoint(
        name="ollama-31b",
        provider="openai",
        model="gemma4:31b",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
    Endpoint(
        name="ollama-26b",
        provider="openai",
        model="gemma4:26b",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
    # `gemma4:latest` is the SAME model — one digest, c6eb396dbd59, two tags. The
    # explicit `:e4b` is used because `latest` moves on the next `ollama pull` and
    # would change what this alias means with nothing here edited.
    Endpoint(
        name="ollama-4b",
        provider="openai",
        model="gemma4:e4b",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
    # The same MODEL as `lms-embed` and `unsloth-embed` — nomic-embed-text v1.5 at
    # 768 dimensions on a 2048 window, verified 2026-08-27 — but NOT A TWIN OF
    # EITHER, because the build differs. Measured 2026-08-31: this is F16 at
    # 274 MB, `lms-embed` is Q4_K_M at 84 MB, `lms-embed-hq` and `unsloth-embed`
    # are Q8_0 at 146 MB. So the embedding row compares three engines on one model
    # at THREE different quantisations — unlike the chat rows, where `lms-4b` and
    # `unsloth-4b` are both QAT and isolate the engine cleanly. The pair that
    # isolates the engine here is `lms-embed-hq` against `unsloth-embed`; this
    # alias is never one half of it.
    #
    # No tag is pinned: `nomic-embed-text` resolves to :latest, which has been
    # v1.5 for a long time but is not guaranteed to stay. Pin
    # `nomic-embed-text:v1.5` if reproducibility of the VECTORS matters — a moved
    # tag re-embeds differently and silently invalidates an index built with the
    # old one.
    Endpoint(
        name="ollama-embed",
        provider="openai",
        model="nomic-embed-text",
        secret="ollama",
        api_base=OLLAMA,
        api_key=OLLAMA_KEY,
    ),
]
