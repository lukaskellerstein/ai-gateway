#!/usr/bin/env python
"""MLflow AI Gateway — the seeder's entry point. It picks ONE engine, and writes.

MLflow's gateway has NO CONFIG FILE: its endpoints live in the tracking database
and arrive over an API. So this gateway's alias list is Python — one file per
engine, beside this one:

    lms.py         LMStudio, on this machine        free
    unsloth.py     Unsloth Studio, on this machine  free
    ollama.py      Ollama, on this machine          free
    openrouter.py  OpenRouter                       PAID
    openai.py      OpenAI                           PAID

ONE WORD FROM THIS PROJECT'S `.env` PICKS WHAT RUNS:

    GATEWAY_ENGINE   lms | unsloth | ollama | openrouter | openai   default lms

THAT WORD IS THIS PROJECT'S ALONE. Each gateway is a standalone compose project
with its own `.env`, so the sibling `litellm/` project can be serving a different
engine at the same moment, and nothing checks that the two agree. Before the
split one word drove both and they could not diverge.

A SECOND WORD DECIDES WHETHER THE LIST ABOVE IS THE WHOLE LIST:

    GATEWAY_DISCOVERY   (empty) | on                                default empty

Empty is the default and nothing changes: the file this script imports is the
entire vocabulary, which is what makes those files worth reading as the example of
how to configure this gateway by hand. Set it and every model the engine holds is
ADDED to that list — the hand-written endpoints are never replaced, and a
discovered alias that would collide with one is dropped. `discover/` holds the
probing; see `with_discovered` below and `discover/gateway_discovery.py`.

DISCOVERY IS LOCAL-ONLY. `openrouter` and `openai` bill a real account per model,
so they keep their hand-written lists and this script refuses to enumerate them.

ONE ENGINE AT A TIME, ON PURPOSE. There is no `all`, no list and no starter/full
split — the repo serves one engine's three-or-so aliases and nothing else. To
compare two engines, change the word and run `docker compose up -d` again; the
aliases are named so that only the prefix differs (`lms-26b` / `unsloth-26b` /
`ollama-26b` / `openrouter-26b` are the same weights).

AN ENGINE IS AN ENGINE, LOCAL OR HOSTED. `openrouter` and `openai` are engine
names like `lms` is, and the alias prefix says which is which. Selecting one of
those two is the only way anything here can spend money — and this script prints a
warning when you do.

compose runs this on every `up -d`, after `mlflow` reports healthy, and it is
idempotent.

RUN IT BY HAND THROUGH COMPOSE, NOT ON THE HOST. It imports `mlflow`, which the
image ships and a laptop usually does not — on the host it stops at
`ModuleNotFoundError: No module named 'mlflow'` before it reads one argument.
Inside the container `--tracking-uri` already defaults to http://mlflow:5000:

    docker compose run --rm mlflow-seed python /app/config/seed.py --engine ollama
    docker compose run --rm mlflow-seed python /app/config/seed.py --reset  # rebuild what it names
    docker compose run --rm mlflow-seed python /app/config/seed.py --prune  # ALSO delete what it does not

`--tracking-uri http://localhost:25000` is for the rare host run that does have
MLflow installed.

---------------------------------------------------------------------------
READ THIS BEFORE `--prune`. It deletes every endpoint this run does not name —
which is EVERY OTHER ENGINE'S. `--engine ollama --prune` removes every `lms-*`,
`unsloth-*`, `openrouter-*` and `openai-*` endpoint MLflow holds, and the
`gateway/*` traces then point at endpoints that no longer exist. Without `--prune`
the extras are left alone and merely listed, which is why switching engine leaves
the old names still answering on 25000.

NOTHING HERE READS ANYTHING OUTSIDE THIS FOLDER, and that is deliberate: this is a
standalone compose project, and the sibling `litellm/` directory can be deleted
whole without touching it. The cost is that the alias lists are maintained once
per gateway — add a model in `config/<engine>.py` AND in the sibling's
`config/<engine>.yaml`, or the name answers on one port and 404s on the other.
Nothing checks that any more; the suite that used to went with the shared tests/.

WHAT MLFLOW HAS NO PLACE FOR, so it is absent rather than lost: prices,
`max_tokens`, context windows and per-route timeouts. MLflow carries one global
timeout, set as MLFLOW_GATEWAY_ROUTE_TIMEOUT_SECONDS in compose.yml. There are no
virtual keys, no spend logs and no budget ceilings here at all — which is why
LiteLLM stays the primary gateway. This folder's README.md has the list.

THE MISSING `max_tokens` IS THE ONE THAT BITES. Chat endpoints here can emit a
reasoning block, and reasoning tokens come out of the SAME allowance as the
reply — so a request whose ceiling is too low returns EMPTY content with
finish_reason "length" and raises no error at all. A CALLER ON 25000 MUST SEND
`max_tokens` ITSELF. Keep it generous, and do not try to predict which routes
think from the engine: it is decided per MODEL. `unsloth-26b` reasons while
`lms-26b` on identical weights does not (2026-08-27), and `lms-4b` on that same
"non-thinking" LMStudio spent 65 of 70 completion tokens reasoning (2026-08-28).
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import importlib
import sys

from gateway import DEFAULT_TRACKING_URI, Endpoint, env, seed

# The engines this repo carries, one file each beside this one. Order is only the
# order they are reported in.
ENGINES = ("lms", "unsloth", "ollama", "openrouter", "openai")

# The engines that bill someone. Used only to print a warning — which engine runs is
# the caller's decision and this script does not second-guess it. It exists so that
# turning one on is never something you discover from an invoice.
PAID = frozenset({"openrouter", "openai"})


def endpoints_for(engine: str) -> list[Endpoint]:
    """Load `<engine>.py` and return its ENDPOINTS list."""
    return list(importlib.import_module(engine).ENDPOINTS)


def with_discovered(engine: str, manual: list[Endpoint]) -> list[Endpoint]:
    """Append every model the engine holds to the hand-written list.

    ADDITIVE, NEVER A REPLACEMENT. The hand-written endpoints come first and a
    discovered alias that collides with one is dropped, so `lms-4b` keeps meaning
    what it has always meant and turning discovery on can only ADD names. That
    matches what the LiteLLM side does by including `<engine>.yaml`.

    THE CREDENTIALS ARE COPIED FROM THE HAND-WRITTEN LIST rather than read from
    the environment a second time. `gateway.check_secrets` demands that one secret
    name mean one api_base + api_key pair, and copying is the only way this cannot
    drift from the file beside it and fail with an unhelpful message.

    The import is here and not at the top of the file because discovery is
    OPTIONAL machinery: with GATEWAY_DISCOVERY empty, `mlflow/` still runs with
    the whole `discover/` directory absent.
    """
    from gateway_discovery import check_word, discover

    check_word(env("GATEWAY_DISCOVERY"))
    template = manual[0]
    taken = {endpoint.name for endpoint in manual}
    extra = [
        Endpoint(
            name=model.alias,
            provider=template.provider,
            model=model.model_id,
            secret=template.secret,
            api_base=template.api_base,
            api_key=template.api_key,
        )
        for model in discover(engine)
        if model.alias not in taken
    ]
    print(f"discovery: {engine} holds {len(extra)} models not already named by config/{engine}.py")
    return manual + extra


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write one engine's endpoints into the MLflow AI Gateway.",
        epilog="The engine defaults from the environment, which is how compose passes it in.",
    )
    parser.add_argument(
        "--engine",
        default=env("GATEWAY_ENGINE", "lms"),
        help=f"which engine: {', '.join(ENGINES)} (default: $GATEWAY_ENGINE, else lms)",
    )
    parser.add_argument(
        "--tracking-uri",
        default=env("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI),
        help="MLflow server to seed (default: $MLFLOW_TRACKING_URI, else %(default)s)",
    )
    parser.add_argument("--reset", action="store_true", help="delete and rebuild every endpoint")
    parser.add_argument("--prune", action="store_true", help="ALSO delete endpoints this run does not name")
    args = parser.parse_args(argv)

    # Checked by hand rather than with argparse `choices`, because a default that
    # came from the environment is never validated against choices — and the
    # environment is exactly where the typo comes from. Without this the failure is
    # a ModuleNotFoundError naming a file nobody meant to write.
    engine = args.engine.strip()
    if engine not in ENGINES:
        parser.error(
            f"--engine / GATEWAY_ENGINE is {args.engine!r}; it must be one of: {', '.join(ENGINES)}. "
            "One engine at a time — a list is not accepted."
        )

    endpoints = endpoints_for(engine)
    # THE THIRD WORD IN .env. Empty is the default and means the hand-written list
    # above is the whole vocabulary — exactly what this script did before.
    if env("GATEWAY_DISCOVERY").strip():
        try:
            endpoints = with_discovered(engine, endpoints)
        except (ValueError, RuntimeError, OSError) as error:
            # A dead engine, a missing key or a PAID engine. Failing here is the
            # point: seeding the hand-written list alone would leave 25000 serving
            # a shorter vocabulary than 24000, which is the drift this repo hates.
            print(f"discovery failed: {error}", file=sys.stderr)
            return 2
    print(f"seeding: engine={engine}  ->  {len(endpoints)} endpoints declared")

    if engine in PAID:
        print(f"  PAID ENGINE: {engine} — every endpoint below bills a real account.")

    if args.prune:
        print(
            "  WARNING: --prune deletes every endpoint this run does not name, which is "
            "EVERY OTHER ENGINE'S — see the header."
        )

    return seed(
        endpoints,
        reset=args.reset,
        prune=args.prune,
        tracking_uri=args.tracking_uri,
    )


if __name__ == "__main__":
    sys.exit(main())

# THE HOSTED PROVIDERS ARE ENGINE FILES, not a commented-out block beside the settings.
# They became `openrouter.py` and `openai.py` on 2026-08-31, because an engine is an
# engine whether the GPU is yours or someone else's, and GATEWAY_ENGINE is the one
# property that decides which one runs. The old names went with them: `cheap`,
# `standard`, `frontier`, `cheap-free` and `standard-hf` named a tier rather than a
# vendor, so a caller could not tell who answered or who was billed.
#
# NO ENDPOINT HERE HAS A FALLBACK CHAIN, hosted or local. An alias names one route: a
# local one fails rather than quietly leaving the machine and billing you, and a hosted
# one fails rather than quietly becoming a different model. `Endpoint.fallbacks` still
# works and is still wired through — it is simply unused, which is a choice this repo
# makes rather than a feature it lacks.
