#!/usr/bin/env python
"""Auto-discovery — ask a local engine what it holds. THIS PROJECT'S OWN COPY.

`seed.py` imports `check_word` and `discover` from here and builds MLflow
endpoints out of the result. Nothing else in this project uses this file, and
nothing outside this project reads it.

WHY THERE ARE TWO COPIES ON DISK. Each gateway is a standalone compose project:
you can delete a sibling folder and this one still comes up. A module shared
between them would be a file neither project could remove, so the probes below
are duplicated on purpose. THE PROBE FUNCTIONS ARE BYTE-FOR-BYTE THE SAME as the
sibling `litellm/` project's copy — fix a probe in one and copy it to the other.

WHAT THIS COPY DOES NOT HAVE is the renderer. LiteLLM is configured by a YAML
file, so its copy also writes `discovered-<engine>.yaml` and has a `main()`.
MLflow has NO CONFIG FILE — its endpoints are database rows written over an API —
so there is nothing here to render and no entry point. This file is a library.

ONE WORD IN `.env` TURNS IT ON, and empty is the default:

    GATEWAY_DISCOVERY   (empty) | on

With it empty, `seed.py` never imports this file at all, and `config/<engine>.py`
is the whole vocabulary. With it set, every model the engine holds is ADDED to
that hand-written list — a discovered alias that would collide with a hand-written
one is dropped, so turning discovery on can only ADD names.

DISCOVERY IS LOCAL-ONLY, ON PURPOSE. `lms`, `unsloth` and `ollama` are free, so
enumerating everything on the disk costs nothing but a longer list. OpenRouter
lists hundreds of models and every one bills a real account, so a paid engine
keeps its hand-written file and MONEY IS NEVER DISCOVERED. Ask for discovery on
`openrouter` or `openai` and `discover()` refuses by name.

`GATEWAY_DISCOVERY=off` DOES NOT TURN IT OFF. compose reacts to the word being
NON-EMPTY, not to its meaning, so `off`, `false`, `0` and `no` all read as ON.
`check_word` catches those four and raises, saying the fix is an EMPTY value.

WHAT EACH ENGINE CAN ACTUALLY TELL US differs:

    lms      GET /api/v0/models   id, type, max_context_length, quantization, state
    ollama   GET /api/tags        name, capabilities, quantization; context_length
                                  only sometimes — GET /api/show fills the rest in
    unsloth  GET /v1/models       id, quant, loaded — but NO type, so chat against
                                  embedding is guessed from the id, and the window
                                  is reported for the ONE LOADED model only

IT RUNS INSIDE THE CONTAINER, not on the host. The default base URLs are
`host.containers.internal`, which resolves inside a container and nowhere else.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

# The engines that can be discovered. The two PAID ones are absent on purpose —
# see the header. This is deliberately NOT seed.py's ENGINES tuple: that one lists
# what this gateway can serve, this one lists what is safe to enumerate.
LOCAL_ENGINES = ("lms", "unsloth", "ollama")

# Words a reader will type expecting discovery to be OFF. compose cannot tell them
# apart from `on`, so they are refused here rather than half-honoured.
FALSY = frozenset({"off", "false", "0", "no"})

# Used only when an engine will not say. Small on purpose: a window that is too
# small refuses an over-long prompt, while one that is too large lets it through
# to fail deep inside the engine with a worse message.
DEFAULT_CONTEXT = 8192

HTTP_TIMEOUT = 15

DEFAULT_BASE = {
    "lms": "http://host.containers.internal:1234/v1",
    "unsloth": "http://host.containers.internal:8888/v1",
    "ollama": "http://host.containers.internal:11434/v1",
}

# LMStudio's `type` field. `vlm` is a vision-capable llm, still a chat route.
LMS_CHAT_TYPES = frozenset({"llm", "vlm"})


def env(name: str, default: str = "") -> str:
    """Read NAME from the environment, treating blank as absent."""
    return os.environ.get(name) or default


def slug(text: str) -> str:
    """Turn a model id into an alias suffix.

    MLflow accepts letters, digits, dot, dash and underscore in an endpoint name
    and nothing else, so the slash in `google/gemma-4-e4b` and the colon in
    `gemma4:26b` both have to go. Lowercased so one model cannot produce two
    aliases that differ only in case.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-").lower()


@dataclass(frozen=True)
class Model:
    """One model an engine reported, in terms no gateway is specific to.

    `model_id` is passed to the engine VERBATIM — it is the only field that must
    not be normalised. `alias` is what a caller names, and it is derived, so the
    same model always produces the same alias on every gateway that discovers it.
    """

    engine: str
    model_id: str
    kind: str  # "chat" or "embedding"
    context: int
    note: str = ""

    @property
    def alias(self) -> str:
        return f"{self.engine}-{slug(self.model_id)}"


def _get_json(url: str, *, headers: dict[str, str] | None = None, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.load(response)


def _root(api_base: str) -> str:
    """Strip the trailing /v1.

    LMStudio's and Ollama's model listings sit OUTSIDE the OpenAI-compatible
    surface — /api/v0/models and /api/tags — while the *_API_BASE variables point
    at /v1 because that is what the gateway calls.
    """
    return api_base.rstrip("/").removesuffix("/v1")


def probe_lms() -> list[Model]:
    """LMStudio's own REST listing, which is far richer than its /v1/models.

    It reports every model ON DISK with `state` telling you which are resident.
    Both are configured: LMStudio JIT-loads a model that is not loaded, so a
    not-loaded model answers on the first call — just slowly.
    """
    base = env("LM_STUDIO_API_BASE", DEFAULT_BASE["lms"])
    payload = _get_json(f"{_root(base)}/api/v0/models")
    models = []
    for row in payload.get("data", []):
        row_type = row.get("type", "")
        if row_type in LMS_CHAT_TYPES:
            kind = "chat"
        elif row_type == "embeddings":
            kind = "embedding"
        else:
            continue  # a type this script does not know how to serve
        models.append(
            Model(
                engine="lms",
                model_id=row["id"],
                kind=kind,
                context=int(row.get("max_context_length") or DEFAULT_CONTEXT),
                note=f"{row_type}, {row.get('quantization', 'unknown quant')}, {row.get('state', 'unknown state')} at discovery",
            )
        )
    return models


def probe_ollama() -> list[Model]:
    """Ollama's tag list, with a second call for the models it under-reports."""
    base = env("OLLAMA_API_BASE", DEFAULT_BASE["ollama"])
    root = _root(base)
    payload = _get_json(f"{root}/api/tags")
    models = []
    for row in payload.get("models", []):
        name = row["name"]
        capabilities = row.get("capabilities") or []
        details = row.get("details") or {}
        context = details.get("context_length") or _ollama_context(root, name)
        models.append(
            Model(
                engine="ollama",
                model_id=name,
                kind="embedding" if "embedding" in capabilities else "chat",
                context=int(context or DEFAULT_CONTEXT),
                note=f"{', '.join(capabilities) or 'no capabilities reported'}; {details.get('quantization_level', 'unknown quant')}",
            )
        )
    return models


def _ollama_context(root: str, name: str) -> int | None:
    """The window for a model whose /api/tags row omits `details.context_length`.

    Measured 2026-09-03: `gemma4:26b` carries it and `gemma4:31b`, `gemma4:latest`
    and `nomic-embed-text` do not. /api/show always has it, but files it under
    `<architecture>.context_length` — `gemma4.`, `nomic-bert.`, `llama.` — so the
    architecture has to be FOUND rather than assumed.
    """
    try:
        payload = _get_json(f"{root}/api/show", payload={"model": name})
    except (urllib.error.URLError, OSError, ValueError):
        return None  # the caller falls back to DEFAULT_CONTEXT
    for key, value in (payload.get("model_info") or {}).items():
        if key.endswith(".context_length"):
            return int(value)
    return None


def probe_unsloth() -> list[Model]:
    """Unsloth's /v1/models, which is richer than the OpenAI shape it looks like.

    It reports every model ON DISK by id, with `quant` and `loaded` on every row —
    so the NAME is never the problem. Two things it does not give, each with a
    different consequence:

    THE CONTEXT WINDOW IS REPORTED ONLY FOR THE MODEL THAT IS LOADED. Unsloth holds
    ONE MODEL AT A TIME, and `context_length` is null on every other row (measured
    2026-09-03: 1 of 15 rows carried 131072, the other 14 carried null). So the
    window here is read when it can be and assumed at DEFAULT_CONTEXT otherwise —
    far below the 262144 the hand-written `unsloth-26b` carries, which is why that
    file stays the better route for the models it names. Load a different model and
    re-run `up -d` and a different row gets its real number.

    THERE IS NO TYPE OR CAPABILITIES FIELD, unlike LMStudio and Ollama. So chat
    against embedding is guessed from the id, and a chat model with "embed" in its
    name would be classified wrongly.

    The one-model-at-a-time limit spans chat and the embedder, so discovering 15
    aliases does not make 15 of them usable at once.
    """
    base = env("UNSLOTH_API_BASE", DEFAULT_BASE["unsloth"])
    key = env("UNSLOTH_API_KEY")
    if not key:
        raise RuntimeError(
            "UNSLOTH_API_KEY is empty — Unsloth answers 401 on every route, /v1/models "
            "included. It arrives from the shell (~/Projects/.envrc), so the shell that "
            "ran `up -d` probably had no direnv."
        )
    payload = _get_json(f"{base.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
    models = []
    for row in payload.get("data", []):
        reported = row.get("context_length") or row.get("native_context_length")
        state = "loaded" if row.get("loaded") else "not loaded"
        window = (
            "window read from the engine"
            if reported
            else f"window NOT reported ({DEFAULT_CONTEXT} assumed) — Unsloth gives it for the LOADED model only"
        )
        models.append(
            Model(
                engine="unsloth",
                model_id=row["id"],
                kind="embedding" if "embed" in row["id"].lower() else "chat",
                context=int(reported or DEFAULT_CONTEXT),
                note=f"{row.get('quant', 'unknown quant')}, {state} at discovery; kind guessed from the id; {window}",
            )
        )
    return models


PROBES = {"lms": probe_lms, "unsloth": probe_unsloth, "ollama": probe_ollama}


def check_word(word: str) -> None:
    """Refuse a value that reads as 'off' but that compose has already read as 'on'."""
    if word.strip().lower() in FALSY:
        raise ValueError(
            f"GATEWAY_DISCOVERY={word!r} does NOT turn discovery off. compose reacts to the "
            "word being non-empty, not to its meaning, and the seed has already been told "
            "to discover. To turn discovery off, leave the value EMPTY."
        )


def discover(engine: str) -> list[Model]:
    """Every model `engine` holds, sorted so the endpoint list has a stable order.

    A dead engine RAISES rather than returning an empty list. Seeding a gateway
    with no endpoints would leave it up and serving nothing, with the only clue in
    a log nobody reads.
    """
    if engine not in PROBES:
        raise ValueError(
            f"discovery is local-only: {engine!r} is not one of {', '.join(LOCAL_ENGINES)}. "
            "OpenRouter and OpenAI bill a real account per model, so they keep their "
            "hand-written lists — leave GATEWAY_DISCOVERY empty to use them."
        )
    models = PROBES[engine]()
    if not models:
        raise RuntimeError(f"{engine} answered but reported no models — nothing to configure")
    return sorted(models, key=lambda model: (model.kind, model.alias))
