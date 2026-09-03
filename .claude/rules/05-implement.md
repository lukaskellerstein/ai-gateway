# Step 3: Implement

- **Do not commit unless the user explicitly asks.**
- Write clean code from the start; refactor as you go rather than "later".
- Delete dead code. No commented-out blocks kept "just in case", no TODOs.
- Use `mermaid` for diagrams.

This repo is almost all configuration, so what those rules mean here: **a config change is
still a change, and the comments are the reasoning.** Keep them accurate rather than tidy —
every number carries a comment saying where it came from.

## Which file to edit

| Change | Goes in |
|:--|:--|
| an alias | `litellm/<engine>.yaml` **and** `mlflow/<engine>.py` — two files |
| a LiteLLM settings block (`router_settings`, `general_settings`, …) | `litellm/settings.yaml` — once; every engine file includes it |
| MLflow seeding logic | `mlflow/gateway.py` — every engine gets it |
| how an engine is chosen | `mlflow/seed.py`, and the `--config` path in `compose.yml` |
| what auto-discovery finds, or how it renders | `discover/gateway_discovery.py` — one file, both gateways |
| services, profiles, ports, healthchecks, env | `compose.yml` |
| anything a caller reads | `README.md` — the one doc, written for the public |

**An alias is never one edit.** Each gateway owns its own list and neither reads the
other. Add it on one side only and the name answers on 24000 and 404s on 25000, with
nothing in either log to say why. Call it on **both** ports afterwards —
[`06-testing.md`](06-testing.md).

**Adding an alias is a five-part edit**, and skipping any part is a bug that hides:

1. the `model_list` entry in that engine's YAML
2. its price — an unpriced route logs `$0`, which makes a budget ceiling a no-op
3. its `max_input_tokens` — what `enable_pre_call_checks` uses to catch an over-long prompt
4. the matching `Endpoint(...)` in `mlflow/<engine>.py`
5. the alias table in `README.md` — a route nobody documents is a route nobody calls

**The alias name must carry its engine.** `lms-*`, `unsloth-*`, `ollama-*`,
`openrouter-*`, `openai-*`. No engine-neutral name, no capability name.

## `compose.yml`

- **`./litellm` mounts at `/app/config`, not `/app/litellm`.** The image already ships
  `/app/litellm` — the proxy's own Python package — and mounting over it breaks the
  container. The whole directory is mounted because each engine config includes
  `settings.yaml` by relative path.
- **Both gateways carry `profiles:`, `postgres` carries none.** That is what lets
  `COMPOSE_PROFILES` switch a gateway off, and why an empty `.env` starts postgres alone.
- **`DATABASE_URL` is required, not optional.** Without it the proxy boots in no-DB mode:
  completions keep working while `/key/generate` fails with `{"error":"No connected db."}`.
  That is the worst failure for a budget guardrail — callers proceed uncapped and nothing
  looks broken.
- **`start_period: 60s`** covers first-boot schema migrations. Shorten it and a cold
  `up -d` reports unhealthy while working correctly.
- **No credential values.** `LITELLM_MASTER_KEY` is `${LITELLM_MASTER_KEY:-sk-litellm-master}`
  and the provider keys are `${..:-}`; the real values arrive from the shell.

## `litellm/` — gateway 1

`settings.yaml` holds the three settings blocks and the facts true of every alias
(timeouts, shadow pricing, reasoning). `<engine>.yaml` holds `model_list` and nothing
else. **MLflow has no place for prices, `max_tokens`, context windows or per-route
timeouts, so those live here and only here.**

- **Do not remove the provider pin** on `openrouter-free`. `order: ["google-ai-studio"]`
  plus `allow_fallbacks: false` exists because OpenRouter load-balances its free tier and
  one provider returns tool calls as raw text with `tool_calls` absent. Nothing errors: the
  agent sees a message with no tool calls, executes nothing, and stops.
- **`success_callback` is empty on purpose.** A trace store is a *project's* system of
  record; two projects sharing one experiment namespace makes "did this get better"
  ambiguous.

## `mlflow/` — gateway 2, and the only code here

Seven files. They exist because MLflow's gateway has no config file: its endpoints live in
the database and arrive over an API, so its alias list has to *be* Python.

| File | Is |
|:--|:--|
| `gateway.py` | the machinery: `Endpoint`, `env()`, the secret / definition / endpoint calls. No list, no CLI |
| `seed.py` | the CLI: reads `GATEWAY_ENGINE`, validates it, imports one engine file, calls `seed()` |
| `<engine>.py` | five files, each `ENDPOINTS = [...]` and nothing else |

- **It must NOT read anything in `litellm/`.** That coupling was removed on purpose so the
  user can delete LiteLLM with MLflow still working. Reintroducing a YAML parse here to
  "stop the drift" undoes the change that was asked for. The drift is a known, documented
  cost.
- **The engine word is validated by hand, not with argparse `choices`.** A default that
  came from the environment is never checked against `choices`, and the environment is
  exactly where the typo comes from.
- **`check_secrets` fails fast on purpose.** One `secret` name must mean one
  `api_base` + `api_key` pair, or one alias 401s with nothing in the log to explain it.
- **`fallback_config` is what activates a chain.** A `FALLBACK` linkage is stored and shown
  in the UI whether or not it is passed; the gateway only wraps the primary when the config
  object is there. No endpoint uses one today.
- **It stays idempotent.** compose runs it on every `up -d`. Secrets are the deliberate
  exception — rewritten each run, which is how a rotated key reaches the gateway.
- **A LiteLLM feature with no MLflow equivalent is documented, not faked.** A shim that
  half-implements one is worse than the gap, because it reads as working.

## `tests/`

One script per **kind** of call, never per alias — `--model` already covers "the same test
on a different alias".

- **A scenario never names a gateway.** The point is that the client, the alias and the
  messages are identical on 24000 and 25000. A scenario that branches on `gateway.name` has
  stopped testing that.
- **The differences go in `Gateway`, as data — never in a scenario.** The vocabulary is
  shared; the calling contract is not. Four things differ (the API key, the model listing,
  what `response.model` echoes, and whether a route stores a `max_tokens`), and all four are
  declared once on `common.Gateway`. A scenario applies the contract by spreading
  `**gateway.body_extras` into its request and reads nothing else, so it still cannot behave
  differently depending on which gateway it got.
- **`04_gateway_contract.py` is the ONE script allowed to care which gateway it is on**,
  because the difference is its whole subject. Even it does not branch on the name: it checks
  the DECLARED table against observed behaviour, so a failure reads "the table says X and the
  gateway did Y". Add a difference to the table and add its check there, in the same commit.
- **`02_tools_call.py` checks `finish_reason` and the `tool_calls` structure**, not the
  words in the reply. A model emitting raw-text tool syntax returns a perfectly
  good-looking message — that is the failure the file exists to catch.
- **Its tools return fixed numbers.** A test calling a real API cannot tell "the gateway is
  broken" from "the market is closed".
- `run_all.py` globs `NN_*.py`, so a new script needs no edit there.

## `README.md`

**The one document, written for the public** — a stranger's front door, not a lab
notebook. Keep it slim: a new fact replaces a vaguer one rather than being appended. Deep
per-alias measurement belongs in the comments of `litellm/<engine>.yaml`. No absolute home
paths, no reference to another repo on this machine.

It carries **verified-on dates** against specific claims. Re-verify one and move the date;
change what it describes without re-testing and delete the claim, rather than leaving a
date vouching for something untested.

## Repository structure

```text
ai-gateway/
├── compose.yml             four services, profiles, ports, healthchecks, env
├── .env.example            tracked; the key lines are blank BY DESIGN
├── litellm/                gateway 1 — YAML
│   ├── settings.yaml           the 3 settings blocks; NO aliases
│   └── <engine>.yaml           lms · unsloth · ollama · openrouter · openai
├── mlflow/                 gateway 2 — Python; reads nothing in litellm/
│   ├── gateway.py              the MLflow API machinery
│   ├── seed.py                 the CLI: picks one engine, validates, writes
│   └── <engine>.py             the same five names, an ENDPOINTS list each
├── discover/               auto-discovery, OFF by default; stdlib only
│   └── gateway_discovery.py    probes a local engine; renders LiteLLM's config
├── postgres/init-databases.sh  CREATE DATABASE mlflow, fresh volume only
├── tests/                  a uv project: 3 call kinds + the contract test, both gateways
├── README.md               the ONE doc
└── .claude/                this contract
```
