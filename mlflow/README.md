# mlflow — the second gateway, on port 25000

A standalone compose project. Run it from **this** directory; nothing above it is read, and
nothing here reads `../litellm`.

```bash
cp .env.example .env      # edit GATEWAY_ENGINE if you do not run LMStudio
docker compose up -d      # first boot takes ~60 s: MLflow runs schema migrations

curl -fsS http://localhost:25000/health          # -> OK
docker compose logs mlflow-seed                  # what it built
```

`podman compose` works identically — the two are drop-in replacements here.

**The same alias names as `../litellm`, through a different gateway**, so the two can be
compared on one machine without changing a caller's vocabulary: swap the base URL, keep the
model name. The table of what the aliases point at is in [`../README.md`](../README.md).

**This is not the gateway to run work through.** There is **no key at all** — anything that
can reach the port can call it — no virtual keys, no spend logs, no budget ceilings and no
`/v1/messages`. `../litellm` has all of those. Run this one to compare gateways.

Three services: `postgres` (endpoints, encrypted secrets, traces — no published port),
`mlflow` (the server, which *is* the gateway), and `mlflow-seed` (a one-shot that writes the
endpoint list in over the API and exits — **exited (0) is its finished state**).

> **This project's database started empty on 2026-09-03**, when the two gateways were split
> into separate compose projects and each got its own postgres. Nothing of value was lost:
> `mlflow-seed` rebuilds every endpoint and rewrites every secret on each `up -d`. Traces from
> before the split are still in the old shared volume, orphaned.

## Call it

Any OpenAI-compatible client works. Point `base_url` at
`http://localhost:25000/gateway/mlflow/v1`, and **always send `max_tokens`** — see below.

```bash
curl -sX POST http://localhost:25000/gateway/mlflow/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"lms-4b","messages":[{"role":"user","content":"hi"}],"max_tokens":2048}'
```

Embeddings use a different path here: `/gateway/openai/v1/embeddings`.

The OpenAI client needs *some* `api_key` string, and MLflow never reads it.

### Always send `max_tokens`

MLflow's endpoints are database rows with nowhere to put a per-route default, so a request
that sends no ceiling is unbounded. Measured 2026-09-03 with `lms-4b` and one "count to 3000"
prompt carrying no `max_tokens`:

| | finish_reason | completion tokens |
|:--|:--|--:|
| LiteLLM 24000 | `length` | 4095 — the route's stored `max_tokens: 4096` |
| **MLflow 25000** | `stop` | **13961** — nothing bounded it |

Same prompt, same alias, same weights: 3.4x the output and 3.4x the wait.

Get it wrong downwards and it is worse than slow: a reasoning model spends the whole allowance
thinking and returns **empty content** with `finish_reason: "length"` and no error at all.
Keep the ceiling generous.

## What does not transfer from LiteLLM

Verified 2026-08-31 across all five engines: the two alias lists match, with the single
deliberate exception of `openrouter-free`.

| In LiteLLM | Here |
|:--|:--|
| `/v1/messages` (the Anthropic route) | **Not available** — the passthrough exists only for Anthropic-provider endpoints, and every alias here is OpenAI-protocol. Claude Code therefore stays on 24000 |
| Virtual keys, `/key/generate`, `/spend/logs` | No equivalent. Budget policies cap **per endpoint**, not per caller, and there is no key to hand a project |
| Per-token pricing | Not carried across, so no shadow pricing |
| `max_input_tokens` + pre-call checks | No equivalent — an over-long prompt fails at the model instead of before the call |
| `drop_params` | No equivalent; every parameter is forwarded exactly as sent — which is why the OpenAI routes need `max_completion_tokens` here and accept `max_tokens` on 24000 |
| `extra_body` (OpenRouter's provider pin) | No equivalent, so **`openrouter-free` is absent here on purpose**. It is the one alias that 404s here and answers on 24000 |
| `timeout` per route | One global `MLFLOW_GATEWAY_ROUTE_TIMEOUT_SECONDS` instead |
| `GET /v1/models` | No such route. The vocabulary is in the MLflow UI and in `config/<engine>.py` |

You do get **traces for free**: each request becomes an MLflow trace in an auto-created
`gateway/<alias>` experiment, written after the response.

## It has no config file, so its config is Python

MLflow's endpoints live in the database and arrive over an API — there is no file to mount. So
this gateway's alias list is **Python**, split exactly the way LiteLLM's YAML is: one file per
engine in `config/` (`lms.py`, `unsloth.py`, `ollama.py`, `openrouter.py`, `openai.py`), each a
plain list of `Endpoint(...)` entries with the reasoning beside them. `config/gateway.py` holds
the API calls, written once; `config/seed.py` reads `GATEWAY_ENGINE` and loads the one file it
names.

`mlflow-seed` runs `seed.py` on every `up -d`, and it is idempotent. **Run it by hand through
compose, not on the host** — it imports `mlflow`, which the image ships and your laptop
probably does not, so on the host it fails with `ModuleNotFoundError` before reading a single
argument.

```bash
docker compose run --rm mlflow-seed python /app/config/seed.py --help
docker compose run --rm mlflow-seed python /app/config/seed.py --engine ollama --reset
```

`--reset` rebuilds every endpoint the run names. **`--prune` deletes the ones it does not, and
that includes every other engine's** — read that file's header before reaching for it. Without
it, changing `GATEWAY_ENGINE` leaves the old engine's endpoints answering here after LiteLLM
has stopped serving them.

## Configuration

Two words in `.env` decide what this gateway serves. Compose interpolates from the **shell
environment first**, then `.env`.

```bash
GATEWAY_ENGINE=ollama
GATEWAY_DISCOVERY=
```

**There is no `COMPOSE_PROFILES` line.** It went with the split: the directory you stand in is
now the choice of gateway, and `up -d` here starts this one whether or not `.env` exists.

| Variable | Default | Used by |
|:--|:--|:--|
| `GATEWAY_ENGINE` | `lms` | **which engine this gateway serves** — one of `lms`, `unsloth`, `ollama`, `openrouter`, `openai`. Not a list. It is this project's alone: `../litellm` has its own, and nothing checks that they agree. A typo makes `mlflow-seed` exit 2 naming the five valid words; the server stays up serving what it held before |
| `GATEWAY_DISCOVERY` | *(blank)* | **which models** — blank means the hand-written list alone. `on` **adds** every model the engine holds on this machine. Local engines only. **`off` does not mean off** — the seed reads any non-empty value as on, so leave it blank |
| `MLFLOW_CRYPTO_KEK_PASSPHRASE` | *(blank)* | wraps the key encrypting the stored provider credentials. Blank is supported. **Change it later and they stop decrypting** — and it surfaces as an auth error at call time, not at startup. The repair is `up -d`, which rewrites them |
| `LM_STUDIO_API_BASE` | `http://host.containers.internal:1234/v1` | every `lms-*` endpoint |
| `UNSLOTH_API_BASE` | `http://host.containers.internal:8888/v1` | every `unsloth-*` endpoint |
| `UNSLOTH_API_KEY` | *(blank)* | **required** by every `unsloth-*` endpoint. Blank means the seed **skips** them, so the alias 404s here — the same blank key makes LiteLLM answer 401 instead |
| `OLLAMA_API_BASE` | `http://host.containers.internal:11434/v1` | every `ollama-*` endpoint. **There is no `OLLAMA_API_KEY`**: Ollama ignores the header. `config/ollama.py` still sets a literal `sk-ollama`, precisely because the seed skips an endpoint with an empty key |
| `OPENROUTER_API_KEY` | *(blank)* | every `openrouter-*` endpoint. **Real spend.** Blank means skipped |
| `OPENAI_API_KEY` | *(blank)* | every `openai-*` endpoint. **Real spend**, same failure |
| `MLFLOW_GATEWAY_ROUTE_TIMEOUT_SECONDS` | `3600` | set in `compose.yml`. MLflow's own default is 300 s, which gives up mid-prompt on a local model |
| `MLFLOW_SERVER_ALLOWED_HOSTS` | set in `compose.yml` | must list `mlflow:5000` and `0.0.0.0:5000`, or in-stack calls get 403 while `/health` still says `OK` |

The defaults name `host.containers.internal`, which is Podman's name. Docker resolves it too
because `compose.yml` declares both — but write `host.docker.internal` if you override these.

The provider keys stay blank in `.env` on purpose when your shell already exports them from an
encrypted store: compose reads the shell first, so no second plaintext copy exists to go stale
after a rotation. See [`.env.example`](.env.example).

## Auto-discovery

One line in `.env` adds every model the selected engine holds on **your** disk:

```bash
GATEWAY_DISCOVERY=on
```

At `up -d` the seed asks the engine over its own HTTP API what it has and **appends** one
endpoint per model to the hand-written list. The name is the engine, a dash, and the model id,
with anything MLflow rejects turned into a dash — `google/gemma-4-e4b` becomes
`lms-google-gemma-4-e4b`.

**It only ever adds.** The hand-written endpoints come first and a discovered alias that would
collide with one is dropped, so `lms-4b` keeps meaning what it always meant. Turning it off is
leaving the value **empty** and running `up -d` again.

It is **local-only** — `openrouter` and `openai` bill a real account per model, so they keep
their hand-written lists and money is never discovered. The credentials for discovered
endpoints are copied from the hand-written list rather than read from the environment a second
time, because one secret name must mean one `api_base` + `api_key` pair.

**`discover/gateway_discovery.py` is this project's own copy**, and it carries the three probe
functions and **no renderer** — there is no config file to render. `../litellm/discover/` has
the same probes plus the YAML renderer. Fix a probe here and copy it there.

## Tests

```bash
cd tests
uv sync                                 # once
uv run run_all.py                       # 4 rows against 25000
uv run run_all.py --model ollama-4b     # any alias
uv run 02_tools_call.py                 # one script
```

It drives **this gateway only**. `04_gateway_contract.py` asserts the four claims
`tests/common.py` makes about how to call it, and all four are `False`: a bad key gets 200,
`/models` 404s, `response.model` carries the engine's own id rather than the alias, and
`/model/info` does not exist. Those are absences, and an absence nobody checks is an absence
somebody eventually assumes away. `../litellm/tests/` asserts the opposite four.

What is deliberately not covered is in [`tests/README.md`](tests/README.md).

## Troubleshooting

| Symptom | Cause | Fix |
|:--|:--|:--|
| `unhealthy` for the first minute after `up -d` | schema migrations against an empty database | expected — wait out the 60 s `start_period` |
| `mlflow-seed` shows as exited | it is a one-shot; exit 0 is the finished state | expected — `docker compose logs mlflow-seed` |
| `mlflow-seed` exits 2 | `GATEWAY_ENGINE` is misspelled, or is an old value like `all` | its log names the bad word and the five valid ones |
| Empty content, `finish_reason: "length"` | a thinking model spent the whole `max_tokens` on reasoning — or you sent none and it ran long | send a generous `max_tokens`; there is no route default here |
| An unbounded reply that runs for minutes | you sent no `max_tokens` | [always send one](#always-send-max_tokens) |
| `unsloth-*` 404s here and 401s on 24000 | `UNSLOTH_API_KEY` was blank when the seed ran, so it skipped those endpoints | export it, run `up -d` again |
| `openrouter-free` 404s | **by design** — MLflow cannot carry the provider pin | use it on 24000 |
| An alias answers on 24000 and 404s here | you added it to `../litellm/config/` only, or the seed has not run since | `up -d`; if the name is not in the seed's log, add the `Endpoint(...)` to `config/<engine>.py` |
| An alias answers **here** but 400s on 24000 with `Invalid model name` | you changed `GATEWAY_ENGINE` and this gateway kept the previous engine's endpoints — it never deletes without `--prune` | `seed.py --prune`, after reading that file's header. Verified 2026-08-31 |
| MLflow answers 403 `Invalid Host header` | the caller's `Host` is not in `MLFLOW_SERVER_ALLOWED_HOSTS`, and `/health` is exempt so the container still looks healthy | add that `host:port` |
| Every alias fails on auth here, LiteLLM is fine | `MLFLOW_CRYPTO_KEK_PASSPHRASE` changed, so stored secrets no longer decrypt | `docker compose up -d` — the seed rewrites them |
| A 400 on an `openai-*` route that works on 24000 | the gpt-5 family rejects `max_tokens`, and this gateway forwards parameters exactly as sent | send `max_completion_tokens` |
| A health probe is green but nothing works | it probed a port another stack answers | this project uses **25000** on purpose, leaving the usual 5000 free |

## Layout

```text
mlflow/
├── compose.yml             postgres · mlflow · mlflow-seed. name: ai-gateway-mlflow
├── .env.example            tracked; the key lines are blank BY DESIGN
├── config/                 mounted at /app/config, read-only
│   ├── gateway.py              the MLflow API machinery, written once
│   ├── seed.py                 the entry point; picks the one engine and writes
│   └── <engine>.py             lms · unsloth · ollama · openrouter · openai
│                                an ENDPOINTS list each, and nothing else
├── discover/
│   └── gateway_discovery.py    the probes only, no renderer; standard library only
└── tests/                  a uv project: 3 call kinds + the contract test
```

**`config/` is a subdirectory and not this folder itself** because the folder also holds
`.env`, and mounting the folder would put your `.env` inside the container. The mount lands on
`/app/config`; before the split it was `/app/mlflow`, which Python could import as a namespace
package called `mlflow` and shadow the real library.
