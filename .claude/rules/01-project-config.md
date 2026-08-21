---
description: Project configuration — architecture, paths, dev environment
---

# Project Config

- **Project**: ai-gateway — the machine-wide LLM gateway: one OpenAI-compatible
  endpoint that every project on this laptop calls, so switching provider or
  model is a change *here* rather than in each repo.
- **Architecture**: two containers in one compose project (`name: ai-gateway`,
  so containers are `ai-gateway-<service>-N`). `litellm` runs the stock
  `ghcr.io/berriai/litellm:main-stable` and publishes `24000:4000`; `postgres:17`
  holds virtual keys, teams, spend logs and budget ceilings and publishes
  **nothing** — only litellm reaches it, over the compose network.
- **Structure**: `compose.yml` (services, ports, healthchecks, env),
  `litellm/config.yaml` (aliases, prices, fallback chains, provider pins),
  `README.md` (start here), `NOTES.md` (driving this gateway from Claude Code).
  There is **no application code** — a change in this repo is a config change.
- **Build**: none. Both images are stock, so `up -d` needs no build step. A
  `litellm/Dockerfile` returns only when a callback needs a package the base
  image lacks.
- **Run locally**: `podman compose up -d` (or `docker compose up -d`) →
  <http://localhost:24000>, admin UI at `/ui`
- **Test**: no suite exists. Verification is the health route plus one real
  completion — `rules/06-testing.md`.
- **Key dependencies**: LiteLLM `main-stable`, Postgres 17, **LMStudio running
  natively on the host** (the free aliases), and OpenRouter / OpenAI /
  HuggingFace (the priced aliases and fallbacks).
- **Package manager**: none — this repo carries no language manifest.

## Services and ports

| Service | Image | Host | Notes |
|:--|:--|:--|:--|
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | `24000` → container `4000` | the endpoint; admin UI at `/ui`; `/v1/messages` alongside the OpenAI routes |
| `postgres` | `docker.io/postgres:17` | **not published** | virtual keys, spend logs, budget ceilings. Shell: `podman compose exec postgres psql -U postgres` |

`24000` is a deliberate third band. Two other stacks on this machine hold ports,
and the failure being avoided is not a loud bind error but the silent one — a
health probe against `localhost:4000` that a *different* project's gateway
answers, going green:

| Stack | Band |
|:--|:--|
| `~/Projects/Github/lukaskellerstein/mlflow-tutorial` | 3000, 4000, 5432, 5555, 6333/4, 7233, 8080, 9090 |
| `~/Projects/Github/lukaskellerstein/ai-agent-platform` | 1xxxx — 14000, 15000 |
| `ai-gateway` (this repo) | 2xxxx — 24000 |

Container-internal ports are unchanged; on the compose network nothing can
collide.

## Aliases are the vocabulary

Callers name an **alias**, never a model — the model behind an alias is expected
to change. `litellm/config.yaml` is the authority; `README.md` has the table.

- **Tiers** — pick one per call: `local`, `cheap`, `standard`, `frontier`.
- **Roles** — asked for by *shape*, not price point: `embed`, `uncensored`,
  `local-31b` (the dense 31B on the host GPU — `standard`'s weights, run here).
- **Not vocabulary**: `cheap-free` and `standard-hf` are fallback targets only.
  Do not tell a caller to use them. `local-31b` looks like one of these and is
  not — it is a name callers are meant to use.

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
