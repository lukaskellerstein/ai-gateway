#!/usr/bin/env python
"""Auto-discovery — ask a local engine what it holds, and write it out for LiteLLM.

THE HAND-WRITTEN CONFIGS ARE STILL THE DEFAULT, and this file does nothing until a
SECOND word in `.env` says otherwise:

    GATEWAY_ENGINE      lms | unsloth | ollama | openrouter | openai WHICH ENGINE
    GATEWAY_DISCOVERY   (empty) | on                                 MANUAL, OR MANUAL + EVERY MODEL

With `GATEWAY_DISCOVERY` empty — the default, and what a fresh clone gets — nothing
here runs and LiteLLM reads `config/<engine>.yaml` exactly as before. Those
hand-written files are the documentation for how to configure this gateway by
hand, so they stay.

WHY THERE ARE TWO COPIES OF THIS MODULE ON DISK. Each gateway is a standalone
compose project: you can delete a sibling folder and this one still comes up. A
module shared between them would be a file neither project could remove, so the
probes below are duplicated on purpose. THE PROBE FUNCTIONS ARE BYTE-FOR-BYTE THE
SAME as the sibling `mlflow/` project's copy — fix a probe in one and copy it to
the other. That copy has no renderer, because MLflow has no config file: its
endpoints are database rows written over an API.

WITH IT ON, DISCOVERY IS ADDITIVE, NEVER A REPLACEMENT. The generated config
INCLUDES the hand-written one:

    config/discovered-lms.yaml
      include: [settings.yaml, lms.yaml]     <- the settings AND your own aliases
      model_list: ...                        <- every model LMStudio holds

LiteLLM merges an included file key by key and EXTENDS a list, so `lms-4b`,
`lms-26b` and `lms-embed` keep answering beside the discovered names (verified
against ghcr.io/berriai/litellm:main-stable, 2026-09-03: two includes plus an own
model_list produced all three lists in /v1/models). Turning discovery on can only
ADD names. Nothing a project already calls can break.

DISCOVERY IS LOCAL-ONLY, ON PURPOSE. `lms`, `unsloth` and `ollama` are free, so
exposing everything on the disk costs nothing but a longer model list. OpenRouter
lists hundreds of models and every one of them bills a real account, so a paid
engine keeps its hand-written file and MONEY IS NEVER DISCOVERED. Ask for
discovery on `openrouter` or `openai` and this script refuses by name.

`GATEWAY_DISCOVERY=off` DOES NOT TURN IT OFF, and that is worth knowing before it
bites. compose builds the config filename with `${GATEWAY_DISCOVERY:+discovered-}`,
which reacts to the word being NON-EMPTY, not to its meaning — so `off`, `false`
and `0` all switch discovery ON as far as compose is concerned. This script
catches those four words and exits 2 saying the fix is an EMPTY value. Without the
check the failure would be LiteLLM crash-looping on a file nobody meant to name.

WHAT EACH ENGINE CAN ACTUALLY TELL US differs, and the generated comments say which
numbers were read and which were assumed:

    lms      GET /api/v0/models   id, type, max_context_length, quantization, state
    ollama   GET /api/tags        name, capabilities, quantization; context_length
                                  only sometimes — GET /api/show fills the rest in
    unsloth  GET /v1/models       id, quant, loaded — but NO type, so chat against
                                  embedding is guessed from the id, and the window
                                  is reported for the ONE LOADED model only

RUN IT THROUGH COMPOSE, not on the host. The default base URLs are
`host.containers.internal`, which resolves inside a container and nowhere else:

    docker compose run --rm discover python /app/discover/gateway_discovery.py --engine lms
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# The engines that can be discovered. The two PAID ones are absent on purpose — see
# the header. This is deliberately NOT seed.py's ENGINES tuple: that one lists what
# the repo can serve, this one lists what it is safe to enumerate.
LOCAL_ENGINES = ("lms", "unsloth", "ollama")

# Words a reader will type expecting discovery to be OFF. compose cannot tell them
# apart from `on`, so they are refused here rather than half-honoured.
FALSY = frozenset({"off", "false", "0", "no"})

# Reserved out of the model's window for the reply, matching every hand-written
# config: 131072 - 8192 = 122880, 262144 - 8192 = 253952.
OUTPUT_RESERVE = 8192

# Used only when an engine will not say. Small on purpose: a window that is too
# small refuses an over-long prompt, while one that is too large lets it through to
# fail deep inside the engine with a worse message.
DEFAULT_CONTEXT = 8192

HTTP_TIMEOUT = 15

# The shadow prices every discovered chat route carries, copied from the
# hand-written configs. An UNPRICED route logs $0, which makes a virtual key's
# budget ceiling a no-op — so a rule that prices every route is not a nicety.
# settings.yaml § 2 has the reasoning.
CHAT_INPUT_COST = "0.00000012"
CHAT_OUTPUT_COST = "0.00000035"

# Generous on purpose. Reasoning tokens come out of the SAME allowance as the
# reply, and which routes think is decided per MODEL — a route that hits the cap
# mid-thought returns EMPTY content with finish_reason "length" and no error at
# all. Discovery cannot know which of 14 models reason, so every one gets room.
CHAT_MAX_TOKENS = 8192

# Prompt processing measures ~100 tok/s on this machine, so a large prompt needs
# 5-15 minutes before its first token. LiteLLM's 600 s default expires mid-prompt.
CHAT_TIMEOUT = 3600

# How each engine is spoken to. `openai/` is a PROTOCOL, not a company: api_base is
# the only thing separating Unsloth and Ollama from api.openai.com.
PROVIDER_PREFIX = {"lms": "lm_studio/", "unsloth": "openai/", "ollama": "openai/"}
API_BASE_VAR = {"lms": "LM_STUDIO_API_BASE", "unsloth": "UNSLOTH_API_BASE", "ollama": "OLLAMA_API_BASE"}

# LMStudio takes any string and Ollama ignores the header entirely, but LiteLLM's
# `openai/` provider needs SOME key or it falls back to a blank OPENAI_API_KEY.
API_KEY_LINE = {
    "lms": '"sk-lmstudio"',
    "ollama": '"sk-ollama"',
    "unsloth": "os.environ/UNSLOTH_API_KEY",
}

DEFAULT_BASE = {
    "lms": "http://host.containers.internal:1234/v1",
    "unsloth": "http://host.containers.internal:8888/v1",
    "ollama": "http://host.containers.internal:11434/v1",
}

# LMStudio's `type` field. `vlm` is a vision-capable llm, still a chat route.
LMS_CHAT_TYPES = frozenset({"llm", "vlm"})

# Finds `model_name: foo` in a hand-written config, to spot an alias discovery
# would duplicate. A regex rather than a YAML parse because the generated file
# needs comments and this script has no third-party dependency at all.
MODEL_NAME_LINE = re.compile(r"^\s*-?\s*model_name:\s*\"?([^\"\s#]+)", re.MULTILINE)


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
    """One model an engine reported, in terms neither gateway is specific to.

    `model_id` is passed to the engine VERBATIM — it is the only field that must
    not be normalised. `alias` is what a caller names, and it is derived, so the
    same model always produces the same alias on both gateways.
    """

    engine: str
    model_id: str
    kind: str  # "chat" or "embedding"
    context: int
    note: str = ""

    @property
    def alias(self) -> str:
        return f"{self.engine}-{slug(self.model_id)}"

    @property
    def max_input_tokens(self) -> int:
        """The window, less the reply's share of it.

        An embedder produces no tokens, so it keeps its whole window. The `// 2`
        floor stops a small window going to zero or negative.
        """
        if self.kind == "embedding":
            return self.context
        return max(self.context - OUTPUT_RESERVE, self.context // 2)


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
    at /v1 because that is what the gateways call.
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


def enabled() -> bool:
    """Is discovery on? Empty or absent means no, which is the default."""
    return bool(env("GATEWAY_DISCOVERY").strip())


def check_word(word: str) -> None:
    """Refuse a value that reads as 'off' but that compose has already read as 'on'."""
    if word.strip().lower() in FALSY:
        raise ValueError(
            f"GATEWAY_DISCOVERY={word!r} does NOT turn discovery off. compose reacts to the "
            "word being non-empty, not to its meaning, and has already pointed LiteLLM at "
            "discovered-*.yaml. To turn discovery off, leave the value EMPTY."
        )


def discover(engine: str) -> list[Model]:
    """Every model `engine` holds, sorted so the generated file has a stable order.

    A dead engine RAISES rather than returning an empty list. Writing a config with
    no models would leave both gateways up and serving nothing, with the only clue
    in a log nobody reads.
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


def existing_aliases(path: Path) -> set[str]:
    """The alias names the hand-written config already declares.

    The generated file INCLUDES that config, so an alias in both would appear
    twice and LiteLLM would silently load-balance between the two entries.
    """
    try:
        return set(MODEL_NAME_LINE.findall(path.read_text()))
    except OSError:
        return set()


def render(engine: str, models: list[Model], manual: str) -> str:
    """The whole generated LiteLLM config, comments included."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    chat = sum(1 for model in models if model.kind == "chat")
    embed = len(models) - chat
    lines = [
        f"# GENERATED by discover/gateway_discovery.py on {stamp}. DO NOT EDIT — every",
        "# `up -d` overwrites this file, and it is gitignored.",
        "#",
        f"# {len(models)} aliases discovered from the {engine} engine: {chat} chat, {embed} embedding.",
        "#",
        f"# IT INCLUDES {manual}, so every hand-written alias in that file KEEPS ANSWERING",
        "# beside the names below. LiteLLM extends a list across included files, so turning",
        "# discovery on only ever ADDS names. To go back to the hand-written config alone,",
        "# leave GATEWAY_DISCOVERY empty in .env and run `up -d` again.",
        "#",
        "# THE PRICES ARE SHADOW PRICES and the same for every discovered chat route: these",
        "# models are free to run, and an unpriced route logs $0, which makes a virtual key's",
        "# budget ceiling a no-op. settings.yaml has the reasoning.",
        "#",
        "# max_input_tokens IS THE WINDOW THE ENGINE REPORTED, less an 8192 output reserve.",
        "# On LMStudio that number is a promise only while the model is HAND-LOADED: a JIT",
        "# load silently comes back at 8192 context, and `lms ps --json` is the truth.",
        "",
        "include:",
        "  - settings.yaml",
        f"  - {manual}",
        "",
        "model_list:",
    ]
    prefix = PROVIDER_PREFIX[engine]
    base_var = API_BASE_VAR[engine]
    key_line = API_KEY_LINE[engine]
    for model in models:
        lines.append(f"  # {model.note}")
        lines.append(f"  - model_name: {model.alias}")
        lines.append("    litellm_params:")
        lines.append(f"      model: {prefix}{model.model_id}")
        lines.append(f"      api_base: os.environ/{base_var}")
        lines.append(f"      api_key: {key_line}")
        if model.kind == "chat":
            lines.append(f"      input_cost_per_token: {CHAT_INPUT_COST}")
            lines.append(f"      output_cost_per_token: {CHAT_OUTPUT_COST}")
            lines.append(f"      max_tokens: {CHAT_MAX_TOKENS}")
            lines.append(f"      timeout: {CHAT_TIMEOUT}")
            lines.append("    model_info:")
            lines.append(f"      max_input_tokens: {model.max_input_tokens}   # {model.context} - {OUTPUT_RESERVE}")
            lines.append(f"      max_output_tokens: {OUTPUT_RESERVE}")
        else:
            lines.append("      input_cost_per_token: 0")
            lines.append("      output_cost_per_token: 0")
            lines.append("    model_info:")
            lines.append(f"      max_input_tokens: {model.max_input_tokens}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover a local engine's models and write LiteLLM's config.",
        epilog="Both arguments default from the environment, which is how compose passes them in.",
    )
    parser.add_argument("--engine", default=env("GATEWAY_ENGINE", "lms"))
    parser.add_argument("--out", default=env("LITELLM_CONFIG_DIR", "/app/config"))
    args = parser.parse_args(argv)

    if not enabled():
        print("GATEWAY_DISCOVERY is empty — discovery is off, and the hand-written config stands.")
        return 0

    engine = args.engine.strip()
    try:
        check_word(env("GATEWAY_DISCOVERY"))
        models = discover(engine)
    except (ValueError, RuntimeError) as error:
        print(f"discovery failed: {error}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as error:
        print(
            f"discovery failed: cannot reach the {engine} engine ({error}). It runs natively on "
            "the host, so check it is started and listening.",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    manual = f"{engine}.yaml"
    taken = existing_aliases(out_dir / manual)
    kept = [model for model in models if model.alias not in taken]

    for model in models:
        mark = "  " if model.alias in taken else "+ "
        suffix = "  (already in the hand-written config)" if model.alias in taken else ""
        print(f"{mark}{model.alias:46s} {model.kind:9s} ctx {model.context:>7d}{suffix}")

    target = out_dir / f"discovered-{engine}.yaml"
    target.write_text(render(engine, kept, manual))
    print(
        f"\nwrote {target}: {len(kept)} discovered aliases, plus every alias {manual} declares."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
