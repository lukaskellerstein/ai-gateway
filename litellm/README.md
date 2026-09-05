# litellm — the primary gateway, on port 24000

A standalone compose project. Run it from **this** directory; nothing above it is read, and
nothing here reads `../envoy`.

```bash
cp .env.example .env      # edit GATEWAY_ENGINE if you do not run LMStudio
podman compose up -d      # first boot takes ~60 s: LiteLLM runs schema migrations

curl -fsS http://localhost:24000/health/readiness   # -> {"status":"healthy","db":"connected"}
```

`podman compose` works identically — the two are drop-in replacements here.

**This is the gateway your projects should call.** It is the only one with virtual keys, spend
logs, budget ceilings, `/v1/messages` and an admin UI. The alias names are shared with
`../envoy`; the table of what they point at is in [`../README.md`](../README.md).

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

**This is the one feature no other gateway here has.** `../envoy` checks no caller key at all,
and its budget equivalent — `QuotaPolicy` and token rate limiting — needs Redis and a full
Envoy Gateway install, which is the Kubernetes path this repo does not take.

## Use it from Claude Code

Claude Code speaks the Anthropic Messages API and nothing else. LiteLLM exposes
`/v1/messages` and translates it to whatever the alias points at, so Claude Code can drive
any model here and never learns it is not talking to Anthropic. **This is the simpler of the
two paths** — `../envoy` serves `/anthropic/v1/messages`, but only on a separate
`<alias>-anthropic` pass-through route, for the reason its README gives.

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
| `GATEWAY_ENGINE` | `lms` | **which engine this gateway serves** — one of `lms`, `unsloth`, `ollama`, `openrouter`, `openai`. Not a list. It is this project's alone: `../envoy` has its own, and nothing checks that they agree |
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

## Provider × route

**LiteLLM routes by the `model:` prefix, not by the alias name**, and the three routes do not
behave the same. This table is the memory: read it before chasing anything that looks like a
routing or reasoning bug, and add a row the day you measure one — **including a result that
did not work**, because those are what get re-tried.

The provider for each alias is in the root [`README.md`](../README.md) § The aliases.

| Provider | `/v1/chat/completions` | `/v1/messages` | `/v1/responses` |
|:--|:--|:--|:--|
| `lm_studio/` | works | works — never used the Responses bridge | works |
| `openai/` | works | **needs `use_chat_completions_url_for_anthropic_messages: true`** | works |
| `openrouter/` | works | works — not in the bridge set | works |

**The one quirk, in full.** `/v1/messages` picks its upstream path from
`_RESPONSES_API_PROVIDERS = frozenset({"openai"})`. Anything on the `openai/` provider is
bridged through the Responses API, and that bridge drops `reasoning_content` — so the Claude
Agent SDK got no thinking blocks at all from `unsloth-*`, `ollama-*` or `openai-*`, while
`lms-*` was fine because it is `lm_studio/`. The flag in
[`config/settings.yaml`](config/settings.yaml) forces the chat-completions path and carries
the full four-field header. Measured 2026-09-05 on 1.99.1, `unsloth-4b`: **6/6 streaming runs
carried thinking, against 0/5 before.**

**Tried and rejected, so nobody re-tries them:**

| Attempt | Result |
|:--|:--|
| Upgrade 1.95.0 → 1.99.1 on its own | no effect — 0/5. The bug is routing, not version |
| `model_info.supports_reasoning: true` | no effect — 0/3 |
| Waiting on BerriAI/litellm#29518, #27946 | **both already closed** before this was measured, and neither fixes it; #29518's fix shipped in 1.95.0 where it still reproduced |

**If a client ever needs the opposite of a global flag, do not flip it.** Give that alias its
own route — `model_info.supported_endpoints: ["/v1/messages"]` is per-alias — and record both
directions here. The rule is in
[`../.claude/rules/05-implement.md`](../.claude/rules/05-implement.md) § Settings that exist
for one client.

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
  on one and `discover` enumerates nothing, then writes a **pass-through**
  `discovered-<engine>.yaml` that just includes the hand-written file — so the gateway comes
  up serving exactly that list. **Until 2026-09-05 it exited 2 instead and LiteLLM
  crash-looped on `Config file not found`**, because compose had already built the filename.
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

**`discover/gateway_discovery.py` belongs to this project and is now the only copy.**
`../mlflow/discover/` held a second one until that folder was deleted on 2026-09-04.
`../envoy` has no discovery at all — its config needs another renderer and its image is
distroless, with no Python to run one in.

## Tests

`tests/` is **seven folders, one per way of calling this gateway**, ordered by distance from
the wire. Each is its own uv project; `uv run --directory` builds whichever venv is missing,
so a fresh clone needs no `uv sync`.

```bash
cd tests
uv run run_all.py                       # 7 rows against 24000
uv run run_all.py --only 6_codex_sdk    # one folder
uv run run_all.py --model ollama-4b     # any alias, everywhere
```

| Folder | Reaches this gateway through |
|:--|:--|
| `1_http_client` | `urllib` — no dependencies at all |
| `2_openai_client` | `openai` — 4 call kinds plus the contract test |
| `3_langchain_langgraph` | `ChatOpenAI(base_url=…)`, then the same loop built by hand |
| `4_deepagents` | a deep agent. Seven scenarios: query, todos, filesystem, tools, MCP, subagent, skill |
| `5_claude_agent_sdk` | `ANTHROPIC_BASE_URL` → **`/v1/messages`**, on the plain alias. Seven scenarios: query, session, in-process MCP, stdio MCP, subagent, skill, thinking |
| `6_codex_sdk` | a `model_providers` override → **`/v1/responses`** |
| `7_opencode_sdk` | an `@ai-sdk/openai-compatible` provider |

**All seven run here, and all seven run on `../envoy` too.** They run differently: folder 5
there needs an `<alias>-anthropic` pass-through route, because Envoy translates the Anthropic
body and this gateway does not.

It drives **this gateway only**. `2_openai_client/04_gateway_contract.py` asserts the four
claims `common.py` makes about how to call it — that a bad key gets 401, that `/models` lists
the aliases, that `response.model` echoes the alias, and that `/model/info` exposes each
route's stored ceiling. `../envoy/tests/` declares its own four, and only one of them matches.

The base URL, the key and the alias live once in `tests/gateway.py`, which every folder
imports and which depends on nothing outside the standard library.

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
| An alias answers here and 404s on 26000 | `openrouter-free` does this **by design**. Otherwise you added it to `config/` only | add the `AIGatewayRoute` rule to `../envoy/config/<engine>.yaml` and `up -d` there |
| An alias 404s after you changed `GATEWAY_ENGINE` | you are calling another engine's alias — only one engine is served at a time | `curl /model/info` for the names this engine serves |
| `litellm` restarts in a loop | `GATEWAY_ENGINE` is misspelled, or is an old value like `all` | `podman compose logs litellm` — it names the config file it could not open |
| `discover` shows as exited | it is a one-shot; exit 0 is the finished state | expected — `podman compose logs discover` |
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
└── tests/                  SEVEN folders, one per way of calling this gateway
    ├── gateway.py              base URL · key · alias, shared by all seven. stdlib only
    ├── run_all.py              runs every folder, one row each
    ├── 1_http_client/          urllib, NO dependencies
    ├── 2_openai_client/        openai — 4 call kinds + the contract test
    ├── 3_langchain_langgraph/  LangChain's agent, and the same loop by hand
    ├── 4_deepagents/           a deep agent. SEVEN scenarios + its own run_all.py
    ├── 5_claude_agent_sdk/     the ANTHROPIC surface, /v1/messages.
    │                            SEVEN scenarios + its own run_all.py
    ├── 6_codex_sdk/            the RESPONSES surface, /v1/responses
    └── 7_opencode_sdk/         an openai-compatible provider over the HTTP server API
```

`config/<engine>.yaml` is where the numbers live — every one carries a comment saying where it
came from.

**`config/` is a subdirectory and not this folder itself** because the folder also holds
`.env`, and mounting the folder would put your `.env` inside the container. It lands on
`/app/config` and never `/app/litellm`: the image already ships `/app/litellm`, which is the
proxy's own Python package, and mounting over it breaks the container.
