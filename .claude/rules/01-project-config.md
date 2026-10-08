# Project config — the facts

**ai-gateway**: the machine-wide LLM gateway. One OpenAI-compatible endpoint every project
on this laptop calls, so switching model or provider is a change *here* rather than in
each repo. Laptop-only — every port is published on `127.0.0.1` only (since 2026-10-07; a
bare `24000:4000` answered on the Mac's network address), and nothing is deployed anywhere.

## Two compose projects, and nothing at the root

Since 2026-09-03 each gateway is a **standalone compose project**. There is no root
`compose.yml`, no root `.env` and no root `tests/`. You start a gateway
by entering its folder; you remove one by deleting its folder. The design was tested both
ways on 2026-09-04: `envoy/` was **added** and touched nothing that already existed, and
`mlflow/` was **deleted** and nothing else stopped working.

A third project, `mlflow/` on port 25000, existed until 2026-09-04. It is gone: the folder,
its postgres, its seed one-shot and its `tests/`. The root `README.md` § What was removed says
why. **Do not propose bringing it back**, and treat a leftover reference to it as a doc bug.

The one root folder is `benchmark/` (2026-09-04). It is **not a project**: it starts nothing,
reads no project's files, and times one HTTP request against both ports with the engine,
model, body and `max_tokens` held identical — see
[`../../benchmark/README.md`](../../benchmark/README.md). Its results are in
[`../../COMPARISON.md`](../../COMPARISON.md) § What they cost per request.

Both images are stock: **no Dockerfile and no build step**. A `litellm/Dockerfile` returns
the day a callback needs a package the base image lacks.

### `litellm/` — project name **`ai-gateway`**, port 24000

| Service | Image | Host port | Holds / does |
|:--|:--|:--|:--|
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | **24000** → 4000 | the primary endpoint; UI at `/ui`; `/v1/messages` alongside the OpenAI routes |
| `postgres` | `docker.io/postgres:17` | **none** | database `litellm` — keys, teams, spend, ceilings |

> **`name: ai-gateway` is load-bearing.** The volume resolves to
> `<project>_postgres_data`, so that word is what keeps this attached to
> `ai-gateway_postgres_data` — every virtual key and spend log since before the split.
> Rename it and compose silently creates a new empty volume.

### `envoy/` — project name `ai-gateway-envoy`, ports 26000 and 26064

| Service | Image | Host port | Holds / does |
|:--|:--|:--|:--|
| `envoy` | `docker.io/envoyproxy/ai-gateway-cli:latest` | **26000** → 1975, **26064** → 1064 | `aigw run` — Envoy AI Gateway's STANDALONE mode. A real Envoy data plane from one config file. **No Kubernetes, no database, one service** |

26000 is the data plane (`/v1/*`, `/anthropic/v1/messages`, `/mcp`); 26064 is the admin
server (`/metrics`, `/health`) and nothing else. The image ships Envoy pre-downloaded, sets
`AIGW_RUN_ID=0`, runs as nonroot and **carries its own HEALTHCHECK**, so `compose.yml`
declares none.

**It is distroless: no shell, so `compose exec` cannot work.** Use `compose logs`.

LiteLLM applies its own schema migrations on first boot, and its postgres creates its one
database with `POSTGRES_DB`. There is **no SQL in this repo at all** —
`postgres/init-databases.sh` existed only because one server had to carry two databases, and
it went with the split.

**Two volumes outlive the deleted MLflow project**: `ai-gateway-mlflow_postgres_data` and
`ai-gateway-mlflow_mlflow_artifacts`. Nothing reads them. Removing a volume is unrecoverable,
so ask before you do.

**The 2xxxx band is deliberate.** Two other stacks hold ports on this machine, and the
failure avoided is not a loud bind error but the silent one: a probe against
`localhost:4000` that a *different* project's gateway answers, going green.

| Stack | Band |
|:--|:--|
| `~/Projects/Github/lukaskellerstein/mlflow-tutorial` | 3000, 4000, 5432, 5555, 6333/4, 7233, 8080, 9090 |
| `~/Projects/Github/lukaskellerstein/ai-agent-platform` | 1xxxx |
| `ai-gateway` | **2xxxx** — 24000, 26000, 26064, and 24090 / 26090 for the test MCP server while a test runs. 25000 is free again since 2026-09-04 |

## The words, per project

`COMPOSE_PROFILES` is gone. The directory you stand in is the gateway switch. Each project
reads its **own** `.env`:

| Variable | Values | Default | Picks | In |
|:--|:--|:--|:--|:--|
| `GATEWAY_ENGINE` | `all`, `lms`, `unsloth`, `ollama`, `openrouter`, `openai`, `cerebras` | **`all`** | which engines | both |
| `AIGW_DEBUG` | `false`, `true` — **never empty** | `false` | per-request logging | `envoy/` |

**`all` IS THE DEFAULT AND IS A REAL FILE**, `config/all.yaml`, not a list you write. It
serves every engine at once: 21 aliases on LiteLLM, 35 route rules on Envoy — the latter split
across **six `AIGatewayRoute`s**, one per engine, because a single route caps at 15 aliases
(`HTTPRoute.spec.rules` allows 16 and aigw uses one). The two files are
built differently and the difference matters when you add an alias:

| | `litellm/config/all.yaml` | `envoy/config/all.yaml` |
|:--|:--|:--|
| shape | seven `include:` lines | the six engine files MERGED |
| copies aliases | **no** | **yes** |
| adding an alias needs it edited | no | **yes** |

Envoy's copies because `aigw run` takes ONE path — not a directory, not a repeated flag,
checked against `aigw run --help` on 2026-09-06 — and Envoy's config has no `include:`
mechanism.

**NAMING ONE ENGINE IS THE MONEY GUARD.** Set `GATEWAY_ENGINE=lms` and every other alias is
absent from the running config, not disabled. On `all` the two paid engines are registered,
which costs nothing: only a completion bills, and no alias falls back to another.

**AUTO-DISCOVERY WAS REMOVED ON 2026-09-06.** `litellm/` had a `discover` one-shot and a
`GATEWAY_DISCOVERY` variable that generated an alias list from what an engine held on disk;
the service, the module, the variable and the generated files are gone, and with them the last
Python outside `tests/` and `benchmark/`. Do not propose bringing it back. Root `README.md`
§ What was removed has the reasoning.

**THE TWO PROJECTS CAN EACH SERVE A DIFFERENT ENGINE.** Before the split one word named a
file on one side and an environment variable on the other, so they could not diverge. Now:

| | LiteLLM (24000) | Envoy (26000) |
|:--|:--|:--|
| reads | `litellm/.env` | `envoy/.env` |
| compose selects | `litellm/config/<word>.yaml` | `envoy/config/<word>.yaml` |
| the aliases are in | that file, or the six it includes | that file |

Check both `.env` files before treating a difference between the ports as a bug.

**NEITHER PROJECT GENERATES ANY CONFIG.** `envoy/` never could — its config would need
another renderer and its image is distroless with no Python — and `litellm/` stopped on
2026-09-06. What a gateway serves is readable from the files in `config/` without running
anything.

A typo crash-loops `litellm` on `Config file not found`, and stops `aigw` with the same
complaint. `compose logs` names the file in both cases.

Each `litellm/config/<engine>.yaml` carries `include: [settings.yaml]` and then its own
`model_list`. LiteLLM extends list keys and replaces the rest, and **does not recurse** — a
nested `include:` is merged as data and dropped.

`config/all.yaml` lives with that rather than around it: it lists `settings.yaml` **directly
and first**, then the six engine files, whose own `include: [settings.yaml]` is then dropped
harmlessly. Verified 2026-09-29 — 17 aliases in `/v1/models`, prices and windows intact. The
rule still bites anywhere else: include a file that carries an `include:` you were relying on,
and the settings vanish silently and the proxy boots with no master key.

## The aliases are the vocabulary

Callers name an **alias**, never a model — the model behind a name is expected to change.
`README.md` carries the full table with models and prices.

|  | LMStudio :1234 | Unsloth :8888 | Ollama :11434 | OpenRouter | OpenAI | Cerebras |
|:--|:--|:--|:--|:--|:--|:--|
| Gemma 4 E4B | `lms-gemma4-e4b` | `unsloth-gemma4-e4b` | `ollama-gemma4-e4b` | — | — | — |
| Gemma 4 12B | `lms-gemma4-12b` | `unsloth-gemma4-12b` | — | — | — | — |
| Gemma 4 26B | `lms-gemma4-26b` | `unsloth-gemma4-26b` · `unsloth-gemma4-26b-fast` | `ollama-gemma4-26b` | `openrouter-gemma4-26b` · `openrouter-gemma4-26b-free` | — | — |
| Qwen 3.8 27B | `lms-qwen38-27b` | `unsloth-qwen38-27b` | — | `openrouter-qwen38-27b` | — | `cerebras-qwen38-27b` |
| other chat | — | — | — | — | `openai-gpt54-mini` | — |
| embed | `lms-nomic-embed` | `unsloth-nomic-embed` · `unsloth-nomic-embed-sidecar` | `ollama-nomic-embed` | — | `openai-embed3-small` | — |
| costs | free | free | free | **paid** | **paid** | **paid** |

**Names are `<engine>-<model>-<size>` since 2026-09-29**, and the suffix is the same on every
engine for the same model. The size-only names before it (`lms-26b`, `cerebras-27b`, …) were
renamed with no fallback and now 404; root `README.md` § The aliases has the old → new table.

`GATEWAY_ENGINE=all` — the default — serves **every column at once**. Naming one engine
selects **one column**, and the rows are the point: the same weights sit across a row, so
changing the word and re-running that project's `tests/` measures the engine and nothing else.
A comparison run still wants one column, because `all` leaves the caller free to pick.

**ENVOY ADDS `-anthropic` NAMES THAT LITELLM DOES NOT HAVE — FIFTEEN OF THEM, ONE PER CHAT
ALIAS** (`lms-gemma4-26b-anthropic`, `openrouter-qwen38-27b-anthropic`, …). They are the SAME
model on the SAME engine. Thirteen of the fifteen reach an `Anthropic`-schema `AIServiceBackend`, so
the body is NOT translated — the only way Claude Code can hold a conversation through Envoy.
**`openai-gpt54-mini-anthropic` and `cerebras-qwen38-27b-anthropic` are the exceptions**:
neither vendor serves `/v1/messages` (Cerebras answered 404, 2026-09-28), so those rules point
at the plain `OpenAI`-schema backend and still translate. They are plumbing, not vocabulary:
LiteLLM does not need them, and nothing but `envoy/tests/5_claude_agent_sdk` calls them.
**20 model aliases + 15 `-anthropic` = the 35 rules in `envoy/config/all.yaml`.** Full note:
`envoy/README.md`.

**`openrouter-gemma4-26b-free` is deliberately absent on 26000.** Envoy has no equivalent of
`extra_body`, so it cannot carry the provider pin, and an unpinned copy would carry exactly
the raw-text tool-call failure the pin exists to stop. It is the one alias where "the config
is incomplete" is the wrong diagnosis.

## Seven things that look like bugs and are not

- **An alias that answers on one port and 404s on the other.** The two projects keep
  separate lists and neither reads the other's. Three causes now: the alias was added on one
  side only, the `.env` files name different engines, or — since 2026-09-06 — it was added to
  `envoy/config/<engine>.yaml` but not to `envoy/config/all.yaml`, which copies rather than
  includes. **No test catches any of the three.**
- **Envoy answering `OK` on 26064 while 26000 refuses.** The admin server starts before
  Envoy's listener. Probe `26000/v1/models`, not `26064/health`.
- **Nothing in `compose logs envoy` after a request.** `AIGW_DEBUG` is `false`, so Envoy's
  stdout goes to a file inside a distroless container. Set it `true` to see anything.
- **A local engine cannot accrue spend — but only when `GATEWAY_ENGINE` names it.** Then the
  hosted routes are not disabled, they are absent. On `all`, the default, they ARE registered:
  still free until a caller names one, because nothing falls back, but present.
- **Local routes are shadow-priced**: free to run, carrying a cloud twin's rate so a
  budget ceiling still trips. An unpriced route would log `$0` and make ceilings a no-op.
- **A gateway call swaps Unsloth's ONE active model**, and the slot spans chat and the
  embedder. `unsloth-nomic-embed` evicts `unsloth-gemma4-26b` and the next chat call swaps it
  back — 13-17 s. **More than one gateway on `unsloth` will thrash it.** LMStudio and Ollama
  do not. **A model pre-loaded in Studio stays beside it** (v0.1.903-beta, measured
  2026-10-07): with `Settings -> Resources -> Keep multiple models loaded` on — ON here — a
  model loaded with `Keep other models loaded`, or `"alongside": true` on
  `POST /api/inference/load`, answers a gateway call with no reload. **No gateway call can
  load one that way**: auto-switch replaces only the active model, never a held one, even the
  least recently used. `GET /api/inference/loaded-models` lists them. **Studio's own
  `Settings -> embedding model`** also runs beside the chat model:
  `unsloth-nomic-embed-sidecar` evicts nothing while that setting names
  `nomic-ai/nomic-embed-text-v1.5` (measured 2026-10-03: 0.04 s, the 26B stayed loaded).
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
| Cerebras | `CEREBRAS_API_KEY` | `cerebras-*` — **real spend**. `qwen-3.8-27b`, which reasons: send `reasoning_effort` on long-output prompts |

The three local engines run **natively on the host**, not in containers — they need the
Apple-Silicon GPU. All three bind 127.0.0.1 only, and the containers still reach them
through `host.containers.internal` (verified from inside the container, 2026-08-26).
Every `compose.yml` declares both hostnames so Podman and Docker behave identically.
`HF_TOKEN` backed nothing and was removed at the split.

**A missing key fails at CALL time on both gateways, not at startup**: the alias stays
registered and answers 401 when something calls it. Nothing complains while either gateway
boots, which is why an auth failure usually means the shell that ran `up -d` had no direnv.

## Config, secrets, tooling

- Each `compose.yml` interpolates from the **shell environment first**, then its own `.env`.
  That ordering is the design: `~/Projects/.envrc` exports the provider keys from
  `~/.secrets/secrets.enc.yaml`, so the key lines in every `.env` stay blank and no
  second plaintext copy exists to go stale after a rotation.
- **A bare `compose config` therefore PRINTS THOSE KEYS.** Filter it or use
  `--services`. This leaked `UNSLOTH_API_KEY` into a transcript on 2026-09-03.
- `.env` is gitignored at every depth. Each project's `.env.example` is tracked and must
  never carry a real value. Full policy → [`12-security.md`](12-security.md).
- **`uv`, and only under the two `tests/` directories** — the only places with a language
  manifest. Since 2026-09-04 each `tests/` is **seven folders, each its own uv project** with
  its own `pyproject.toml` and `.venv`, plus a manifest-only `pyproject.toml` at `tests/`
  itself so `uv run run_all.py` works there. **There is no `uv sync` step**: the runner shells
  out to `uv run --directory <folder>`, which builds whichever venv is missing. The repo root
  carries no manifest, and `benchmark/` has one with no dependencies.
- **Run**: `cd <folder> && podman compose up -d`. There is no command that starts more than
  one.
- **Test**: `cd <folder>/tests && uv run run_all.py` — seven folders against that one port,
  exit 1 on any failure. Each drives one alias per run, so none is a substitute for the checks
  in [`06-testing.md`](06-testing.md). **The two gateways share a vocabulary but not a
  calling contract**, and the contracts are genuinely different:

  | | LiteLLM | Envoy |
  |:--|:--|:--|
  | `checks_api_key` | yes | no |
  | `lists_models` | yes | **yes** |
  | `echoes_alias` | yes | no |
  | `exposes_route_limits` | yes | no |
  | `loopback_only` | yes | **yes** |
  | caller must send `max_tokens` | no | yes |
  | `/v1/responses` — Codex needs it | **yes** | **yes** |
  | an Anthropic route — the Claude SDK needs it | `/v1/messages` | `/anthropic/v1/messages`, on a pass-through alias |
  | SSE streaming | yes | yes |

  The first six rows are declared in each `tests/2_openai_client/settings.py` § `CONTRACT` and
  checked by `04_gateway_contract.py`; the last three are what folders 1, 5 and 6 exercise.
  **Only two of the first six match** — the listing and the loopback binding — which is why
  neither project reads the other's table.
