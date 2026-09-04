# litellm — the primary gateway, on port 24000

A standalone compose project. Run it from **this** directory; nothing above it is read, and
nothing here reads `../mlflow`.

```bash
cp .env.example .env      # edit GATEWAY_ENGINE if you do not run LMStudio
docker compose up -d      # first boot takes ~60 s: LiteLLM runs schema migrations

curl -fsS http://localhost:24000/health/readiness   # -> {"status":"healthy","db":"connected"}
```

`podman compose` works identically — the two are drop-in replacements here.

**This is the gateway your projects should call.** It is the only one with virtual keys, spend
logs, budget ceilings, `/v1/messages` and an admin UI. The alias names are shared with
`../mlflow`; the table of what they point at is in [`../README.md`](../README.md).

Three services: `postgres` (keys, spend, ceilings — no published port), `discover` (a one-shot
that exits, and does nothing unless discovery is on), and `litellm` itself.

> **Do not rename this compose project.** `name: ai-gateway` in `compose.yml` is what keeps it
> attached to the `ai-gateway_postgres_data` volume. Change the word and compose creates a new
> empty one, LiteLLM migrates a fresh schema, and every virtual key ever issued stops working.
> Nothing errors — it just comes up empty.

## Call it

Any OpenAI-compatible client works. Point `base_url` at `http://localhost:24000/v1`.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:24000/v1", api_key="sk-litellm-master")

r = client.chat.completions.create(
    model="lms-4b",                                    # an alias, not a model id
    messages=[{"role": "user", "content": "hi"}],
)
print(r.choices[0].message.content)
```

| Method | Path | Auth | What |
|:--|:--|:--|:--|
| `POST` | `/v1/chat/completions` | any key | the OpenAI route |
| `POST` | `/v1/messages` | any key | the Anthropic route — what Claude Code drives |
| `POST` | `/v1/embeddings` | any key | the running engine's `*-embed` alias |
| `GET` | `/health/readiness` | none | `{"status":"healthy","db":"connected"}` — **the probe to use** |
| `GET` | `/health/liveliness` | none | `"I'm alive!"` — the process is up, nothing more |
| `GET` | `/health` | master key | live per-model check; costs one call to each provider |
| `GET` | `/model/info` | master key | which aliases are actually registered |
| `POST` | `/key/generate` | master key | mint a capped key ([below](#budget-capped-keys)) |
| `GET` | `/key/info` | the key itself | its models, ceiling, spend and expiry |
| `GET` | `/spend/logs` | master key | every request, with `model`, `spend` and `api_base` |
| — | `/ui` | master key | admin UI; the Logs tab carries prompt and response |

## Budget-capped keys

The master key mints other keys and **has no ceiling of its own**, so it is not what a
project should hold. Issue a capped, expiring key instead, and check it with
`curl -H "Authorization: Bearer $KEY" http://localhost:24000/key/info`.

```bash
curl -X POST http://localhost:24000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"models":["lms-4b","lms-embed"],"max_budget":0.50,"duration":"24h"}'
```

Local routes are **shadow-priced**: free on your machine, but carrying a cloud twin's rate so
spend accrues and a ceiling can actually trip. That figure is "what this workload would cost in
the cloud", not money anyone was billed — anything summing `/spend/logs` has to say which of
the two it reports. Setting both `*_cost_per_token` values to `0` turns it off, at the cost of
ceilings no longer applying locally.

**This is the one feature no other gateway here has.** MLflow caps per endpoint, not per
caller, and has no key to hand a project at all.

## Use it from Claude Code

Claude Code speaks the Anthropic Messages API and nothing else. LiteLLM exposes
`/v1/messages` and translates it to whatever the alias points at, so Claude Code can drive
any model here and never learns it is not talking to Anthropic. **Stay on 24000 for this** —
the MLflow gateway has no equivalent route.

| Variable | Value | Why |
|:--|:--|:--|
| `ANTHROPIC_BASE_URL` | `http://localhost:24000` | **No `/v1` suffix** — Claude Code appends `/v1/messages` itself |
| `ANTHROPIC_AUTH_TOKEN` | a gateway key | sent as `Authorization: Bearer` |
| `ANTHROPIC_API_KEY` | the same value | sent as `x-api-key`. Set both; which one is used has moved between versions |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | an alias | what `/model sonnet` resolves to |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | an alias | what `/model opus` resolves to |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | an alias | background work — titles, summaries, suggestions |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | `1` | beta headers a non-Anthropic backend does not implement |
| `API_TIMEOUT_MS` | `3600000` | the default expires while a local model is still reading the prompt |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | the alias's `Input` figure | without it Claude Code assumes 200000 for every alias |

```bash
ANTHROPIC_BASE_URL="http://localhost:24000" \
ANTHROPIC_API_KEY="$AI_GATEWAY_KEY" \
ANTHROPIC_AUTH_TOKEN="$AI_GATEWAY_KEY" \
ANTHROPIC_DEFAULT_SONNET_MODEL="lms-4b" \
ANTHROPIC_DEFAULT_OPUS_MODEL="lms-4b" \
ANTHROPIC_DEFAULT_HAIKU_MODEL="lms-4b" \
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 \
API_TIMEOUT_MS=3600000 \
CLAUDE_CODE_MAX_CONTEXT_TOKENS=122880 \
claude
```

The same keys go in a `.claude/settings.json` `env` block if you want them to persist. Two
warnings about that file: **never commit a gateway key into it**, and an `env` block there
silently overrides anything you set on the command line.

Three traps, in the order people hit them:

1. **Set all three model variables.** Leave one unset and Claude Code sends a real Claude
   model id, which this gateway has never heard of:
   `Invalid model name passed in model=claude-...`. It looks like a broken proxy and is just
   an unmapped slot.
2. **Raise both timeouts, or neither matters.** Prompt processing measures ~100 tok/s here
   (17.6k tokens in 173 s), and Claude Code re-sends its system prompt and every tool schema
   each turn — so a real agent turn needs **5–15 minutes before the first token**. The
   gateway already carries `timeout: 3600` on every local route; if the client hangs up
   first, that patience is wasted.
3. **Never pick the `[1m]` variant in `/model`.** It forces a 1.0M window unconditionally and
   ignores `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, so auto-compact never fires in time.

**Tool calling works on all three default aliases.** `lms-4b`, `unsloth-4b` and `ollama-4b`
each returned a structured `tool_calls` reply — verified 2026-08-27, and re-verified on
`ollama-4b` 2026-08-31 — not the raw-text tool syntax that makes most local models useless
from an agent. Those runs go through the OpenAI route; `tests/` cannot drive `/v1/messages`,
so check a real Claude Code turn yourself before trusting an alias with agent work.

## Configuration

Two words in `.env` decide what this gateway serves. Compose interpolates from the **shell
environment first**, then `.env`.

```bash
GATEWAY_ENGINE=ollama
GATEWAY_DISCOVERY=
```

**There is no `COMPOSE_PROFILES` line.** It went with the split: the directory you stand in is
now the choice of gateway, and `up -d` here starts this one whether or not `.env` exists.

**Which engine.** One word, one engine. There is no list, no `all`, and no separate switch for
the cloud — a hosted provider is an engine like any other, and the alias prefix already says
which is which. That word names one file, `config/<engine>.yaml`. A typo is a clean crash: the
file does not exist and `litellm` exits saying so.

**Which models.** `GATEWAY_DISCOVERY` is empty by default, and then `config/<engine>.yaml` is
the whole vocabulary — see [Auto-discovery](#auto-discovery) below.

| Variable | Default | Used by |
|:--|:--|:--|
| `GATEWAY_ENGINE` | `lms` | **which engine this gateway serves** — one of `lms`, `unsloth`, `ollama`, `openrouter`, `openai`. Not a list. It is this project's alone: `../mlflow` has its own, and nothing checks that they agree |
| `GATEWAY_DISCOVERY` | *(blank)* | **which models** — blank means the hand-written list alone. `on` **adds** every model the engine holds on this machine. Local engines only. **`off` does not mean off** — compose reads any non-empty value as on, so leave it blank |
| `LITELLM_MASTER_KEY` | `sk-litellm-master` | the admin credential. **Change it for anything but a laptop** |
| `LM_STUDIO_API_BASE` | `http://host.containers.internal:1234/v1` | every `lms-*` alias |
| `UNSLOTH_API_BASE` | `http://host.containers.internal:8888/v1` | every `unsloth-*` alias |
| `UNSLOTH_API_KEY` | *(blank)* | **required** by every `unsloth-*` alias — Unsloth 401s every route without it. Blank keeps the alias and fails at call time |
| `OLLAMA_API_BASE` | `http://host.containers.internal:11434/v1` | every `ollama-*` alias. **There is no `OLLAMA_API_KEY`**: Ollama ignores the header. The config still sets a literal `sk-ollama`, because LiteLLM's `openai/` provider needs some key string |
| `OPENROUTER_API_KEY` | *(blank)* | every `openrouter-*` alias. **Real spend.** Without it the alias stays and 401s at call time |
| `OPENAI_API_KEY` | *(blank)* | every `openai-*` alias. **Real spend**, same failure |
| `DATABASE_URL` | set in `compose.yml` | **required** — without it `/key/generate` fails with `{"error":"No connected db."}` while completions keep working |
| `MAX_STRING_LENGTH_PROMPT_IN_DB` | `100000` | LiteLLM's own default of 2048 clips agent transcripts mid-run |

The defaults name `host.containers.internal`, which is Podman's name. Docker resolves it too
because `compose.yml` declares both — but write `host.docker.internal` if you override these.

The provider keys stay blank in `.env` on purpose when your shell already exports them from an
encrypted store: compose reads the shell first, so no second plaintext copy exists to go stale
after a rotation. Fill them in only if you have no such setup — see
[`.env.example`](.env.example).

## Auto-discovery

One line in `.env` adds every model the selected engine holds on **your** disk:

```bash
GATEWAY_DISCOVERY=on
```

At `up -d` the `discover` service asks the engine over its own HTTP API what it has, and writes
`config/discovered-<engine>.yaml` — one alias per model. The name is **the engine, a dash, and
the model id**, with anything unusable turned into a dash:

| Engine reports | Alias becomes |
|:--|:--|
| `google/gemma-4-e4b` | `lms-google-gemma-4-e4b` |
| `gemma4:26b` | `ollama-gemma4-26b` |
| `nomic-embed-text:latest` | `ollama-nomic-embed-text-latest` |

**It only ever adds.** The generated file *includes* the hand-written one, so `lms-4b`,
`lms-26b` and `lms-embed` keep answering exactly as before. A discovered name that would
collide with one is dropped. Turning discovery on cannot break anything a project already
calls. Turning it off is leaving the value **empty** and running `up -d` again.

**Models that are downloaded but not loaded are configured too.** LMStudio and Ollama both
report what is on disk, and both load a model on demand, so an unloaded model answers on the
first call — slowly the first time, then warm.

Verified 2026-09-03: `GATEWAY_ENGINE=unsloth` with discovery on wrote 15 discovered aliases
beside the 3 hand-written ones.

Three limits worth knowing before you switch it on:

- **It is local-only.** `lms`, `unsloth` and `ollama` are free, so a long list costs nothing.
  OpenRouter lists hundreds of models and every one bills a real account, so the two paid
  engines keep their hand-written lists and **money is never discovered**. Ask for discovery
  on one and the `discover` service refuses by name.
- **`GATEWAY_DISCOVERY=off` does not mean off.** compose builds the config filename with
  `${GATEWAY_DISCOVERY:+discovered-}`, which reacts to the word being *non-empty*, not to its
  meaning. `off`, `false`, `0` and `no` are caught and refused with exit 2; **leave the value
  empty** to turn it off.
- **Unsloth reports the names fine; the numbers are thin.** Its `/v1/models` gives every model
  on disk with its quantisation and whether it is loaded, so the aliases are complete. But it
  serves **one model at a time**, and it reports the context window **only for the loaded
  one** — 1 of 15 rows carried it on 2026-09-03, and the other 14 fall back to 8192, far below
  the 262144 the hand-written `unsloth-26b` carries. It also has no type field, so chat
  against embedding is guessed from the name. For the models it names,
  [`config/unsloth.yaml`](config/unsloth.yaml) stays the better route.

The generated file is gitignored, rewritten on every `up -d`, and worth reading once — it
carries the window and quantisation each model reported.

**`discover/gateway_discovery.py` is this project's own copy.** `../mlflow/discover/` has the
same three probe functions and no renderer, because MLflow has no config file. Fix a probe here
and copy it there.

## Tests

```bash
cd tests
uv sync                                 # once
uv run run_all.py                       # 4 rows against 24000
uv run run_all.py --model ollama-4b     # any alias
uv run 02_tools_call.py                 # one script
```

It drives **this gateway only**. `04_gateway_contract.py` asserts the four claims
`tests/common.py` makes about how to call it — that a bad key gets 401, that `/models` lists
the aliases, that `response.model` echoes the alias, and that `/model/info` exposes each
route's stored ceiling. `../mlflow/tests/` asserts the opposite four against its own gateway.

What is deliberately not covered is in [`tests/README.md`](tests/README.md).

## Troubleshooting

Every request lands in the admin UI's Logs tab at <http://localhost:24000/ui>, prompt and
response included. **Look there before changing configuration.**

| Symptom | Cause | Fix |
|:--|:--|:--|
| `unhealthy` for the first minute after `up -d` | schema migrations against an empty database | expected — wait out the 60 s `start_period` |
| `{"error":"No connected db."}` from `/key/generate` | the proxy booted without `DATABASE_URL` | `curl /health/readiness` — it reports `db` |
| **Every virtual key stopped working after an edit to `compose.yml`** | the `name:` line changed, so compose attached a new empty volume | put `name: ai-gateway` back and `up -d`; the old volume is untouched |
| A local alias fails instantly with a context error | LMStudio JIT-loaded it at 8192 | hand-load it — [`../README.md`](../README.md) § Load a model first |
| Empty content, `finish_reason: "length"` | a thinking model spent the whole `max_tokens` on reasoning | raise `max_tokens` on the call, or on the route in `config/` |
| `400 No model loaded` from `unsloth-*` | Unsloth serves one model at a time and auto-switch is off | turn on `Settings → API → Model auto-switch` |
| `unsloth-*` 401s | `UNSLOTH_API_KEY` was blank when `up -d` ran | export it, run `up -d` again |
| An `ollama-*` call that was fast a few minutes ago is slow again | Ollama evicted the idle model | expected — `ollama ps`, or raise `OLLAMA_KEEP_ALIVE` |
| `ollama-*` says `model not found` | the tag is not pulled | `ollama pull <tag>` — the ids are in [`config/ollama.yaml`](config/ollama.yaml) |
| An alias answers here and 404s on 25000 | `openrouter-free` does this **by design**. Otherwise you added it to `config/` only | add the `Endpoint(...)` to `../mlflow/config/<engine>.py` and `up -d` there |
| An alias 404s after you changed `GATEWAY_ENGINE` | you are calling another engine's alias — only one engine is served at a time | `curl /model/info` for the names this engine serves |
| `litellm` restarts in a loop | `GATEWAY_ENGINE` is misspelled, or is an old value like `all` | `docker compose logs litellm` — it names the config file it could not open |
| `discover` shows as exited | it is a one-shot; exit 0 is the finished state | expected — `docker compose logs discover` |
| `Engine protocol predict request failed: fetch failed` | a timeout fired mid-prompt and tore down the engine socket; it maps to a 400, and a 400 is never retried | raise **both** the client and the route timeout |
| An agent runs a step or two, executes nothing, exits cleanly | tool calls came back as raw text from the wrong OpenRouter free-tier provider | check the provider pin in [`config/openrouter.yaml`](config/openrouter.yaml) |
| A health probe is green but nothing works | it probed a port another stack answers | this project uses **24000** on purpose, leaving the usual 4000 free |

## Layout

```text
litellm/
├── compose.yml             postgres · discover · litellm. name: ai-gateway — DO NOT RENAME
├── .env.example            tracked; the key lines are blank BY DESIGN
├── config/                 mounted at /app/config, read-only
│   ├── settings.yaml           the three settings blocks; NO aliases
│   ├── <engine>.yaml           lms · unsloth · ollama · openrouter · openai
│   │                            each includes settings.yaml and declares its aliases
│   └── discovered-<engine>.yaml  GENERATED and gitignored; only when discovery is on
├── discover/
│   └── gateway_discovery.py    probes + the YAML renderer; standard library only
└── tests/                  a uv project: 3 call kinds + the contract test
```

`config/<engine>.yaml` is where the numbers live — every one carries a comment saying where it
came from.

**`config/` is a subdirectory and not this folder itself** because the folder also holds
`.env`, and mounting the folder would put your `.env` inside the container. It lands on
`/app/config` and never `/app/litellm`: the image already ships `/app/litellm`, which is the
proxy's own Python package, and mounting over it breaks the container.
