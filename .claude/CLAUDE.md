# ai-gateway — the working contract

## Workflow — mandatory for any prompt that changes something

If you will use Edit or Write, or run `podman compose` / `docker compose` here, complete
all five steps before reporting. Applies to every kind of work — compose, aliases, docs,
troubleshooting.

1. **Understand** → [`rules/02-understand.md`](rules/02-understand.md)
2. **Plan** → [`rules/03-plan.md`](rules/03-plan.md) *(skip for trivial changes)*
3. **Implement** → [`rules/05-implement.md`](rules/05-implement.md)
4. **Test** → [`rules/06-testing.md`](rules/06-testing.md)
5. **Report** → [`rules/08-report.md`](rules/08-report.md)

**Never report completion without bringing the gateway up and getting a real answer out of
the alias you touched.** A mistyped `api_base` parses perfectly and fails on the first
call. Verification is your job — the user should never have to ask.

Reference: [`01-project-config.md`](rules/01-project-config.md) (services, ports, engines,
aliases) · [`09-code-quality.md`](rules/09-code-quality.md) ·
[`11-communication.md`](rules/11-communication.md) ·
[`12-security.md`](rules/12-security.md) ·
[`machine-tools.md`](rules/machine-tools.md) (`nvim-tools`, `lukas-ps` — pre-approved,
read-only) · [`lsp.md`](rules/lsp.md) (no `lsp-*` plugin here, so use `grep`).

## The repo in a dozen points

- **THREE STANDALONE COMPOSE PROJECTS, AND NOTHING AT THE ROOT.** There is no root
  `compose.yml`, no root `.env` and no root `tests/`. You start a gateway by entering its
  folder. Split 2026-09-03; `envoy/` added 2026-09-04:

  | Folder | Project name | Port | Services |
  |:--|:--|:--|:--|
  | `litellm/` | **`ai-gateway`** | 24000 | `postgres`, `discover`, `litellm` |
  | `mlflow/` | `ai-gateway-mlflow` | 25000 | `postgres`, `mlflow`, `mlflow-seed` |
  | `envoy/` | `ai-gateway-envoy` | 26000, 26064 | `envoy` — **one service, no database** |

  `discover` and `mlflow-seed` are one-shots whose finished state is **exited (0)**. The
  first two run **their own postgres**; neither publishes a port. `envoy/` is `aigw run`,
  Envoy AI Gateway's standalone mode: a real Envoy data plane from one config file, no
  Kubernetes, no build step.
- **`name: ai-gateway` IN `litellm/compose.yml` IS LOAD-BEARING.** The volume resolves to
  `<project>_postgres_data`, so that word is what keeps it attached to
  `ai-gateway_postgres_data` — every virtual key, spend log and budget ceiling ever issued.
  Rename the project and compose creates a NEW EMPTY volume, LiteLLM migrates a fresh
  schema, and every key other projects hold stops working. **Nothing errors.**
- **THERE IS NO `COMPOSE_PROFILES` ANY MORE.** It was the gateway switch until the split;
  the directory is now that switch. Two words remain, per project, in that project's own
  `.env`:

  | Variable | Values | Default | Picks |
  |:--|:--|:--|:--|
  | `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `openrouter`, `openai` | `lms` | which engine |
  | `GATEWAY_DISCOVERY` | *(empty)*, `on` | *(empty)* | which models |

- **THE TWO PROJECTS CAN SERVE DIFFERENT ENGINES, and nothing notices.** Each has its own
  `.env` and its own `GATEWAY_ENGINE`. Before the split one word drove both and they could
  not diverge. If a comparison is the point, check both `.env` files first.
- **AUTO-DISCOVERY IS OFF BY DEFAULT AND IS PURELY ADDITIVE.** With `GATEWAY_DISCOVERY`
  empty nothing changes: each gateway serves exactly the aliases its hand-written file
  names, and those files stay as the worked example of hand configuration. Set it and the
  gateway ADDS every model the engine holds on disk, named `<engine>-<slugged model id>`
  (`lms-google-gemma-4-e4b`, `ollama-gemma4-26b`). LiteLLM's generated
  `litellm/config/discovered-<engine>.yaml` **includes** the hand-written file and MLflow's
  seed **appends** to the hand-written list, so a hand-written alias can never be replaced
  or shadowed. **Discovery is local-only** — `openrouter` and `openai` are refused by name,
  because money is never discovered.
- **`GATEWAY_DISCOVERY=off` DOES NOT TURN IT OFF.** compose builds the config filename with
  `${GATEWAY_DISCOVERY:+discovered-}`, which reacts to the word being non-empty, not to its
  meaning. Both projects catch `off`, `false`, `0` and `no` and refuse. **The way to turn it
  off is an EMPTY value.**
- **ONE ENGINE AT A TIME, per project.** No list, no `all`. `GATEWAY_ENGINE` names one file
  — `litellm/config/<engine>.yaml`, `mlflow/config/<engine>.py` or
  `envoy/config/<engine>.yaml`. Each engine has two or
  three aliases; every other alias is absent from the running config, and a 404 on one is
  correct.
- **NOTHING IS SHARED BETWEEN THE FOLDERS — including the auto-discovery prober.**
  `litellm/` and `mlflow/` each carry their own copy of `discover/gateway_discovery.py`:
  LiteLLM's has the probes plus the YAML renderer, MLflow's has the probes only. The probe
  functions are identical, and both headers say to fix them together. This duplication is
  deliberate — a shared module would be a file neither project could delete.
- **`envoy/` HAS NO DISCOVERY AT ALL, and that is a gap not a decision.** It would need a
  third renderer (AIGatewayRoute rules), and the aigw image is distroless — no shell, no
  Python — so there is nowhere to run one without a fourth image. `envoy/README.md` says so.
- **ENVOY'S OWN TRAPS, all measured 2026-09-04:**
  - `AIGW_DEBUG` must never be EMPTY. aigw parses it as a bool and crash-loops on `""`
    before reading any config. `${AIGW_DEBUG:-false}`, not `${AIGW_DEBUG:-}`.
  - **`/health` on 26064 goes green BEFORE 26000 accepts a connection.** Probe
    `26000/v1/models` instead, which needs no key.
  - **With `AIGW_DEBUG=false` there is NO per-request logging at all.** Envoy's stdout goes
    to a file inside a distroless container. `true` gives the JSON access line AND a full
    prompt/response dump.
  - **`compose exec` cannot work** — distroless, no shell. Use `compose logs`.
  - The config mounts at `/etc/aigw`, never `/app`: `/app` IS the binary.
- **AN ALIAS IS THREE EDITS, AND NOTHING CHECKS THAT YOU DID THEM ALL.** Add it to
  `litellm/config/<engine>.yaml`, `mlflow/config/<engine>.py` **and**
  `envoy/config/<engine>.yaml`. Do one and the name answers on that port and 404s on the
  others, with nothing in any log to say why. The shared test suite that used to catch this
  went with the split — each project now tests only itself. Do not "fix" this by making one
  project read another's files.
- **Every alias names its engine** — `lms-*`, `unsloth-*`, `ollama-*`, `openrouter-*`,
  `openai-*`. There is no engine-neutral name (`local` was removed) and no capability name
  (`cheap`, `standard`, `frontier` were removed): the first hid which engine answered, the
  second hid who was billed. **The prefix is the money warning** — the three local engines
  are free; `openrouter` and `openai` bill a real account. **No alias falls back to
  another**, so a request costs money only when a caller names a route that costs money.
- **Local routes are shadow-priced** — free, but carrying a cloud twin's rate so budget
  ceilings still trip. Anything summing `/spend/logs` must say whether it reports money
  billed or the cost of the same workload in the cloud.
- **Almost no code.** Three `compose.yml`, six YAML in `litellm/config/`, seven Python in
  `mlflow/config/`, five YAML in `envoy/config/`, two copies of one discovery module, three
  `tests/`, four `README.md`. All four images are stock — there is no build step, and neither
  `discover/` reaches for anything outside the standard library.
- **Ports 24000 / 25000 / 26000 are deliberate.** The failure avoided is not a bind error
  but the silent one: a health probe against `localhost:4000` that another stack answers,
  going green.
- **Health**: `curl -fsS http://localhost:24000/health/readiness` →
  `{"status":"healthy","db":"connected"}`. Use readiness, not liveliness — only readiness
  reports the database, and a proxy that booted without one still serves completions.
  MLflow: `/health` → `OK`. First boot takes ~60 s for schema migrations. **Envoy: probe
  `26000/v1/models`, NOT `26064/health`** — the admin port answers before the data plane
  does.

Full facts → [`rules/01-project-config.md`](rules/01-project-config.md).

## Standing authorizations — do NOT ask before doing these

**Read-only, always safe:** `podman compose ps | config | logs` **from inside a gateway
folder**; `curl` against 24000 (`/health/readiness`, `/health`, `/model/info`, `/key/info`,
`/spend/logs`, completions), 25000 (`/health`, `/version`, completions) and 26000
(`/v1/models`, completions) / 26064 (`/health`, `/metrics`);
`cd litellm/tests && uv sync && uv run run_all.py`, and the same in `mlflow/tests` and
`envoy/tests`;
`lms ps --json`; `ollama ps | list`; `podman compose exec postgres psql -U postgres -c
"SELECT ..."` — **`SELECT` only**; `git status | diff | log`; reading any file here.
**`litellm/.env`, `mlflow/.env` and `envoy/.env` are denied to you — ask the user what is
in them.**

> **`compose config` PRINTS SECRETS.** Compose reads the shell first, and `~/Projects/.envrc`
> exports the real provider keys — so a bare `compose config` dumps `UNSLOTH_API_KEY` and the
> rest in plaintext into the transcript. Filter it (`| grep -v API_KEY`) or use
> `compose config --services`. This happened on 2026-09-03 and cost a key rotation.

Calling a **free** alias to check something is always fine. A **paid** one
(`openrouter-*`, `openai-*`) costs money, so keep it to one short call.

**Pre-approved mutations:** editing `litellm/`, `mlflow/`, `envoy/`, `README.md`, `LICENSE`,
`.claude/`; `up -d`, `restart`, and `down` **without `-v`** in any project; re-running
the seed or `discover`; bringing a gateway up on another engine for a test — **then putting
it back the way you found it**; minting a virtual key that carries **both** `max_budget`
≤ 2.00 and `duration` ≤ `7d`.

## Requires confirmation — always ask first

- **Changing `name:` in `litellm/compose.yml`.** It silently detaches the postgres volume
  holding every virtual key, spend log and budget ceiling. See point 2 above.
- **`down -v`**, or anything else removing a `postgres_data` volume. On the LiteLLM project
  it destroys every virtual key, all spend history and every budget ceiling, unrecoverably —
  the keys other projects hold stop working at that moment.
- **Removing or weakening the provider pin** (`order: ["google-ai-studio"]`,
  `allow_fallbacks: false`) in `litellm/config/openrouter.yaml`. It looks like dead
  configuration and is the only thing preventing raw-text tool calls that make agents
  silently do nothing.
- **Selecting a paid engine** — `GATEWAY_ENGINE=openrouter` or `openai` — in a project the
  user did not ask to make billable. Bringing one UP without calling it spends nothing and is
  how `envoy/config/openrouter.yaml` and `openai.yaml` were checked; a COMPLETION through one
  is what costs money.
- **Changing `LITELLM_MASTER_KEY`**, or minting a key with no `max_budget` or no
  `duration`. Both hand out spend against real provider accounts.
- **`lms load` / `lms unload`** on the host. It can evict a model another session is
  mid-request against, and several sessions run here at once.
- **Changing the published ports**, or publishing a `postgres`. All three re-enter the
  collision the 2xxxx band exists to avoid.
- **`seed.py --prune`**, or dropping the `mlflow` database. `--prune` deletes every endpoint
  the run does not name — which is **every other engine's** — and their `gateway/*` traces
  lose the endpoint they belong to.
- **Changing `MLFLOW_CRYPTO_KEK_PASSPHRASE` on a project that has already run.** Stored
  credentials stop decrypting, and it surfaces as an auth error at call time, not at startup.
- Setting `lms-26b`'s `*_cost_per_token` to `0`. It silently disables every budget ceiling
  for local traffic.
- **Re-coupling the projects** — a shared module, a shared `.env`, a root `compose.yml`, or
  anything in one folder that reads a file in another. The separation was asked for
  explicitly; its costs are known and documented.
- `git push`, force-push, branch deletes. **Never commit unless the user explicitly asks.**
- Anything touching secrets, TLS material or credential files →
  [`12-security.md`](rules/12-security.md).

When in doubt, ask. **Every project on this laptop calls this gateway** — a bad edit here
does not break one repo, it takes LLM access away from all of them at once.
