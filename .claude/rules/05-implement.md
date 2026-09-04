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
| an alias | `litellm/config/<engine>.yaml`, `mlflow/config/<engine>.py` **and** `envoy/config/<engine>.yaml` — three files |
| a LiteLLM settings block (`router_settings`, `general_settings`, …) | `litellm/config/settings.yaml` — once; every engine file includes it |
| MLflow seeding logic | `mlflow/config/gateway.py` — every engine gets it |
| how an engine is chosen | `mlflow/config/seed.py`, and the `--config` path in `litellm/compose.yml` |
| what auto-discovery finds, or how it renders | `litellm/discover/gateway_discovery.py` **and** `mlflow/discover/gateway_discovery.py` — two copies. `envoy/` has no discovery |
| an Envoy route, backend, timeout or buffer limit | `envoy/config/<engine>.yaml` — Kubernetes custom resources, self-contained per engine |
| services, ports, healthchecks, env | that project's `compose.yml` — never several in one edit unless the change is genuinely several |
| anything a caller reads | the README of the gateway it concerns, or `README.md` if it is shared |

**An alias is never one edit.** Each project owns its own list and none reads another's.
Add it on one side only and the name answers on that port and 404s on the others, with
nothing in any log to say why — and **no test catches it**, because the shared suite that
used to went with the split. Call it on **every** port afterwards —
[`06-testing.md`](06-testing.md).

**Adding an alias is a six-part edit**, and skipping any part is a bug that hides:

1. the `model_list` entry in `litellm/config/<engine>.yaml`
2. its price — an unpriced route logs `$0`, which makes a budget ceiling a no-op
3. its `max_input_tokens` — what `enable_pre_call_checks` uses to catch an over-long prompt
4. the matching `Endpoint(...)` in `mlflow/config/<engine>.py`
5. the matching `AIGatewayRoute` rule in `envoy/config/<engine>.yaml` — an exact
   `x-ai-eg-model` match, a `modelNameOverride`, and a `request` timeout
6. the alias table in `README.md` — a route nobody documents is a route nobody calls

**The alias name must carry its engine.** `lms-*`, `unsloth-*`, `ollama-*`,
`openrouter-*`, `openai-*`. No engine-neutral name, no capability name.

## The three projects must stay independent

They were split on 2026-09-03 at the user's explicit request, and `envoy/` was added on
2026-09-04 without touching either existing folder — which is the design working.
**Do not re-couple them.**
No shared module, no shared `.env`, no root `compose.yml`, and nothing in one folder that
reads a file in another. The costs are known and written down; they are not a defect to
fix.

The one thing that looks like a mistake and is not: **`discover/gateway_discovery.py` exists
twice.** LiteLLM's copy has the probes plus the YAML renderer; MLflow's has the probes only,
because MLflow has no config file to render. The probe functions are identical and both
headers say to fix them together. Deduplicating them would create a file neither project
could delete.

## The `compose.yml` files

- **`name:` IS THE MOST DANGEROUS LINE IN THIS REPO.** `litellm/compose.yml` carries
  `name: ai-gateway`, and the volume resolves to `<project>_postgres_data`. Change that word
  and compose attaches a NEW EMPTY volume: LiteLLM migrates a fresh schema and every virtual
  key, spend log and budget ceiling is gone, with no error anywhere. `mlflow/compose.yml`
  uses `ai-gateway-mlflow`, which is what lets both run at once.
- **`./config` mounts at `/app/config`, not `/app/litellm`.** The image already ships
  `/app/litellm` — the proxy's own Python package — and mounting over it breaks the
  container. The whole directory is mounted because each engine config includes
  `settings.yaml` by relative path.
- **`config/` is a subdirectory, not the folder itself.** The folder holds `.env` now, and
  mounting it would put a secrets file inside the container.
- **There are no `profiles:` any more.** The directory is the gateway switch. Do not
  reintroduce them.
- **`envoy/compose.yml` mounts at `/etc/aigw`, never `/app`.** `/app` IS the binary in that
  image. And `AIGW_DEBUG` must default to `false`, never to empty: aigw parses it as a bool
  and crash-loops on an empty string before reading any config.
- **`DATABASE_URL` is required, not optional.** Without it the proxy boots in no-DB mode:
  completions keep working while `/key/generate` fails with `{"error":"No connected db."}`.
  That is the worst failure for a budget guardrail — callers proceed uncapped and nothing
  looks broken.
- **`start_period: 60s`** covers first-boot schema migrations. Shorten it and a cold
  `up -d` reports unhealthy while working correctly.
- **No credential values.** `LITELLM_MASTER_KEY` is `${LITELLM_MASTER_KEY:-sk-litellm-master}`
  and the provider keys are `${..:-}`; the real values arrive from the shell.

## `litellm/` — gateway 1

`config/settings.yaml` holds the three settings blocks and the facts true of every alias
(timeouts, shadow pricing, reasoning). `config/<engine>.yaml` holds `model_list` and nothing
else. **MLflow has no place for prices, `max_tokens`, context windows or per-route timeouts,
so those live here and only here.**

- **Do not remove the provider pin** on `openrouter-free`. `order: ["google-ai-studio"]`
  plus `allow_fallbacks: false` exists because OpenRouter load-balances its free tier and
  one provider returns tool calls as raw text with `tool_calls` absent. Nothing errors: the
  agent sees a message with no tool calls, executes nothing, and stops.
- **`success_callback` is empty on purpose.** A trace store is a *project's* system of
  record; two projects sharing one experiment namespace makes "did this get better"
  ambiguous.

## `mlflow/` — gateway 2, and the only real code here

Seven files in `config/`. They exist because MLflow's gateway has no config file: its
endpoints live in the database and arrive over an API, so its alias list has to *be* Python.

| File | Is |
|:--|:--|
| `config/gateway.py` | the machinery: `Endpoint`, `env()`, the secret / definition / endpoint calls. No list, no CLI |
| `config/seed.py` | the CLI: reads `GATEWAY_ENGINE`, validates it, imports one engine file, calls `seed()` |
| `config/<engine>.py` | five files, each `ENDPOINTS = [...]` and nothing else |

- **It must NOT read anything in `../litellm/`.** That coupling was removed so the user can
  delete LiteLLM with MLflow still working. Reintroducing a YAML parse here to "stop the
  drift" undoes the change that was asked for. The drift is a known, documented cost.
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

## `envoy/` — gateway 3, and the only one you could deploy

`config/<engine>.yaml` is the same Kubernetes custom-resource API a cluster would read, so
what is proven here is what would ship. Five files, one per engine, each self-contained.

- **The alias mechanism is an `AIGatewayRoute` rule**: an exact `x-ai-eg-model` header match
  plus `modelNameOverride`. An alias with no rule gets 404.
- **Three numbers differ from upstream's example and must not be lowered.** `request: 60m`
  on BOTH the route and the backend (the smaller wins, and upstream's default is 3m);
  `bufferLimit: 50Mi` on the `ClientTrafficPolicy` (Envoy's 32 KiB default fails on a base64
  image); `logging.level: error` (at `debug` Envoy dumps request headers).
- **It has no discovery and no database.** Adding discovery needs a third renderer and a
  fourth image, because the aigw image is distroless. That gap is documented, not hidden.
- **It cannot do budgets.** `QuotaPolicy` and token rate limiting need Redis plus an Envoy
  Gateway install — the Kubernetes path. Do not add a shim that pretends otherwise.

## The three `tests/`

One script per **kind** of call, never per alias — `--model` already covers "the same test
on a different alias". **Each of the three suites drives its own gateway only**; there is no
`--gateway` flag any more, because the folder is the answer.

- **The differences go in `Gateway`, as data — never in a scenario.** The vocabulary is
  shared between the projects; the calling contract is not. Four things differ (the API key,
  the model listing, what `response.model` echoes, and whether a route stores a
  `max_tokens`), and all four are declared once on that project's `common.Gateway`. A
  scenario applies the contract by spreading `**gateway.body_extras` into its request and
  reads nothing else.
- **`01`–`03` are byte-identical across all three projects on purpose.** They never name a
  gateway, so a scenario written for one can be copied to the others unchanged. Keep it that
  way — a scenario that reads `gateway.name` has stopped being portable.
- **The three contracts are genuinely different, and Envoy is not "MLflow again".** It lists
  its models like LiteLLM and checks no key like MLflow. Anything written as "LiteLLM or
  not-LiteLLM" is wrong about it.
- **`04_gateway_contract.py` is the ONE script that is about its gateway**, and even it does
  not branch on the name: it checks the DECLARED table against observed behaviour, so a
  failure reads "the table says X and the gateway did Y". Add a difference to a table and
  add its check there, in the same commit.
- **`02_tools_call.py` checks `finish_reason` and the `tool_calls` structure**, not the
  words in the reply. A model emitting raw-text tool syntax returns a perfectly
  good-looking message — that is the failure the file exists to catch.
- **Its tools return fixed numbers.** A test calling a real API cannot tell "the gateway is
  broken" from "the market is closed".
- `run_all.py` globs `NN_*.py`, so a new script needs no edit there.

## The four `README.md`

**`README.md` at the root is the front door**, written for a stranger: what the repo is,
which gateway to pick, the shared alias table, the host-engine facts, the design decisions.
Each gateway's own `README.md` carries everything specific to it — its endpoints, its
configuration table, its discovery, its troubleshooting, its layout.

Keep all three slim: a new fact replaces a vaguer one rather than being appended. Deep
per-alias measurement belongs in the comments of `litellm/config/<engine>.yaml`. No absolute
home paths.

They carry **verified-on dates** against specific claims. Re-verify one and move the date;
change what it describes without re-testing and delete the claim, rather than leaving a
date vouching for something untested.

## Repository structure

```text
ai-gateway/
├── README.md               the front door and the shared vocabulary
├── litellm/                compose project `ai-gateway`         PORT 24000
│   ├── compose.yml             postgres · discover · litellm. name: DO NOT RENAME
│   ├── .env.example            tracked; the key lines are blank BY DESIGN
│   ├── config/                 settings.yaml + <engine>.yaml, mounted read-only
│   ├── discover/               probes + the YAML renderer; stdlib only
│   ├── tests/                  a uv project: 3 call kinds + the contract test
│   └── README.md
├── mlflow/                 compose project `ai-gateway-mlflow`  PORT 25000
│   ├── compose.yml             postgres · mlflow · mlflow-seed
│   ├── .env.example
│   ├── config/                 gateway.py · seed.py · <engine>.py
│   ├── discover/               the probes ONLY, no renderer
│   ├── tests/
│   └── README.md
├── envoy/                  compose project `ai-gateway-envoy`   PORT 26000/26064
│   ├── compose.yml             ONE service, no database
│   ├── .env.example
│   ├── config/                 <engine>.yaml — Kubernetes custom resources
│   ├── tests/                  NO discover/ — see envoy/README.md
│   └── README.md
└── .claude/                this contract
```
