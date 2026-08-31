#!/usr/bin/env python
"""MLflow AI Gateway — the seeder's entry point. It picks a list and an engine, and writes.

MLflow's gateway has NO CONFIG FILE: its endpoints live in the tracking database
and arrive over an API. So this gateway's alias list is Python, split exactly the
way LiteLLM's YAML is — one file per engine per list:

              starter (2 each)      full
    LMStudio  starter/lms.py        full/lms.py         12 aliases
    Unsloth   starter/unsloth.py    full/unsloth.py      4 aliases
    Ollama    starter/ollama.py     full/ollama.py       4 aliases

TWO WORDS FROM `.env` PICK WHAT RUNS, and they are the same two words that pick
LiteLLM's composed config file, so the gateways cannot end up on different lists:

    GATEWAY_MODELS   starter | full            default starter
    GATEWAY_ENGINE   lms | unsloth | ollama | all      default all

    GATEWAY_MODELS=full + GATEWAY_ENGINE=unsloth  ->  full/unsloth.py, 4 endpoints
    both unset                                    ->  all three starter files, 6

compose runs this on every `up -d`, after `mlflow` reports healthy, and it is
idempotent. Run it by hand against the published port:

    python mlflow/seed.py --tracking-uri http://localhost:25000
    python mlflow/seed.py --models full --engine ollama
    python mlflow/seed.py --reset        # rebuild every endpoint it names
    python mlflow/seed.py --prune        # ALSO delete every endpoint it does not

---------------------------------------------------------------------------
READ THIS BEFORE `--prune`. It deletes every endpoint this run does not name —
which now includes THE OTHER ENGINES. `--engine ollama --prune` removes every
`lms-*` and `unsloth-*` endpoint MLflow holds, and the `gateway/*` traces then
point at endpoints that no longer exist. Without `--prune` the extras are left
alone and merely listed, which is why switching engine or list leaves the old
names still answering on 25000.

NOTHING HERE READS ANYTHING FROM LiteLLM, and that is deliberate. It used to
parse `litellm/config.yaml`, which meant MLflow could not run without LiteLLM.
The cost of the split is that the two alias lists are maintained twice: add a
model in `mlflow/<list>/<engine>.py` AND in `litellm/<list>/<engine>.yaml`, or
the name answers on one port and 404s on the other.

WHAT MLFLOW HAS NO PLACE FOR, so it is absent rather than lost: prices,
`max_tokens`, context windows and per-route timeouts. MLflow carries one global
timeout, set as MLFLOW_GATEWAY_ROUTE_TIMEOUT_SECONDS in compose.yml. There are no
virtual keys, no spend logs and no budget ceilings here at all — which is why
LiteLLM stays the primary gateway. README.md § The MLflow gateway is the list.

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

MODELS = ("starter", "full")
ENGINES = ("lms", "unsloth", "ollama")


def endpoints_for(models: str, engine: str) -> list[Endpoint]:
    """Load `<models>/<engine>.py` — or all three engines — and return their lists."""
    wanted = ENGINES if engine == "all" else (engine,)
    chosen: list[Endpoint] = []
    for name in wanted:
        chosen.extend(importlib.import_module(f"{models}.{name}").ENDPOINTS)
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write one list of endpoints into the MLflow AI Gateway.",
        epilog="Both words default from the environment, which is how compose passes them in.",
    )
    parser.add_argument(
        "--models",
        default=env("GATEWAY_MODELS", "starter"),
        help="which alias list: starter or full (default: $GATEWAY_MODELS, else starter)",
    )
    parser.add_argument(
        "--engine",
        default=env("GATEWAY_ENGINE", "all"),
        help="which engine: lms, unsloth, ollama or all (default: $GATEWAY_ENGINE, else all)",
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
    # environment is exactly where the typo comes from. Without this the failure
    # is a ModuleNotFoundError naming a file nobody meant to write.
    if args.models not in MODELS:
        parser.error(f"--models / GATEWAY_MODELS is {args.models!r}; it must be one of: {', '.join(MODELS)}")
    if args.engine not in (*ENGINES, "all"):
        parser.error(f"--engine / GATEWAY_ENGINE is {args.engine!r}; it must be one of: {', '.join(ENGINES)}, all")

    endpoints = endpoints_for(args.models, args.engine)
    print(f"seeding: models={args.models}  engine={args.engine}  ->  {len(endpoints)} endpoints declared")
    if args.prune and args.engine != "all":
        print(
            f"  WARNING: --prune with one engine deletes every endpoint that is not {args.engine}-*, "
            "including the other engines' — see the header."
        )

    return seed(
        endpoints,
        reset=args.reset,
        prune=args.prune,
        tracking_uri=args.tracking_uri,
    )


if __name__ == "__main__":
    sys.exit(main())

# ---------------------------------------------------------------------------
# THE HOSTED TIERS — cloud, priced, and COMMENTED OUT, exactly as they are in
# litellm/settings.yaml. They live here rather than in an engine file because they
# belong to no engine: GATEWAY_ENGINE selects which LOCAL engine answers, and
# these are what you reach for when none of them should.
#
# To turn them on, add them to `endpoints_for`'s result — a `hosted.py` beside
# this file with its own ENDPOINTS list, loaded whatever the engine, is the
# smallest honest way — and uncomment the matching routes in litellm/settings.yaml
# so the two gateways still agree.
#
# READ THIS FIRST. LiteLLM pins `cheap-free` to one OpenRouter provider because
# another returns tool calls as raw text and an agent then executes nothing.
# MLflow has no equivalent of `extra_body`, so THAT PIN CANNOT BE EXPRESSED HERE
# and a `cheap-free` endpoint on 25000 is not the same route LiteLLM serves under
# that name. `standard-hf` is absent on purpose too: MLflow's nearest provider is
# text-generation-inference, a different API from the HuggingFace router LiteLLM
# uses. A LiteLLM feature with no MLflow equivalent is documented, not faked.
#
#   Endpoint(name="cheap", provider="openrouter",
#            model="google/gemma-4-26b-a4b-it",
#            secret="openrouter", api_key=env("OPENROUTER_API_KEY"),
#            fallbacks=["standard", "frontier"]),
#   Endpoint(name="standard", provider="openrouter",
#            model="google/gemma-4-31b-it",
#            secret="openrouter", api_key=env("OPENROUTER_API_KEY"),
#            fallbacks=["frontier"]),
#   Endpoint(name="cheap-free", provider="openrouter",
#            model="google/gemma-4-26b-a4b-it:free",
#            secret="openrouter", api_key=env("OPENROUTER_API_KEY"),
#            fallbacks=["cheap"]),
#   Endpoint(name="frontier", provider="openai",
#            model="gpt-5.4-mini",
#            secret="openai", api_key=env("OPENAI_API_KEY"),
#            fallbacks=["standard"]),
#
# NO LOCAL ENDPOINT GETS A FALLBACK CHAIN, in either gateway. These names promise
# "these weights, this engine, on this machine, free", and a hop to a hosted model
# breaks that promise at the worst moment. `lms-26b` is LiteLLM's single
# deliberate exception and it is commented out there too.
# ---------------------------------------------------------------------------
