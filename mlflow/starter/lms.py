"""LMStudio (port 1234) — the STARTER endpoints. Two: one chat model, one embedder.

This file declares `ENDPOINTS` and nothing else. `seed.py` loads it when
GATEWAY_MODELS is `starter` and GATEWAY_ENGINE is `lms` or `all`, and `gateway.py`
holds every MLflow API call. Its twin on the other gateway is
`litellm/starter/lms.yaml` — the same two aliases, written again, because neither
gateway reads the other.

The same two models exist on all three engines in this list, which is the point:
one model, three engines, so you measure the engine by changing the alias.

LMSTUDIO MUST BE HAND-LOADED. It JIT-loads a model that is not resident, and a
JIT load does NOT inherit hand-load flags — the model comes back at 8192 context
with a 1 h TTL, so a long prompt fails for no visible reason. `lms ps --json` is
the truth, not the UI:

    lms load google/gemma-4-e4b --context-length 131072 --parallel 1 --gpu max

`--parallel 1` on purpose: an agent client fires its main turn and its background
calls at once, and at --parallel 4 they split one GPU four ways.

`provider` is `openai` here and on every local endpoint in this repo. An MLflow
provider name means "speaks the OpenAI protocol", not "is OpenAI" — `api_base` is
the only thing separating LMStudio from api.openai.com. The key is any string;
LMStudio does not check it.
"""

from __future__ import annotations

from gateway import Endpoint, env

LM_STUDIO = env("LM_STUDIO_API_BASE", "http://host.containers.internal:1234/v1")

ENDPOINTS = [
    # Gemma 4 E4B — "effective" 4B, a 131072 window. Tools and vision both work:
    # small here means few parameters, not a cut-down feature set. It is also the
    # one chat alias present in BOTH lists on BOTH gateways, which is why tests/
    # defaults to it.
    Endpoint(
        name="lms-4b",
        provider="openai",
        model="google/gemma-4-e4b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key="sk-lmstudio",
    ),
    # nomic-embed-text v1.5 at 768 dimensions, the Q4_K_M build at 84 MB.
    #
    # EMBEDDING VECTORS DO NOT MIX ACROSS MODELS OR BUILDS, AND ALL THREE
    # EMBEDDERS HERE ARE A DIFFERENT BUILD of that one model — this is Q4_K_M,
    # `unsloth-embed` is Q8_0 at 146 MB, `ollama-embed` is F16 at 274 MB
    # (measured 2026-08-31, `lms ls --json` and `ollama show`). An index built
    # with one alias and queried with another returns quietly worse neighbours.
    # Nothing errors. Record which alias built each index, and do not treat any
    # two of these as interchangeable.
    Endpoint(
        name="lms-embed",
        provider="openai",
        model="text-embedding-nomic-embed-text-v1.5",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key="sk-lmstudio",
    ),
]
