# Project config — the facts

**ai-gateway**: the machine-wide LLM gateway. One OpenAI-compatible endpoint every project
on this laptop calls, so switching model or provider is a change *here* rather than in
each repo. Laptop-only — both gateways bind localhost, and nothing is deployed anywhere.

## Services

One compose project (`name: ai-gateway`), so containers are `ai-gateway-<service>-N`. All
three images are stock: **no Dockerfile and no build step**. A `litellm/Dockerfile`
returns the day a callback needs a package the base image lacks.

| Service | Image | Host port | Holds / does |
|:--|:--|:--|:--|
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | **24000** → 4000 | the primary endpoint; UI at `/ui`; `/v1/messages` alongside the OpenAI routes |
| `postgres` | `docker.io/postgres:17` | **none** | databases `litellm` (keys, teams, spend, ceilings) and `mlflow` (endpoints, secrets, traces) |
| `mlflow` | `ghcr.io/mlflow/mlflow:latest` | **25000** → 5000 | the same aliases through the MLflow AI Gateway. **No key, and no `/v1/messages`** |
| `mlflow-seed` | same as `mlflow` | — | one-shot: runs `mlflow/seed.py`, then exits. **Exited (0) is the finished state** |

Both gateways carry compose profiles; `postgres` carries none and always starts. Each
server applies its own schema migrations on first boot, so the only SQL here is
`postgres/init-databases.sh` — `CREATE DATABASE mlflow`, on a fresh volume only.

**The 2xxxx band is deliberate.** Two other stacks hold ports on this machine, and the
failure avoided is not a loud bind error but the silent one: a probe against
`localhost:4000` that a *different* project's gateway answers, going green.

| Stack | Band |
|:--|:--|
| `~/Projects/Github/lukaskellerstein/mlflow-tutorial` | 3000, 4000, 5432, 5555, 6333/4, 7233, 8080, 9090 |
| `~/Projects/Github/lukaskellerstein/ai-agent-platform` | 1xxxx |
| `ai-gateway` | **2xxxx** — 24000, 25000 |

## The two words

| Variable | Values | Default | Picks |
|:--|:--|:--|:--|
| `COMPOSE_PROFILES` | `litellm`, `mlflow`, `litellm,mlflow`, `all` | *(nothing starts)* | which gateway |
| `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `openrouter`, `openai` | `lms` | which engine |

`GATEWAY_ENGINE` becomes a filename on one side and an environment variable on the other,
so the gateways cannot serve different engines — though they can still drift in *content*:

| | LiteLLM (24000) | MLflow (25000) |
|:--|:--|:--|
| compose selects | `litellm/<engine>.yaml` | `mlflow/seed.py`, with the word in its env |
| the aliases are in | that same file | `mlflow/<engine>.py` |

Each `litellm/<engine>.yaml` carries `include: [settings.yaml]` and then its own
`model_list`. LiteLLM extends list keys and replaces the rest, and **does not recurse** —
so an included file must never itself carry an `include:`, or the settings vanish silently
and the proxy boots with no master key.

A typo stops both gateways: `mlflow-seed` exits 2 naming the five valid words, and
`litellm` crash-loops on `Config file not found`.

## The aliases are the vocabulary

Callers name an **alias**, never a model — the model behind a name is expected to change.
`README.md` carries the full table with models and prices.

|  | LMStudio :1234 | Unsloth :8888 | Ollama :11434 | OpenRouter | OpenAI |
|:--|:--|:--|:--|:--|:--|
| chat, small | `lms-4b` | `unsloth-4b` | `ollama-4b` | — | `openai-mini` |
| chat, large | `lms-26b` | `unsloth-26b` | `ollama-26b` | `openrouter-26b` | — |
| embed | `lms-embed` | `unsloth-embed` | `ollama-embed` | — | `openai-embed` |
| extra | — | — | — | `openrouter-free` | — |
| costs | free | free | free | **paid** | **paid** |

`GATEWAY_ENGINE` selects **one column**. The rows are the point: the same weights sit
across a row, so changing the word and re-running `tests/` measures the engine and
nothing else.

**`openrouter-free` is deliberately absent on 25000.** MLflow has no equivalent of
`extra_body`, so it cannot carry the provider pin, and an unpinned copy would carry
exactly the raw-text tool-call failure the pin exists to stop. It is the one alias where
"the seed has not run" is the wrong diagnosis.

## Four things that look like bugs and are not

- **A local engine cannot accrue spend.** The hosted routes are not disabled, they are
  absent — not in the running config at all.
- **Local routes are shadow-priced**: free to run, carrying a cloud twin's rate so a
  budget ceiling still trips. An unpriced route would log `$0` and make ceilings a no-op.
- **Unsloth holds one model at a time**, and the limit spans chat and the embedder.
  `unsloth-embed` evicts `unsloth-26b` and the next chat call swaps it back — 14 s cold,
  4.4 s warm. LMStudio and Ollama do not.
- **LMStudio JIT-loads at 8192 context with a 1 h TTL**, ignoring hand-load flags. A
  session that worked this morning fails this afternoon with nothing changed.
  `lms ps --json` is the truth, not the UI.

## Providers

| Provider | Reached at | Serves |
|:--|:--|:--|
| LMStudio | host :1234, via `host.containers.internal` / `host.docker.internal` | `lms-*` |
| Unsloth Studio | host :8888, same. **Requires `UNSLOTH_API_KEY`** — every route 401s without it | `unsloth-*` |
| Ollama | host :11434, same. Ignores the Authorization header | `ollama-*` |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter-*` — **real spend** |
| OpenAI | `OPENAI_API_KEY` | `openai-*` — **real spend** |

The three local engines run **natively on the host**, not in containers — they need the
Apple-Silicon GPU. All three bind 127.0.0.1 only, and the containers still reach them
through `host.containers.internal` (verified from inside the container, 2026-08-26).
`compose.yml` declares both hostnames so Podman and Docker behave identically.
`HF_TOKEN` backs nothing now.

**A missing key fails twice, differently**: LiteLLM keeps the alias and 401s at call time,
while the MLflow seed skips the endpoint entirely — so the same name 401s on 24000 and
404s on 25000.

## Config, secrets, tooling

- `compose.yml` interpolates from the **shell environment first**, then `.env`. That
  ordering is the design: `~/Projects/.envrc` exports the provider keys from
  `~/.secrets/secrets.enc.yaml`, so the key lines in `.env` stay blank and no second
  plaintext copy exists to go stale after a rotation.
- `.env` is gitignored. `.env.example` is tracked and must never carry a real value. Full
  policy → [`12-security.md`](12-security.md).
- **`uv`, and only inside `tests/`** — the one place with a language manifest
  (`pyproject.toml`, Python 3.12, `openai` + `python-dotenv`). `mlflow/` runs inside the
  MLflow image and has no manifest of its own; the repo root carries none.
- **Run**: `podman compose up -d` (or `docker compose`) → 24000, and 25000. Needs
  `COMPOSE_PROFILES` in `.env`, or only postgres starts.
- **Test**: `cd tests && uv sync && uv run run_all.py` — three call kinds against every
  gateway `COMPOSE_PROFILES` starts, exit 1 on any failure. It drives one alias per run,
  so it is not a substitute for the checks in [`06-testing.md`](06-testing.md).
