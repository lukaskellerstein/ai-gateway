---
description: Project configuration — architecture, paths, dev environment
---

# Project Config

- **Project**: ai-gateway — the machine-wide LLM gateway: one OpenAI-compatible
  endpoint that every project on this laptop calls, so switching provider or
  model is a change *here* rather than in each repo.
- **Architecture**: four containers in one compose project (`name: ai-gateway`,
  so containers are `ai-gateway-<service>-N`). `litellm` runs the stock
  `ghcr.io/berriai/litellm:main-stable` and publishes `24000:4000`; `postgres:17`
  holds two databases — `litellm` (virtual keys, teams, spend logs, budget
  ceilings) and `mlflow` (gateway endpoints, traces) — and publishes **nothing**;
  `mlflow` runs the stock `ghcr.io/mlflow/mlflow:latest` and publishes
  `25000:5000`; `mlflow-seed` runs once and exits.
- **Structure**: `compose.yml` (services, ports, healthchecks, env),
  `litellm/config.yaml` (aliases, prices, fallback chains, provider pins),
  `mlflow/seed_gateway.py` (that config.yaml, applied to the MLflow gateway),
  `postgres/init-databases.sh` (the `mlflow` database, fresh volumes only),
  `tests/` (three scripts that drive **both** gateways through the OpenAI
  client), `README.md` (start here), `NOTES.md` (driving this gateway from Claude
  Code). Outside `tests/`, `mlflow/seed_gateway.py` is the **only** code —
  everything else is a config change.
- **Build**: none. All three images are stock, so `up -d` needs no build step.
  The MLflow image already ships `psycopg2` and `cryptography`. A
  `litellm/Dockerfile` returns only when a callback needs a package the base
  image lacks.
- **Run locally**: `podman compose up -d` (or `docker compose up -d`) →
  <http://localhost:24000>, admin UI at `/ui`; MLflow at
  <http://localhost:25000>.
- **Test**: `cd tests && uv sync && uv run run_all.py` — three call kinds (plain,
  tools, multimodal) against **both** gateways, six rows, exit `1` on any
  failure. It needs the stack up and the alias loaded in LMStudio; it is not a
  substitute for the health route and the alias-specific completion in
  `rules/06-testing.md`. A `litellm/config.yaml` change must be proved on both
  gateways, because `mlflow-seed` copies that file.
- **Key dependencies**: LiteLLM `main-stable`, MLflow `latest` (3.15.1 at the
  time of writing), Postgres 17, **LMStudio running natively on the host** (the
  free aliases), and OpenRouter / OpenAI / HuggingFace (the priced aliases and
  fallbacks).
- **Package manager**: `uv`, and **only inside `tests/`** — that folder is the
  one place with a language manifest (`tests/pyproject.toml`, Python 3.12,
  `openai` + `python-dotenv`). The repo root still carries none.

## Services and ports

| Service | Image | Host | Notes |
|:--|:--|:--|:--|
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | `24000` → container `4000` | **the primary endpoint**; admin UI at `/ui`; `/v1/messages` alongside the OpenAI routes |
| `postgres` | `docker.io/postgres:17` | **not published** | databases `litellm` and `mlflow`. Shell: `podman compose exec postgres psql -U postgres` |
| `mlflow` | `ghcr.io/mlflow/mlflow:latest` | `25000` → container `5000` | the same aliases through the MLflow AI Gateway; UI at `/`, gateway under `/gateway`. **No key, and no `/v1/messages`** |
| `mlflow-seed` | `ghcr.io/mlflow/mlflow:latest` | — | one-shot: reads `litellm/config.yaml` into MLflow, then exits 0. Exited **is** the finished state |

`24000` and `25000` are a deliberate third band. Two other stacks on this machine
hold ports, and the failure being avoided is not a loud bind error but the silent
one — a health probe against `localhost:4000` that a *different* project's
gateway answers, going green:

| Stack | Band |
|:--|:--|
| `~/Projects/Github/lukaskellerstein/mlflow-tutorial` | 3000, 4000, 5432, 5555, 6333/4, 7233, 8080, 9090 |
| `~/Projects/Github/lukaskellerstein/ai-agent-platform` | 1xxxx — 14000, 15000 |
| `ai-gateway` (this repo) | 2xxxx — 24000, 25000 |

`mlflow-tutorial` runs its own MLflow on `5555` and its own LiteLLM on `4000`.
That stack is a *different* set of aliases (`gemma-chat`, `gemma-judge`, ...) and
nothing here talks to it.

Container-internal ports are unchanged; on the compose network nothing can
collide.

## Aliases are the vocabulary

Callers name an **alias**, never a model — the model behind an alias is expected
to change. `litellm/config.yaml` is the authority for **both** gateways:
`mlflow-seed` reads that same file and creates one MLflow endpoint per
`model_name`, so an alias added there appears on `25000` after the next `up -d`.
`README.md` has the table.

- **Tiers** — pick one per call: `local`, `cheap`, `standard`, `frontier`.
- **Roles** — asked for by *shape*, not price point: `embed`, `uncensored`,
  `local-31b` (the dense 31B on the host GPU — `standard`'s weights, run here).
- **Engines** — `unsloth-31b` and `unsloth-26b` are the same weights as
  `local-31b` and `local`, run by **Unsloth Studio on port 8888** instead of
  LMStudio on 1234. The alias names the engine because the engine is the only
  difference, and comparing the two is the only reason they exist.
- **Not vocabulary**: `cheap-free` and `standard-hf` are fallback targets only.
  Do not tell a caller to use them. `local-31b` looks like one of these and is
  not — it is a name callers are meant to use, and so is every `unsloth-*`.

Two properties of this config that look like bugs and are not:

- **`local` is not guaranteed to stay local.** It falls back
  `local → cheap-free → cheap` when LMStudio is unreachable, landing on the same
  weights at OpenRouter. A "free" session can therefore accrue real spend.
  `uncensored` and `local-31b` are the aliases with **no fallback**, deliberately
  — `uncensored` fails rather than routing a prompt to a hosted model that would
  see it and refuse; `local-31b` fails so that the name always means "on this
  machine, free" (its hosted twin is simply `standard`, for callers who want it).
- **`local` is shadow-priced** — free on this machine but carrying its
  OpenRouter twin's rate, so budget ceilings can actually trip. Anything summing
  `/spend/logs` must say whether it is reporting money billed or the cost of the
  same workload on the cloud twin.
