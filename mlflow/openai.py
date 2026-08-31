"""OpenAI — the whole endpoint list for this engine. IT SPENDS REAL MONEY.

ONE ENGINE RUNS AT A TIME. `seed.py` loads THIS file when GATEWAY_ENGINE is
`openai`, and these endpoints are then the entire vocabulary the MLflow gateway
serves. Choosing that word is the act that makes spend possible — with a local
engine selected instead, nothing in the running gateway can bill anyone.

Its twin on the other gateway is `litellm/openai.yaml`.

A CALLER ON THIS GATEWAY MUST SEND `max_completion_tokens`, NOT `max_tokens`.
The gpt-5 family rejects `max_tokens` — "Unsupported parameter: 'max_tokens' is
not supported with this model." LiteLLM translates it, so the same body works on
24000 and 400s here (verified 2026-08-31), because MLflow forwards parameters
exactly as sent. `max_completion_tokens` works on BOTH gateways, so that is what a
caller driving both should send. It is the one place where this repo's "same
alias, same body, different base_url" promise does not hold.

THE ENGINE IS IN THE NAME. `frontier` lived here as a commented-out example until
2026-08-31 and was renamed: it named a tier rather than a vendor, and it pointed
at a *mini* model.

IT NEEDS A KEY, and `gateway.py` SKIPS any endpoint whose key is empty rather than
storing a blank one. With no OPENAI_API_KEY in the shell that ran `up -d` neither
alias reaches MLflow, and the seed says so in its log.

NOTE THE PROVIDER NAME MEANS SOMETHING DIFFERENT HERE THAN IN THE LOCAL FILES.
All three local engines also declare `provider="openai"`, because in MLflow a
provider name means "speaks this protocol" and `api_base` is what separates
LMStudio from api.openai.com. THIS file is the one where it means the company too
— which is why `api_base` is blank: the provider's default URL is the real OpenAI.
"""

from __future__ import annotations

from gateway import Endpoint, env

OPENAI_KEY = env("OPENAI_API_KEY")

ENDPOINTS = [
    # gpt-5.4-mini — the small, fast, cheap tier. No ladder here on purpose: a
    # hosted catalogue moves faster than this repo does, and a stale model id is a
    # 404 at call time rather than a clean error at startup.
    #
    # IT HAS NO VISION, so tests/03_multimodal.py cannot pass against it. That is
    # why tests/ never picks an `openai-*` alias as its default.
    Endpoint(
        name="openai-mini",
        provider="openai",
        model="gpt-5.4-mini",
        secret="openai",
        api_key=OPENAI_KEY,
    ),
    # text-embedding-3-small at 1536 dimensions — the only hosted embedder here,
    # and NOT interchangeable with any local one. `lms-embed`, `unsloth-embed` and
    # `ollama-embed` are all nomic v1.5 at 768 dims; this is a different model at
    # twice the width, so an index built with one and queried with the other does
    # not merely degrade — the vector lengths do not match and it cannot be read.
    #
    # TWO THINGS TO WEIGH. Every document embedded here LEAVES THIS MACHINE, which
    # the three local embedders never do. And retrieval is many small calls, so
    # this is the alias most able to run up a bill with no single call looking
    # expensive — meter it on 24000, where spend logs exist, not here.
    Endpoint(
        name="openai-embed",
        provider="openai",
        model="text-embedding-3-small",
        secret="openai",
        api_key=OPENAI_KEY,
    ),
]
