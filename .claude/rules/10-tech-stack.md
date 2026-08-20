---
description: "Reference: Technology stack — LiteLLM proxy + Postgres under compose, no application code"
---

# Reference: Technology Stack

## Backend

- **Language**: none — this repo carries no language manifest and no source
  files. The "backend" is a stock upstream image, configured by YAML.
- **Framework**: LiteLLM proxy, `ghcr.io/berriai/litellm:main-stable`, run with
  `--config /app/config.yaml --port 4000 --num_workers 1`. It exposes the
  OpenAI-compatible routes **and** `/v1/messages`, which is what lets Claude Code
  drive any alias here.
- **Data**: Postgres 17 (`docker.io/postgres:17`), database `litellm`, volume
  `postgres_data`. It holds virtual keys, teams, spend logs and budget ceilings —
  LiteLLM applies its own schema migrations on first startup, so there is no
  `init.sql` and no migration tool in this repo.

## Model providers

| Provider | Reaches | Used by |
|:--|:--|:--|
| **LMStudio** | native on the host, via `host.containers.internal` / `host.docker.internal` | `local`, `embed`, `uncensored` |
| **OpenRouter** | `OPENROUTER_API_KEY` | `cheap`, `standard`, `cheap-free` |
| **OpenAI** | `OPENAI_API_KEY` | `frontier` |
| **HuggingFace** | `HF_TOKEN` | `standard-hf` (fallback target only) |

LMStudio is a **host** dependency, not a container — it needs the Apple-Silicon
GPU. It must be hand-loaded with matching flags; a JIT load silently returns a
smaller context window with a 1 h TTL.

## Infrastructure

- **Deploy**: `podman compose up -d`, and `docker compose up -d` works
  identically — both are supported and the compose file avoids anything specific
  to either. `extra_hosts` declares both `host.docker.internal` and
  `host.containers.internal` for exactly that reason.
- **Runtime target**: this laptop only. Nothing here is built, published, or
  deployed anywhere else, and the gateway binds `localhost`. A gateway reachable
  by anything but localhost needs a real `LITELLM_MASTER_KEY` first.
- **Images**: both stock. There is deliberately **no custom image and no build
  step** — a `litellm/Dockerfile` returns the day a callback needs a package the
  base image lacks.

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
- Shell scripts only for trivial one-liners. If something genuinely needs a
  program, it does not belong in this repo — it belongs in the project that
  wants it, or in mac-setup's `apps/`.

## Conventions this machine imposes

- **One formatter per filetype.** Biome owns the JS/TS family; prettier and
  eslint are not installed. Python formats with the ruff CLI chain. Neither
  applies here — see `09-code-quality.md` for what this repo's filetypes get,
  which is close to nothing.
- Tools run only where the repo carries their config file — see
  `rules/09-code-quality.md`.
