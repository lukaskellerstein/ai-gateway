---
description: "Reference: Technology stack — LiteLLM proxy + Postgres under compose, no application code"
---

# Reference: Technology Stack

## Backend

- **Language**: none at the root — the "backend" is a stock upstream image,
  configured by YAML. Python appears in exactly two places: `mlflow/`, run
  **inside** the MLflow image with no manifest of its own, and `tests/`, a `uv`
  project with `pyproject.toml` and a lockfile that runs on the host.
- **Framework**: LiteLLM proxy, `ghcr.io/berriai/litellm:main-stable`, run with
  `--config /app/config.yaml --port 4000 --num_workers 1`. It exposes the
  OpenAI-compatible routes **and** `/v1/messages`, which is what lets Claude Code
  drive any alias here.
- **Second gateway**: the MLflow AI Gateway, `ghcr.io/mlflow/mlflow:latest`
  (3.15.1), run as `mlflow server` on `25000`. It serves the **same alias names**
  through `/gateway/mlflow/v1/chat/completions`. The gateway *is* the tracking
  server: no second process, and no restart when its configuration changes —
  which is also why it has no config file. `mlflow/seed_gateway.py`, run by the
  one-shot `mlflow-seed` service, reads `litellm/config.yaml` and writes the same
  aliases in through the API.
- **Data**: Postgres 17 (`docker.io/postgres:17`), volume `postgres_data`, two
  databases. `litellm` holds virtual keys, teams, spend logs and budget ceilings;
  `mlflow` holds gateway endpoints, encrypted provider secrets and traces. Both
  servers apply their own schema migrations on first startup, so the only SQL in
  this repo is `postgres/init-databases.sh`, which does nothing but
  `CREATE DATABASE mlflow` and only on a fresh volume.

## Model providers

| Provider | Reaches | Used by |
|:--|:--|:--|
| **LMStudio** | native on the host, port 1234, via `host.containers.internal` / `host.docker.internal` | every `local-*` alias plus `local-qwen`, `reasoning`, `creative`, `uncensored`, `embed`, `embed-hq` — from **both** gateways |
| **Unsloth Studio** | native on the host, port 8888, same two hostnames. **Needs `UNSLOTH_API_KEY`** | `unsloth-31b`, `unsloth-26b` — from **both** gateways |
| **OpenRouter** | `OPENROUTER_API_KEY` | `cheap`, `standard`, `cheap-free` |
| **OpenAI** | `OPENAI_API_KEY` | `frontier` |
| **HuggingFace** | `HF_TOKEN` | `standard-hf` (fallback target only) |

LMStudio and Unsloth Studio are **host** dependencies, not containers — both need
the Apple-Silicon GPU, and both bind `127.0.0.1` only, which the containers still
reach through `host.containers.internal` (verified from inside the container,
2026-08-26). They fail differently when a model is not loaded, and the difference
matters: LMStudio JIT-loads and silently gives you a smaller context window with a
1 h TTL, while Unsloth returns `400 No model loaded` unless auto-switch is on, and
then unloads whatever it was holding to make room.

## Infrastructure

- **Deploy**: `podman compose up -d`, and `docker compose up -d` works
  identically — both are supported and the compose file avoids anything specific
  to either. `extra_hosts` declares both `host.docker.internal` and
  `host.containers.internal` for exactly that reason.
- **Runtime target**: this laptop only. Nothing here is built, published, or
  deployed anywhere else, and both gateways bind `localhost`. A gateway reachable
  by anything but localhost needs a real `LITELLM_MASTER_KEY` first — and the
  MLflow one has **no key at all**, so binding it wider hands out free use of
  every alias.
- **Images**: all three stock. There is deliberately **no custom image and no
  build step** — the MLflow image already ships `psycopg2` and `cryptography`,
  and a `litellm/Dockerfile` returns the day a callback needs a package the base
  image lacks.

## Configuration and secrets

- `compose.yml` interpolates from the **shell environment first**, then `.env`.
  That ordering is the whole design: `~/Projects/.envrc` exports the provider
  keys from `~/.secrets/secrets.enc.yaml`, so the three key lines in `.env` stay
  blank and no second plaintext copy exists to go stale after a rotation.
- `.env.example` is tracked and must never carry a real value. `.env` is
  gitignored.
- Full policy: [`12-security.md`](12-security.md).

## Scripting & Automation

- Default: **`curl` + `python3 -c`** for one-off gateway calls — that is what
  `README.md` and `NOTES.md` already use, and it needs nothing installed.
- Shell scripts only for trivial one-liners. A tool a *project* wants belongs in
  that project, or in mac-setup's `apps/` — not here.
- **`tests/` is the one exception, and it is deliberate.** A repeatable check of
  what this gateway serves cannot live in another repo: it is this repo's
  behaviour being proved, and a caller's copy would drift the moment an alias
  changed. It is a `uv` project (`pyproject.toml`, `uv.lock`, Python 3.12,
  `openai` + `python-dotenv`) so it can drive the real OpenAI client, which is
  what every caller uses and what `curl` cannot exercise. Keep it to that: three
  scripts, one shared `common.py`, one runner — [`tests/README.md`](../../tests/README.md).

## Conventions this machine imposes

- **One formatter per filetype.** Biome owns the JS/TS family; prettier and
  eslint are not installed. Python formats with the ruff CLI chain. Neither
  applies here — see `09-code-quality.md` for what this repo's filetypes get,
  which is close to nothing.
- Tools run only where the repo carries their config file — see
  `rules/09-code-quality.md`.
