# Project config — the facts

**ai-gateway**: the machine-wide LLM gateway. One OpenAI-compatible endpoint every project
on this laptop calls, so switching model or provider is a change *here* rather than in
each repo. Laptop-only — every gateway binds localhost, and nothing is deployed anywhere.

## Three compose projects, and nothing at the root

Since 2026-09-03 each gateway is a **standalone compose project**. There is no root
`compose.yml`, no root `.env`, no root `tests/` and no root `discover/`. You start a gateway
by entering its folder; you remove one by deleting its folder. `envoy/` was added on
2026-09-04 and touched nothing that already existed — the first real test of the design.

All four images are stock: **no Dockerfile and no build step**. A `litellm/Dockerfile`
returns the day a callback needs a package the base image lacks.

### `litellm/` — project name **`ai-gateway`**, port 24000

| Service | Image | Host port | Holds / does |
|:--|:--|:--|:--|
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | **24000** → 4000 | the primary endpoint; UI at `/ui`; `/v1/messages` alongside the OpenAI routes |
| `postgres` | `docker.io/postgres:17` | **none** | database `litellm` — keys, teams, spend, ceilings |
| `discover` | same as `litellm` | — | one-shot: writes `config/discovered-<engine>.yaml` when `GATEWAY_DISCOVERY` is set, and exits in a second doing nothing when it is not. `litellm` waits for it either way |

> **`name: ai-gateway` is load-bearing.** The volume resolves to
> `<project>_postgres_data`, so that word is what keeps this attached to
> `ai-gateway_postgres_data` — every virtual key and spend log since before the split.
> Rename it and compose silently creates a new empty volume.

### `mlflow/` — project name `ai-gateway-mlflow`, port 25000

| Service | Image | Host port | Holds / does |
|:--|:--|:--|:--|
| `mlflow` | `ghcr.io/mlflow/mlflow:latest` | **25000** → 5000 | the same aliases through the MLflow AI Gateway. **No key, and no `/v1/messages`** |
| `postgres` | `docker.io/postgres:17` | **none** | database `mlflow` — endpoints, encrypted secrets, traces |
| `mlflow-seed` | same as `mlflow` | — | one-shot: runs `config/seed.py`, then exits |

### `envoy/` — project name `ai-gateway-envoy`, ports 26000 and 26064

| Service | Image | Host port | Holds / does |
|:--|:--|:--|:--|
| `envoy` | `docker.io/envoyproxy/ai-gateway-cli:latest` | **26000** → 1975, **26064** → 1064 | `aigw run` — Envoy AI Gateway's STANDALONE mode. A real Envoy data plane from one config file. **No Kubernetes, no database, one service** |

26000 is the data plane (`/v1/*`, `/anthropic/v1/messages`, `/mcp`); 26064 is the admin
server (`/metrics`, `/health`) and nothing else. The image ships Envoy pre-downloaded, sets
`AIGW_RUN_ID=0`, runs as nonroot and **carries its own HEALTHCHECK**, so `compose.yml`
declares none.

**It is distroless: no shell, so `compose exec` cannot work.** Use `compose logs`.

**Exited (0) is the finished state** for `discover` and `mlflow-seed`.

Each server applies its own schema migrations on first boot, and each project's postgres
creates its one database with `POSTGRES_DB`. There is **no SQL in this repo at all** —
`postgres/init-databases.sh` existed only because one server had to carry two databases,
and it went with the split.

**The 2xxxx band is deliberate.** Two other stacks hold ports on this machine, and the
failure avoided is not a loud bind error but the silent one: a probe against
`localhost:4000` that a *different* project's gateway answers, going green.

| Stack | Band |
|:--|:--|
| `~/Projects/Github/lukaskellerstein/mlflow-tutorial` | 3000, 4000, 5432, 5555, 6333/4, 7233, 8080, 9090 |
| `~/Projects/Github/lukaskellerstein/ai-agent-platform` | 1xxxx |
| `ai-gateway` | **2xxxx** — 24000, 25000, 26000, 26064 |

## The words, per project

`COMPOSE_PROFILES` is gone. The directory you stand in is the gateway switch. Each project
reads its **own** `.env`:

| Variable | Values | Default | Picks | In |
|:--|:--|:--|:--|:--|
| `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `openrouter`, `openai` | `lms` | which engine | all three |
| `GATEWAY_DISCOVERY` | *(empty)*, `on` | *(empty)* | which models | `litellm/`, `mlflow/` |
| `AIGW_DEBUG` | `false`, `true` — **never empty** | `false` | per-request logging | `envoy/` |

`GATEWAY_DISCOVERY` is empty by default, and then the hand-written lists below are the whole
vocabulary. Set it and the gateway ADDS every model the engine holds on disk — LiteLLM
through a generated `litellm/config/discovered-<engine>.yaml` that **includes** the
hand-written file, MLflow by **appending** to the hand-written `ENDPOINTS`. It never
replaces a hand-written alias, and it is refused on the two paid engines. Full facts:
[`../CLAUDE.md`](../CLAUDE.md) § the repo in ten points, and either
`discover/gateway_discovery.py`.

**THE THREE PROJECTS CAN EACH SERVE A DIFFERENT ENGINE.** Before the split one word named a
file on one side and an environment variable on the other, so they could not diverge. Now:

| | LiteLLM (24000) | MLflow (25000) | Envoy (26000) |
|:--|:--|:--|:--|
| reads | `litellm/.env` | `mlflow/.env` | `envoy/.env` |
| compose selects | `litellm/config/<engine>.yaml` | `config/seed.py`, word in its env | `envoy/config/<engine>.yaml` |
| the aliases are in | that same file | `mlflow/config/<engine>.py` | that same file |

Check every `.env` before treating a difference between the ports as a bug.

**`GATEWAY_DISCOVERY` DOES NOT EXIST IN `envoy/`.** Its config would need a third renderer
and its image has no Python. `envoy/config/<engine>.yaml` is always the whole vocabulary.

A typo fails differently on each side: `mlflow-seed` exits 2 naming the five valid words
while its server keeps serving what it held; `litellm` crash-loops on `Config file not
found`.

Each `litellm/config/<engine>.yaml` carries `include: [settings.yaml]` and then its own
`model_list`. LiteLLM extends list keys and replaces the rest, and **does not recurse** —
so an included file must never itself carry an `include:`, or the settings vanish silently
and the proxy boots with no master key.

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
across a row, so changing the word and re-running that project's `tests/` measures the
engine and nothing else.

**`openrouter-free` is deliberately absent on 25000 AND 26000.** Neither MLflow nor Envoy
has an equivalent of `extra_body`, so neither can carry the provider pin, and an unpinned
copy would carry exactly the raw-text tool-call failure the pin exists to stop. It is the one
alias where "the config is incomplete" is the wrong diagnosis.

## Seven things that look like bugs and are not

- **An alias that answers on one port and 404s on another.** The three projects keep
  separate lists and none reads another's. Either the alias was added on one side only, or
  the `.env` files name different engines. **No test catches this any more.**
- **Envoy answering `OK` on 26064 while 26000 refuses.** The admin server starts before
  Envoy's listener. Probe `26000/v1/models`, not `26064/health`.
- **Nothing in `compose logs envoy` after a request.** `AIGW_DEBUG` is `false`, so Envoy's
  stdout goes to a file inside a distroless container. Set it `true` to see anything.
- **A local engine cannot accrue spend.** The hosted routes are not disabled, they are
  absent — not in the running config at all.
- **Local routes are shadow-priced**: free to run, carrying a cloud twin's rate so a
  budget ceiling still trips. An unpriced route would log `$0` and make ceilings a no-op.
- **Unsloth holds one model at a time**, and the limit spans chat and the embedder.
  `unsloth-embed` evicts `unsloth-26b` and the next chat call swaps it back — 14 s cold,
  4.4 s warm. **More than one gateway on `unsloth` will thrash it.** LMStudio and Ollama
  do not.
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
Every `compose.yml` declares both hostnames so Podman and Docker behave identically.
`HF_TOKEN` backed nothing and was removed at the split.

**A missing key fails twice, differently**: LiteLLM keeps the alias and 401s at call time,
while the MLflow seed skips the endpoint entirely — so the same name 401s on 24000 and
404s on 25000.

## Config, secrets, tooling

- Each `compose.yml` interpolates from the **shell environment first**, then its own `.env`.
  That ordering is the design: `~/Projects/.envrc` exports the provider keys from
  `~/.secrets/secrets.enc.yaml`, so the key lines in every `.env` stay blank and no
  second plaintext copy exists to go stale after a rotation.
- **A bare `compose config` therefore PRINTS THOSE KEYS.** Filter it or use
  `--services`. This leaked `UNSLOTH_API_KEY` into a transcript on 2026-09-03.
- `.env` is gitignored at every depth. Each project's `.env.example` is tracked and must
  never carry a real value. Full policy → [`12-security.md`](12-security.md).
- **`uv`, and only inside the three `tests/` directories** — the only places with a language
  manifest (`pyproject.toml`, Python 3.12, `openai` + `python-dotenv`). Each is its own uv
  project and needs its own `uv sync`. `mlflow/config/` runs inside the MLflow image and has
  no manifest of its own; the repo root carries none.
- **Run**: `cd <folder> && podman compose up -d`. There is no command that starts more than
  one.
- **Test**: `cd <folder>/tests && uv sync && uv run run_all.py` — four scripts against that
  one port, exit 1 on any failure. Each drives one alias per run, so none is a substitute for
  the checks in [`06-testing.md`](06-testing.md). **The three gateways share a vocabulary but
  not a calling contract**, and they are genuinely three different contracts:

  | | LiteLLM | MLflow | Envoy |
  |:--|:--|:--|:--|
  | `checks_api_key` | yes | no | no |
  | `lists_models` | yes | no | **yes** |
  | `echoes_alias` | yes | no | no |
  | `exposes_route_limits` | yes | no | no |
  | caller must send `max_tokens` | no | yes | yes |

  A check that assumed "LiteLLM or not-LiteLLM" would be wrong about Envoy. Each
  `tests/common.py` § `Gateway` declares its own row, and `04_gateway_contract.py` checks it.
