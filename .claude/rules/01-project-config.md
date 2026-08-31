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
  `25000:5000`; `mlflow-seed` runs once and exits. **Both gateways carry compose
  profiles** (`litellm` / `mlflow`, plus `all` on both), so `COMPOSE_PROFILES`
  decides which of them runs; `postgres` has none and always starts. With no `.env`
  at all, `up -d` starts postgres alone.
- **Structure**: `compose.yml` (services, profiles, ports, healthchecks, env),
  `litellm/` (**gateway 1**: `settings.yaml` with the three settings blocks and the
  commented hosted tiers, `starter/<engine>.yaml` and `full/<engine>.yaml` with the
  aliases and prices, and eight `config.<models>.<engine>.yaml` that are nothing but
  `include:` lists), `mlflow/` (**gateway 2**, reading nothing from `litellm/`:
  `gateway.py` the API machinery, `seed.py` the CLI that picks a list and an engine,
  and the same six `<models>/<engine>.py` split), `postgres/init-databases.sh` (the
  `mlflow` database, fresh volumes only), `tests/` (three scripts that drive **both**
  gateways through the OpenAI client), `README.md` (start here, and the ONLY doc —
  aliases, quick start, tests, Claude Code, troubleshooting), `LICENSE` (MIT).
  Outside `tests/`, `mlflow/` is the **only** code — everything else is a config
  change.
- **Build**: none. All three images are stock, so `up -d` needs no build step.
  The MLflow image already ships `psycopg2` and `cryptography`. A
  `litellm/Dockerfile` returns only when a callback needs a package the base
  image lacks.
- **Run locally**: `podman compose up -d` (or `docker compose up -d`) →
  <http://localhost:24000>, admin UI at `/ui`; MLflow at
  <http://localhost:25000>. **Needs `COMPOSE_PROFILES` in `.env`** naming the
  gateways you want, or only postgres starts.
- **Test**: `cd tests && uv sync && uv run run_all.py` — three call kinds (plain,
  tools, multimodal) against **every gateway `COMPOSE_PROFILES` starts**, six rows
  with both, exit `1` on any failure. The default alias follows `GATEWAY_ENGINE`.
  It needs the stack up and the model loaded in that engine; it is not a
  substitute for the health route and the alias-specific completion in
  `rules/06-testing.md`. An alias change must be proved on both gateways, because
  each gateway now has its OWN list and the two can drift apart silently.
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
| `mlflow-seed` | `ghcr.io/mlflow/mlflow:latest` | — | one-shot: runs `mlflow/seed.py` with `GATEWAY_MODELS` and `GATEWAY_ENGINE` in its environment, then exits 0. Exited **is** the finished state |

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
to change. `README.md` has the table.

**EACH GATEWAY IS THE AUTHORITY FOR ITSELF, and neither reads the other**
(changed 2026-08-28). LiteLLM reads `litellm/<models>/<engine>.yaml`; MLflow's
endpoints live in `mlflow/<models>/<engine>.py`. That is what lets the whole
`litellm/` directory and the `litellm` service be deleted — or simply left out of
`COMPOSE_PROFILES` — with the MLflow gateway still serving. **The price is that an
alias is TWO edits, one per side** — do only one and the name answers on 24000 and
404s on 25000 with nothing in either log to say why.

**Every alias names its engine**, and that is the whole naming rule — there is no
engine-neutral name and there must not be one. A `local` alias existed until
2026-08-27 and was renamed `lms-26b` because it hid which of the three engines
answered, which is exactly the question this repo exists to make cheap to ask.

**THREE WORDS IN `.env` DECIDE WHAT RUNS** (2026-08-31), and they are independent:

| Variable | Values | Default | Picks |
|:--|:--|:--|:--|
| `COMPOSE_PROFILES` | `litellm`, `mlflow`, `litellm,mlflow`, `all` | *(nothing starts)* | which gateway runs |
| `GATEWAY_MODELS` | `starter`, `full` | `starter` | which alias list |
| `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `all` | `all` | which engine |

The last two name one file per gateway, and it is the same pair on both, so a
switch moves both at once:

| | LiteLLM (24000) | MLflow (25000) |
|:--|:--|:--|
| compose selects | `litellm/config.<models>.<engine>.yaml` | `mlflow/seed.py` + both words in its env |
| the aliases are in | `litellm/<models>/<engine>.yaml` | `mlflow/<models>/<engine>.py` |

A composed `config.<models>.<engine>.yaml` declares nothing: it is an `include:`
list naming `litellm/settings.yaml` plus one to three engine fragments. LiteLLM
extends list keys and replaces the rest, and it does **not** recurse — so a
composed file must never include another composed file, or the settings vanish
silently and the proxy boots with no master key.

**starter** — the default a fresh clone gets. Six aliases with `all`, ~17 GB:

|  | LMStudio 1234 | Unsloth 8888 | Ollama 11434 |
|:--|:--|:--|:--|
| chat — Gemma 4 E4B | `lms-4b` | `unsloth-4b` | `ollama-4b` |
| embed — nomic v1.5, 768d | `lms-embed` | `unsloth-embed` | `ollama-embed` |

**full** — 20 aliases with `all`, ~90 GB, a strict superset. Adds the
LMStudio ladder `lms-31b` `lms-26b` `lms-12b` `lms-3b` `lms-2b`, the roles
`lms-qwen` `lms-uncensored` `lms-reasoning` `lms-creative` `lms-embed-hq`, and
`unsloth-31b` `unsloth-26b` `ollama-31b` `ollama-26b`. Opt in with one line in
`.env`:

```
GATEWAY_MODELS=full
```

**Naming one engine keeps only that engine's aliases** — `GATEWAY_ENGINE=ollama`
on the full list serves four names and 404s on every `lms-*`. That is the right
answer for a machine with one engine installed, and it is also what removes the
three-way comparison, so `all` stays the default.

Everything in both is local and free. Each engine serves **both** chat and
embeddings, so one engine can carry a whole retrieval workload. The E4B row —
`lms-4b` / `unsloth-4b` / `ollama-4b` — is the only chat model in both lists,
which is why `tests/` defaults to it and picks the leg matching `GATEWAY_ENGINE`.
Keep it that way, or a fresh clone's first command fails.

**Not vocabulary**: `cheap`, `standard`, `frontier`, `cheap-free` and
`standard-hf` are **commented out** in `litellm/settings.yaml` and in
`mlflow/seed.py`, together with both fallback maps — they belong to no engine,
which is why they sit beside the settings rather than in a fragment. Do not tell a
caller to use them without uncommenting them first.

Three properties of this config that look like bugs and are not:

- **Nothing can accrue spend today**, because every priced route is commented out
  in `litellm/settings.yaml`.
  Uncomment the tiers and `lms-26b → cheap-free → cheap` goes live, at which point
  a stopped LMStudio silently turns a free session into a paid one. Every other
  local alias is terminal by design: `lms-uncensored` fails rather than sending a
  prompt to a hosted model that would see it and refuse, and the rest fail so the
  name always means "these weights, this engine, on this machine, free".
- **Local routes are shadow-priced** — free, but carrying a cloud twin's rate, so
  budget ceilings still trip. Anything summing `/spend/logs` must say whether it
  reports money billed or the cost of the same workload on the cloud twin.
- **Unsloth holds one model at a time, chat and embedder alike.** `unsloth-embed`
  evicts `unsloth-26b` and the next chat call swaps it back, so a retrieval loop
  on that engine pays a swap per call. LMStudio and Ollama do not.
