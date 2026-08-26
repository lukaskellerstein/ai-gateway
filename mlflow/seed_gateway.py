#!/usr/bin/env python
"""Seed the MLflow AI Gateway from litellm/config.yaml.

LiteLLM reads its aliases from a file at every boot. MLflow cannot: its gateway
configuration lives in the tracking database and is reachable only through an
API. So this repo has no `mlflow/config.yaml` to sit beside `litellm/config.yaml`
— it has this script, which reads that file and writes the same aliases into
MLflow.

Reading LiteLLM's own file, instead of keeping a second list here, is the whole
point. A second list drifts, and the drift is silent: an alias answers on one
gateway and 404s on the other, with nothing to say why.

One LiteLLM entry becomes three MLflow objects:

    secret            the credential + base URL      one per provider account
      |
    model definition  provider + the real model id   one per DISTINCT model
      |
    endpoint          the alias a caller names       one per model_name

compose runs this after `mlflow` reports healthy, on every `up -d`. It is
idempotent: existing objects are reused, and every secret is rewritten on each
run, so a rotated provider key reaches the gateway with no manual step.

Usage:
    python seed_gateway.py [path/to/litellm/config.yaml] [--reset] [--prune]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import mlflow
import yaml
from mlflow.entities import (
    FallbackConfig,
    FallbackStrategy,
    GatewayEndpointModelConfig,
    GatewayModelLinkageType,
)
from mlflow.tracking._tracking_service.utils import _get_store

# LiteLLM provider prefix -> MLflow provider name. `lm_studio` becomes `openai`
# because a provider name here means "speaks the OpenAI protocol", not "is
# OpenAI" — api_base is the only thing separating LMStudio from api.openai.com.
#
# A prefix that is absent is reported and skipped, never guessed at. `huggingface`
# is the one this repo can hit: MLflow's nearest provider is text-generation-
# inference, which is a different API from the HF router that `standard-hf` uses.
PROVIDERS = {
    "lm_studio": "openai",
    "openrouter": "openrouter",
    "openai": "openai",
}

DEFAULT_CONFIG = "/app/litellm-config.yaml"
DEFAULT_TRACKING_URI = "http://mlflow:5000"


@dataclass
class Route:
    """One `model_list` entry, already resolved into MLflow's three objects."""

    alias: str  # the name callers use -> becomes an endpoint
    provider: str  # MLflow provider name
    model: str  # upstream model id, LiteLLM's prefix stripped
    api_key: str
    api_base: str  # "" when the provider's own default URL is right
    secret: str  # secret name
    definition: str  # model definition name


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def resolve_env(value: object) -> str:
    """`os.environ/NAME` in a LiteLLM config means "read NAME from the environment"."""
    text = str(value or "")
    if text.startswith("os.environ/"):
        return os.environ.get(text.split("/", 1)[1], "")
    return text


def slug(text: str) -> str:
    """MLflow accepts letters, digits, dot, dash and underscore in a name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")


def load_routes(path: Path) -> tuple[list[Route], dict[str, list[str]], list[str]]:
    """Parse litellm/config.yaml into routes, fallback chains and skip reasons."""
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    routes: list[Route] = []
    skipped: list[str] = []
    # (prefix, api_base, api_key) -> secret name. Keyed on all three so two
    # accounts at one provider, or two LMStudio hosts, become two secrets rather
    # than one that silently takes whichever entry was read last.
    secret_names: dict[tuple[str, str, str], str] = {}

    for entry in document.get("model_list") or []:
        alias = str(entry.get("model_name") or "")
        params = entry.get("litellm_params") or {}
        info = entry.get("model_info") or {}
        prefix, _, model = str(params.get("model") or "").partition("/")

        if not alias or not model:
            skipped.append(f"{alias or '<unnamed>'}: no model_name or no model")
            continue
        if prefix not in PROVIDERS:
            skipped.append(f"{alias}: LiteLLM provider '{prefix}' has no MLflow equivalent")
            continue

        api_key = resolve_env(params.get("api_key"))
        api_base = resolve_env(params.get("api_base"))
        if not api_key:
            # config.yaml treats a provider as optional in the same way: it is
            # needed only by the aliases that route to it. Creating a secret with
            # no key would build an endpoint that fails with a 401 at call time.
            skipped.append(f"{alias}: no API key in the environment")
            continue

        key = (prefix, api_base, api_key)
        if key not in secret_names:
            # The provider prefix is a poor secret name whenever it means "speaks
            # the OpenAI protocol" rather than "is OpenAI" — an Unsloth account
            # would land in MLflow as a secret called `openai`, and the real
            # OpenAI would then be pushed to `openai-2` by the loop below.
            # `model_info.mlflow_secret_name` in config.yaml overrides it.
            base = str(info.get("mlflow_secret_name") or "") or ("lmstudio" if prefix == "lm_studio" else prefix)
            name, suffix = base, 2
            while name in secret_names.values():
                name, suffix = f"{base}-{suffix}", suffix + 1
            secret_names[key] = name
        secret = secret_names[key]

        routes.append(
            Route(
                alias=alias,
                provider=PROVIDERS[prefix],
                model=model,
                api_key=api_key,
                api_base=api_base,
                secret=secret,
                definition=f"{secret}-{slug(model)}",
            )
        )

    # LiteLLM writes fallbacks as a list of one-key maps: {"local": ["cheap"]}.
    fallbacks: dict[str, list[str]] = {}
    for pair in (document.get("litellm_settings") or {}).get("fallbacks") or []:
        fallbacks.update(pair)

    return routes, fallbacks, skipped


def apply_secrets(store, routes: list[Route]) -> dict[str, str]:
    """Create or refresh one secret per provider account. Returns name -> id."""
    existing = {s.secret_name: s.secret_id for s in store.list_secret_infos()}
    wanted = {r.secret: r for r in routes}
    built: dict[str, str] = {}

    for name, route in wanted.items():
        # The base URL belongs in auth_config. Put it in secret_value and MLflow
        # ignores it without a word — the server then calls the provider's own
        # API and reports an auth failure about a key it never sent.
        auth_config = {"api_base": route.api_base} if route.api_base else {}
        if name in existing:
            # Rewritten rather than reused: the seed runs on every `up -d`, so a
            # key rotated in ~/.secrets reaches the gateway without a manual step.
            store.update_gateway_secret(
                secret_id=existing[name],
                secret_value={"api_key": route.api_key},
                auth_config=auth_config,
            )
            built[name] = existing[name]
            print(f"  {name:12s} refreshed  provider={route.provider}")
            continue
        secret = store.create_gateway_secret(
            secret_name=name,
            secret_value={"api_key": route.api_key},
            provider=route.provider,
            auth_config=auth_config,
        )
        built[name] = secret.secret_id
        print(f"  {name:12s} created    provider={route.provider}  ->  {route.api_base or 'provider default'}")
    return built


def apply_definitions(store, routes: list[Route], secret_ids: dict[str, str]) -> dict[str, str]:
    """Create one model definition per distinct model. Returns name -> id."""
    existing = {d.name: d.model_definition_id for d in store.list_gateway_model_definitions()}
    built: dict[str, str] = {}

    for route in routes:
        if route.definition in built:
            continue  # several aliases share this model — that is the point
        if route.definition in existing:
            built[route.definition] = existing[route.definition]
            print(f"  {route.definition:46s} reused")
            continue
        definition = store.create_gateway_model_definition(
            name=route.definition,
            secret_id=secret_ids[route.secret],
            provider=route.provider,
            model_name=route.model,
        )
        built[route.definition] = definition.model_definition_id
        print(f"  {route.definition:46s} created  ->  {route.model}")
    return built


def apply_endpoints(
    store,
    routes: list[Route],
    definition_ids: dict[str, str],
    fallbacks: dict[str, list[str]],
    reset: bool,
) -> list[tuple[str, str, str]]:
    """Create one endpoint per alias. Returns (alias, chain, status) per alias."""
    existing = {e.name: e.endpoint_id for e in store.list_gateway_endpoints()}
    alias_to_definition = {r.alias: r.definition for r in routes}
    rows: list[tuple[str, str, str]] = []

    for route in routes:
        chain_names = [route.definition]
        if route.alias in existing and not reset:
            print(f"  {route.alias:14s} reused  (--reset to rebuild)")
            rows.append((route.alias, "reused", "reused"))
            continue
        if route.alias in existing:
            store.delete_gateway_endpoint(existing[route.alias])

        primary_id = definition_ids[route.definition]
        seen = {primary_id}
        configs = [
            GatewayEndpointModelConfig(
                model_definition_id=primary_id,
                linkage_type=GatewayModelLinkageType.PRIMARY,
                weight=1,
                fallback_order=0,
            )
        ]
        # LiteLLM chains ALIASES in a separate block; MLflow chains MODELS inside
        # the endpoint. So each hop is resolved to the model behind that alias.
        for hop in fallbacks.get(route.alias, []):
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
            name=route.alias,
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
        print(f"  {route.alias:14s} created  {chain}")
        rows.append((route.alias, chain, "created"))
    return rows


def report_extras(store, routes: list[Route], prune: bool) -> None:
    """Endpoints MLflow holds that litellm/config.yaml no longer names."""
    wanted = {r.alias for r in routes}
    extras = [e for e in store.list_gateway_endpoints() if e.name not in wanted]
    if not extras:
        print("  none — MLflow holds exactly the aliases LiteLLM serves")
        return
    for endpoint in extras:
        if prune:
            store.delete_gateway_endpoint(endpoint.endpoint_id)
            print(f"  {endpoint.name:14s} DELETED  (--prune)")
        else:
            print(f"  {endpoint.name:14s} not in config.yaml — left alone (--prune removes it)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default=DEFAULT_CONFIG, help="path to litellm/config.yaml")
    parser.add_argument("--reset", action="store_true", help="delete and rebuild every endpoint")
    parser.add_argument("--prune", action="store_true", help="delete endpoints config.yaml no longer names")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"config not found: {config_path}", file=sys.stderr)
        return 1

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    mlflow.set_tracking_uri(tracking_uri)
    store = _get_store()

    routes, fallbacks, skipped = load_routes(config_path)
    print(f"read {config_path}  ->  {len(routes)} routes, {len(fallbacks)} fallback chains")
    if not routes:
        print("nothing to seed: every model_list entry was skipped", file=sys.stderr)
        for reason in skipped:
            print(f"  {reason}", file=sys.stderr)
        return 1

    section("Step 1: secrets  (LiteLLM: os.environ/... in litellm_params)")
    secret_ids = apply_secrets(store, routes)

    section("Step 2: model definitions  (LiteLLM: one model_list entry per alias)")
    definition_ids = apply_definitions(store, routes, secret_ids)

    section("Step 3: endpoints  (LiteLLM: model_name + litellm_settings.fallbacks)")
    rows = apply_endpoints(store, routes, definition_ids, fallbacks, args.reset)

    section("Step 4: endpoints LiteLLM does not serve")
    report_extras(store, routes, args.prune)

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


if __name__ == "__main__":
    sys.exit(main())
