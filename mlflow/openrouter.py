"""OpenRouter — the whole endpoint list for this engine. IT SPENDS REAL MONEY.

ONE ENGINE RUNS AT A TIME. `seed.py` loads THIS file when GATEWAY_ENGINE is
`openrouter`, and this endpoint is then the entire vocabulary the MLflow gateway
serves. Choosing that word is the act that makes spend possible — with a local
engine selected instead, nothing in the running gateway can bill anyone.

Its twin on the other gateway is `litellm/openrouter.yaml`, which carries TWO
aliases where this file carries one. That asymmetry is deliberate:

---------------------------------------------------------------------------
`openrouter-free` IS ABSENT HERE ON PURPOSE.

OpenRouter load-balances its free tier across upstream providers, and one of them
advertises tool support but returns tool calls as RAW TEXT under agent-scale
prompts — `tool_calls` absent, the syntax sitting in the content. Nothing errors:
an agent sees an ordinary message with no tool calls, executes nothing, and exits
cleanly. LiteLLM stops that with `extra_body.provider.order` plus
`allow_fallbacks: false`, pinning the one provider that behaves.

MLFLOW HAS NO EQUIVALENT OF `extra_body`. An `openrouter-free` endpoint here could
not carry the pin, so it would be a route that LOOKS like LiteLLM's and carries
exactly the failure the pin exists to prevent. A LiteLLM feature with no MLflow
equivalent is documented, not faked.

So expect `openrouter-free` to answer on 24000 and 404 on 25000. That is the one
case where the usual diagnosis — "the seed has not run" — is wrong.
---------------------------------------------------------------------------

THE ENGINE IS IN THE NAME. `cheap` and `standard` lived here as commented-out
examples until 2026-08-31 and were renamed: a caller reading `cheap` cannot tell
that it is not free.

IT NEEDS A KEY, and `gateway.py` SKIPS any endpoint whose key is empty rather than
storing a blank one. With no OPENROUTER_API_KEY in the shell that ran `up -d`,
this alias never reaches MLflow — it 404s here while LiteLLM keeps it and 401s on
24000. The seed says which endpoints it skipped and why.

WHAT MLFLOW CANNOT CARRY, absent rather than faked: the price, `max_tokens`, the
context window, the per-route timeout, and OpenRouter's provider controls.
"""

from __future__ import annotations

from gateway import Endpoint, env

OPENROUTER_KEY = env("OPENROUTER_API_KEY")

ENDPOINTS = [
    # Gemma 4 26B A4B — the same weights `lms-26b`, `unsloth-26b` and `ollama-26b`
    # run locally, so this is the cloud half of the comparison those aliases make:
    # the same model, on hardware you do not own and do not have to keep loaded.
    #
    # $0.07 in / $0.34 out per 1M tokens on 2026-08-31. The price is not stored
    # here — MLflow has nowhere to put it — which is exactly why LiteLLM stays the
    # gateway that meters spend.
    #
    # api_base is left blank on purpose: MLflow's `openrouter` provider already
    # knows the base URL, and a hand-written one would be a second place to go
    # stale.
    Endpoint(
        name="openrouter-26b",
        provider="openrouter",
        model="google/gemma-4-26b-a4b-it",
        secret="openrouter",
        api_key=OPENROUTER_KEY,
    ),
]
