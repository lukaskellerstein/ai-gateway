"""LMStudio (port 1234) — the FULL endpoints. Twelve: a size ladder, four roles, two embedders.

This file declares `ENDPOINTS` and nothing else. `seed.py` loads it when
GATEWAY_MODELS is `full` and GATEWAY_ENGINE is `lms` or `all`, and `gateway.py`
holds every MLflow API call. Its twin on the other gateway is
`litellm/full/lms.yaml` — the same twelve aliases, written again, because neither
gateway reads the other. That file also carries what MLflow has no place for:
prices, `max_tokens`, context windows and per-route timeouts.

EVERY ROUTE HERE ASSUMES A HAND LOAD AT FULL CONTEXT. A JIT load comes back at
8192 with a 1 h TTL, and a long prompt then fails for no visible reason.
`lms ps --json` is the truth, not the UI:

    lms load <model> --context-length 262144 --parallel 1 --gpu max

262144 for most; lms-4b, lms-2b and lms-creative cap at 131072 instead.
`lms ls --json` -> maxContextLength is the per-model figure.

`--parallel 1` on purpose. An agent client fires the main turn and its background
calls (titles, summaries) at once; at --parallel 4 they split one GPU four ways
and a 1-token request measured 34 s while big prompts sat behind it.

`provider` is `openai` here and on every local endpoint in this repo: an MLflow
provider name means "speaks the OpenAI protocol", not "is OpenAI". The key is any
string; LMStudio does not check it.
"""

from __future__ import annotations

from gateway import Endpoint, env

LM_STUDIO = env("LM_STUDIO_API_BASE", "http://host.containers.internal:1234/v1")
LM_STUDIO_KEY = "sk-lmstudio"

ENDPOINTS = [
    # The 26B MoE with ~4B active — the fast default of the ladder.
    Endpoint(
        name="lms-26b",
        provider="openai",
        model="google/gemma-4-26b-a4b-qat",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # The dense 31B, unablated. Slower than lms-26b — 31B dense against a 26B MoE
    # with ~4B active means every token goes through every parameter — so it is a
    # name you pick deliberately, not a default.
    #
    # QAT: quantisation-aware trained, not quantised after the fact. The 4-bit
    # error is learned around during training, so this sits closer to full
    # precision than its Q4_0 label suggests.
    Endpoint(
        name="lms-31b",
        provider="openai",
        model="google/gemma-4-31b-qat",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # The rungs below lms-31b. Same Gemma 4 family, same 262144 window, a fraction
    # of the weights — the names to reach for when the 31B's minutes-per-prompt
    # cost more than its extra quality is worth.
    Endpoint(
        name="lms-12b",
        provider="openai",
        model="google/gemma-4-12b-qat",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # 3 GB, so it loads in seconds and leaves most of the GPU free. For
    # classification, routing, extraction and the other high-volume short calls
    # where throughput is the constraint rather than reasoning. Tools and vision,
    # full window — small here means few parameters, not a cut-down feature set.
    Endpoint(
        name="lms-3b",
        provider="openai",
        model="mistralai/ministral-3-3b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # The Gemma 4 E pair — "effective" 4B and 2B, and the only LMStudio chat
    # routes whose window is 131072 rather than 262144.
    #
    # On the two figures you would check first they lose to lms-3b: e4b is 6.86 GB
    # on disk against Ministral's 2.99, e2b is 4.37 GB — LARGER than the 3B it
    # nominally sits below — and both carry half the context. They earn a name for
    # the one thing Ministral cannot give, which is a Gemma-family answer at this
    # size. `lms-4b` is also the one chat alias that exists in BOTH lists, which
    # is why tests/ defaults to it.
    Endpoint(
        name="lms-4b",
        provider="openai",
        model="google/gemma-4-e4b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    Endpoint(
        name="lms-2b",
        provider="openai",
        model="google/gemma-4-e2b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # The non-Gemma opinion at the top of the ladder: Qwen3.8 27B, tool-trained and
    # vision-capable, on the same 262144 window.
    #
    # Named by family and not by rung, deliberately. `lms-27b` would be ambiguous:
    # `lms-reasoning` below is ALSO a 27B Qwen, so a size name would describe two
    # different routes equally well. The reason to reach for this one is the
    # family, so the family is what the name says.
    #
    # It emits a reasoning block: asked for 17x23 it spent 59 of 65 completion
    # tokens thinking (verified 2026-08-23). LiteLLM gives it max_tokens 8192 for
    # that reason; MLflow cannot, so send the number yourself — see seed.py.
    Endpoint(
        name="lms-qwen",
        provider="openai",
        model="qwen/qwen3.8-27b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # Abliterated weights. It has no fallback chain ON PURPOSE, in either gateway:
    # a hosted twin would refuse the request and would see prompts chosen to stay
    # on this machine.
    Endpoint(
        name="lms-uncensored",
        provider="openai",
        model="gemma-4-31b-it-abliterated",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # A role, not a rung: this one emits a reasoning block before its answer.
    # Reasoning tokens are drawn from the same allowance as the reply, so a low
    # max_tokens returns empty content and no error — which reads as a broken
    # alias rather than a low cap.
    Endpoint(
        name="lms-reasoning",
        provider="openai",
        model="thinkingcap-qwen3.6-27b",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # A role: long-form prose at 28B, and the only non-Gemma, non-Qwen route here.
    # Its window is 131072, half what the Gemma routes carry.
    #
    # It is the one model whose LMStudio metadata says tool use was never trained
    # in (`trainedForToolUse: false` in `lms ls --json`) — and yet a single-tool
    # request returns a proper structured tool_call, verified 2026-08-23. Treat the
    # flag as a statement about training, not about the runtime. What stays
    # UNVERIFIED is whether that holds under an agent loop's many-tool, many-turn
    # prompts, which is where an untrained model degrades to raw-text tool syntax.
    Endpoint(
        name="lms-creative",
        provider="openai",
        model="meta/muse-glimmer",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    # The embedding pair on this engine. Both are nomic-embed-text v1.5 at 768
    # dimensions on a 2048 window; `lms-embed-hq` is the Q8_0 build against
    # `lms-embed`'s Q4_K_M — 146 MB against 84 MB, more fidelity per vector.
    #
    # VECTORS FROM THE TWO ARE NOT INTERCHANGEABLE. Quantisation moves where a
    # text lands in the space, so a query embedded with one and matched against an
    # index built with the other returns subtly worse neighbours — nothing errors,
    # the results are just quietly less relevant. Pick ONE alias per index, and
    # record which one alongside the index. `lms-embed-hq` is the same build
    # `unsloth-embed` serves, so that pair isolates the engine and nothing else.
    Endpoint(
        name="lms-embed",
        provider="openai",
        model="text-embedding-nomic-embed-text-v1.5",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
    Endpoint(
        name="lms-embed-hq",
        provider="openai",
        model="text-embedding-nomic-embed-text-v1.5-embedding",
        secret="lmstudio",
        api_base=LM_STUDIO,
        api_key=LM_STUDIO_KEY,
    ),
]
