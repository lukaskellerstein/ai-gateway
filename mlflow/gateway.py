#!/usr/bin/env python
"""The MLflow AI Gateway seeder — machinery only, with no endpoint list of its own.

MLflow's gateway has NO CONFIG FILE. LiteLLM re-reads a YAML file at every boot;
MLflow cannot, because its endpoints live in the tracking database and arrive
over an API. So the thing that plays the part of a config file in this repo is
Python, and it is split the same way LiteLLM's YAML is — one file per engine per
list, with the CLI that picks two of them on top:

    seed.py            the entry point: reads GATEWAY_MODELS and GATEWAY_ENGINE
    starter/lms.py     starter/unsloth.py    starter/ollama.py     2 endpoints each
    full/lms.py        full/unsloth.py       full/ollama.py        12 / 4 / 4

Each of those six declares `ENDPOINTS` and nothing else. THIS FILE EXISTS SO THE
API CALLS ARE WRITTEN ONCE: a fix to the seeding logic is made here and every
list gets it, rather than drifting between copies.

Nothing in this directory reads any LiteLLM file. Delete the `litellm/` directory
and the `litellm` service and the seed still works — verified 2026-08-28 by
running the stack with `litellm` stopped, which left 24000 refusing connections
while 25000 kept serving. The cost of that independence is that the same aliases
are written twice, once per gateway; `tests/` is what catches them disagreeing.

One `Endpoint` becomes three MLflow objects:

    secret            the credential + base URL      one per provider account
      |
    model definition  provider + the real model id   one per DISTINCT model
      |
    endpoint          the alias a caller names       one per Endpoint

compose runs `seed.py` after `mlflow` reports healthy, on every `up -d`. It is
idempotent: existing objects are reused, and every secret is rewritten on each
run, so a rotated provider key reaches the gateway with no manual step.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

import mlflow
from mlflow.entities import (
    FallbackConfig,
    FallbackStrategy,
    GatewayEndpointModelConfig,
    GatewayModelLinkageType,
)
from mlflow.tracking._tracking_service.utils import _get_store

DEFAULT_TRACKING_URI = "http://mlflow:5000"


def env(name: str, default: str = "") -> str:
    """Read NAME from the environment.

    The defaults the engine files pass are the compose values, so a run straight
    from the host — `python mlflow/seed.py` — still reaches the same engines
    instead of silently seeding endpoints with a blank base URL.
    """
    return os.environ.get(name) or default


def slug(text: str) -> str:
    """MLflow accepts letters, digits, dot, dash and underscore in a name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")


@dataclass
class Endpoint:
    """One alias, and everything MLflow needs to serve it.

    `provider` is an MLflow provider name, and it means "speaks this protocol",
    not "is this company". All three local engines are `openai`, because api_base
    is the only thing separating LMStudio from api.openai.com.

    `secret` names the credential this endpoint uses. Endpoints that share a
    provider account share one name — `lmstudio`, `unsloth`, `ollama` — and MLflow
    then stores one secret for all of them. It is declared rather than derived
    because the derived name was wrong in the common case: an Unsloth key would
    have been filed under `openai`.
    """

    name: str
    provider: str
    model: str
    secret: str
    api_base: str = ""  # "" when the provider's own default URL is right
    api_key: str = ""
    fallbacks: list[str] = field(default_factory=list)

    @property
    def definition(self) -> str:
        """The model-definition name. Two aliases on one model share one."""
        return f"{self.secret}-{slug(self.model)}"


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def check_secrets(endpoints: list[Endpoint]) -> None:
    """One secret name must mean one credential and one base URL.

    Two endpoints sharing a name but not a key would otherwise store whichever
    was read last, and the other alias would then answer 401 with nothing in the
    log to explain it. Fail here instead, where the line number is right there.
    """
    seen: dict[str, tuple[str, str]] = {}
    for endpoint in endpoints:
        pair = (endpoint.api_base, endpoint.api_key)
        if seen.setdefault(endpoint.secret, pair) != pair:
            raise ValueError(
                f"secret '{endpoint.secret}' is used with two different "
                f"api_base/api_key pairs — '{endpoint.name}' disagrees with an "
                f"earlier endpoint. Give one of them its own secret name."
            )


def usable(endpoints: list[Endpoint]) -> tuple[list[Endpoint], list[str]]:
    """Split the list into endpoints that can be seeded and the reasons for the rest."""
    keep: list[Endpoint] = []
    skipped: list[str] = []
    for endpoint in endpoints:
        if not endpoint.api_key:
            # Creating a secret with no key builds an endpoint that 401s at call
            # time. Unsloth is the case that hits: its key is personal, arrives
            # from the shell, and is blank on a machine that has not set it.
            skipped.append(f"{endpoint.name}: no API key in the environment")
            continue
        keep.append(endpoint)
    return keep, skipped


def apply_secrets(store, endpoints: list[Endpoint]) -> dict[str, str]:
    """Create or refresh one secret per provider account. Returns name -> id."""
    existing = {s.secret_name: s.secret_id for s in store.list_secret_infos()}
    wanted = {e.secret: e for e in endpoints}
    built: dict[str, str] = {}

    for name, endpoint in wanted.items():
        # The base URL belongs in auth_config. Put it in secret_value and MLflow
        # ignores it without a word — the server then calls the provider's own
        # API and reports an auth failure about a key it never sent.
        auth_config = {"api_base": endpoint.api_base} if endpoint.api_base else {}
        if name in existing:
            # Rewritten rather than reused: the seed runs on every `up -d`, so a
            # key rotated in ~/.secrets reaches the gateway without a manual step.
            store.update_gateway_secret(
                secret_id=existing[name],
                secret_value={"api_key": endpoint.api_key},
                auth_config=auth_config,
            )
            built[name] = existing[name]
            print(f"  {name:12s} refreshed  provider={endpoint.provider}")
            continue
        secret = store.create_gateway_secret(
            secret_name=name,
            secret_value={"api_key": endpoint.api_key},
            provider=endpoint.provider,
            auth_config=auth_config,
        )
        built[name] = secret.secret_id
        print(f"  {name:12s} created    provider={endpoint.provider}  ->  {endpoint.api_base or 'provider default'}")
    return built


def apply_definitions(store, endpoints: list[Endpoint], secret_ids: dict[str, str]) -> dict[str, str]:
    """Create one model definition per distinct model. Returns name -> id."""
    existing = {d.name: d.model_definition_id for d in store.list_gateway_model_definitions()}
    built: dict[str, str] = {}

    for endpoint in endpoints:
        if endpoint.definition in built:
            continue  # several aliases share this model — that is the point
        if endpoint.definition in existing:
            built[endpoint.definition] = existing[endpoint.definition]
            print(f"  {endpoint.definition:46s} reused")
            continue
        definition = store.create_gateway_model_definition(
            name=endpoint.definition,
            secret_id=secret_ids[endpoint.secret],
            provider=endpoint.provider,
            model_name=endpoint.model,
        )
        built[endpoint.definition] = definition.model_definition_id
        print(f"  {endpoint.definition:46s} created  ->  {endpoint.model}")
    return built


def apply_endpoints(
    store,
    endpoints: list[Endpoint],
    definition_ids: dict[str, str],
    reset: bool,
) -> list[tuple[str, str, str]]:
    """Create one endpoint per alias. Returns (alias, chain, status) per alias."""
    existing = {e.name: e.endpoint_id for e in store.list_gateway_endpoints()}
    alias_to_definition = {e.name: e.definition for e in endpoints}
    rows: list[tuple[str, str, str]] = []

    for endpoint in endpoints:
        chain_names = [endpoint.definition]
        if endpoint.name in existing and not reset:
            print(f"  {endpoint.name:14s} reused  (--reset to rebuild)")
            rows.append((endpoint.name, "reused", "reused"))
            continue
        if endpoint.name in existing:
            store.delete_gateway_endpoint(existing[endpoint.name])

        primary_id = definition_ids[endpoint.definition]
        seen = {primary_id}
        configs = [
            GatewayEndpointModelConfig(
                model_definition_id=primary_id,
                linkage_type=GatewayModelLinkageType.PRIMARY,
                weight=1,
                fallback_order=0,
            )
        ]
        # A fallback names another ALIAS, which is how a reader thinks about it.
        # MLflow chains MODELS inside the endpoint, so each hop is resolved to the
        # model behind that alias here.
        for hop in endpoint.fallbacks:
            hop_id = definition_ids.get(alias_to_definition.get(hop, ""))
            if hop_id is None or hop_id in seen:
                continue
            seen.add(hop_id)
            chain_names.append(alias_to_definition[hop])
            configs.append(
                GatewayEndpointModelConfig(
                    model_definition_id=hop_id,
                    linkage_type=GatewayModelLinkageType.FALLBACK,
                    weight=1,
                    fallback_order=len(configs),
                )
            )

        store.create_gateway_endpoint(
            name=endpoint.name,
            model_configs=configs,
            # WITHOUT THIS THE FALLBACKS NEVER FIRE. A FALLBACK linkage is stored,
            # and shown in the UI, whether or not this is passed — but the gateway
            # only wraps the primary in a fallback provider when the config object
            # is there. Leave it out and the chain looks right everywhere but in
            # production.
            fallback_config=(FallbackConfig(strategy=FallbackStrategy.SEQUENTIAL) if len(configs) > 1 else None),
            # Every request becomes a trace in an auto-created `gateway/<alias>`
            # experiment. It is the one thing this gateway does that LiteLLM
            # cannot do without an external trace store.
            usage_tracking=True,
        )
        chain = " -> ".join(chain_names)
        print(f"  {endpoint.name:14s} created  {chain}")
        rows.append((endpoint.name, chain, "created"))
    return rows


def report_extras(store, endpoints: list[Endpoint], prune: bool) -> None:
    """Endpoints MLflow holds that this seed script does not name."""
    wanted = {e.name for e in endpoints}
    extras = [e for e in store.list_gateway_endpoints() if e.name not in wanted]
    if not extras:
        print("  none — MLflow holds exactly the endpoints this script names")
        return
    for endpoint in extras:
        if prune:
            store.delete_gateway_endpoint(endpoint.endpoint_id)
            print(f"  {endpoint.name:14s} DELETED  (--prune)")
        else:
            print(f"  {endpoint.name:14s} not in this script — left alone (--prune removes it)")


def seed(
    endpoints: list[Endpoint],
    *,
    reset: bool = False,
    prune: bool = False,
    tracking_uri: str = DEFAULT_TRACKING_URI,
) -> int:
    """Write `endpoints` into the MLflow AI Gateway. `seed.py` calls this.

    The command line lives in `seed.py`, not here: this file talks to MLflow and
    knows nothing about which list or which engine a caller chose.
    """
    check_secrets(endpoints)
    wanted, skipped = usable(endpoints)
    print(f"{len(endpoints)} endpoints declared  ->  {len(wanted)} to seed, {len(skipped)} skipped")
    if not wanted:
        print("nothing to seed: every endpoint was skipped", file=sys.stderr)
        for reason in skipped:
            print(f"  {reason}", file=sys.stderr)
        return 1

    mlflow.set_tracking_uri(tracking_uri)
    store = _get_store()

    section("Step 1: secrets  (one per provider account)")
    secret_ids = apply_secrets(store, wanted)

    section("Step 2: model definitions  (one per distinct model)")
    definition_ids = apply_definitions(store, wanted, secret_ids)

    section("Step 3: endpoints  (one per alias)")
    rows = apply_endpoints(store, wanted, definition_ids, reset)

    section("Step 4: endpoints this run does not name")
    report_extras(store, wanted, prune)

    if skipped:
        section("Skipped, and why")
        for reason in skipped:
            print(f"  {reason}")

    created = sum(1 for _, _, status in rows if status == "created")
    print(
        f"\ndone: {len(secret_ids)} secrets, {len(definition_ids)} model definitions, "
        f"{len(rows)} endpoints ({created} created this run)"
    )
    print(f"call one:  POST {tracking_uri}/gateway/mlflow/v1/chat/completions  with  \"model\": \"{rows[0][0]}\"")
    return 0
