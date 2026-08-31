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

**Never report completion without bringing the stack up and getting a real answer out of
the alias you touched.** A mistyped `api_base` parses perfectly and fails on the first
call. Verification is your job — the user should never have to ask.

Reference: [`01-project-config.md`](rules/01-project-config.md) (services, ports, engines,
aliases) · [`09-code-quality.md`](rules/09-code-quality.md) ·
[`11-communication.md`](rules/11-communication.md) ·
[`12-security.md`](rules/12-security.md) ·
[`machine-tools.md`](rules/machine-tools.md) (`nvim-tools`, `lukas-ps` — pre-approved,
read-only) · [`lsp.md`](rules/lsp.md) (no `lsp-*` plugin here, so use `grep`).

## The repo in ten points

- **Four containers.** `litellm` on **24000** (UI at `/ui`), `postgres` unpublished
  (virtual keys, spend logs, budget ceilings), `mlflow` on **25000**, and `mlflow-seed`, a
  one-shot whose finished state is **exited (0)**.
- **TWO WORDS IN `.env` DECIDE WHAT RUNS**, and they are independent:

  | Variable | Values | Default | Picks |
  |:--|:--|:--|:--|
  | `COMPOSE_PROFILES` | `litellm`, `mlflow`, `litellm,mlflow`, `all` | *(nothing starts)* | which gateway |
  | `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `openrouter`, `openai` | `lms` | which engine |

  With no `.env` at all, `up -d` starts postgres and nothing else. That is configured
  behaviour, not a fault.
- **ONE ENGINE AT A TIME.** No list, no `all`, no starter/full split. `GATEWAY_ENGINE`
  names one file per gateway — `litellm/<engine>.yaml` and `mlflow/<engine>.py` — so the
  two can never serve different engines. Each engine has two or three aliases; every other
  alias is absent from the running config, and a 404 on one is correct.
- **EACH GATEWAY OWNS ITS OWN LIST, and nothing in `mlflow/` reads anything in
  `litellm/`.** Deliberate: LiteLLM must stay deletable. **The price is that an alias is
  TWO edits.** Do one and the name answers on 24000 and 404s on 25000, with nothing in
  either log to say why. Do not "fix" this by making the seed parse the YAML.
- **Every alias names its engine** — `lms-*`, `unsloth-*`, `ollama-*`, `openrouter-*`,
  `openai-*`. There is no engine-neutral name (`local` was removed) and no capability name
  (`cheap`, `standard`, `frontier` were removed): the first hid which engine answered, the
  second hid who was billed.
- **The prefix is the money warning.** The three local engines are free; `openrouter` and
  `openai` bill a real account. **No alias falls back to another**, so a request costs
  money only when a caller names a route that costs money.
- **Local routes are shadow-priced** — free, but carrying a cloud twin's rate so budget
  ceilings still trip. Anything summing `/spend/logs` must say whether it reports money
  billed or the cost of the same workload in the cloud.
- **Almost no code.** `compose.yml`, six YAML in `litellm/`, seven Python in `mlflow/`,
  `tests/`, `README.md`. All three images are stock — there is no build step.
- **Ports 24000 / 25000 are deliberate.** The failure avoided is not a bind error but the
  silent one: a health probe against `localhost:4000` that another stack answers, going
  green.
- **Health**: `curl -fsS http://localhost:24000/health/readiness` →
  `{"status":"healthy","db":"connected"}`. Use readiness, not liveliness — only readiness
  reports the database, and a proxy that booted without one still serves completions.
  MLflow: `/health` → `OK`. First boot takes ~60 s for schema migrations.

Full facts → [`rules/01-project-config.md`](rules/01-project-config.md).

## Standing authorizations — do NOT ask before doing these

**Read-only, always safe:** `podman compose ps | config | logs`; `curl` against 24000
(`/health/readiness`, `/health`, `/model/info`, `/key/info`, `/spend/logs`, completions)
and 25000 (`/health`, `/version`, completions); `cd tests && uv sync && uv run
run_all.py`; `lms ps --json`; `ollama ps | list`; `podman compose exec postgres psql -U
postgres -c "SELECT ..."` — **`SELECT` only**; `git status | diff | log`; reading any file
here. **`.env` is denied to you — ask the user what is in it.**

Calling a **free** alias to check something is always fine. A **paid** one
(`openrouter-*`, `openai-*`) costs money, so keep it to one short call.

**Pre-approved mutations:** editing `compose.yml`, `litellm/`, `mlflow/`,
`postgres/init-databases.sh`, `README.md`, `LICENSE`, `.env.example`, `.claude/`,
`tests/`; `up -d`, `restart`, and `down` **without `-v`**; re-running the seed; bringing
the stack up on another engine for a test — **then putting it back the way you found
it**; minting a virtual key that carries **both** `max_budget` ≤ 2.00 and
`duration` ≤ `7d`.

## Requires confirmation — always ask first

- **`down -v`**, or anything else removing the `postgres_data` volume. It destroys every
  virtual key, all spend history and every budget ceiling, unrecoverably — the keys other
  projects hold stop working at that moment.
- **Removing or weakening the provider pin** (`order: ["google-ai-studio"]`,
  `allow_fallbacks: false`) in `litellm/openrouter.yaml`. It looks like dead configuration
  and is the only thing preventing raw-text tool calls that make agents silently do
  nothing.
- **Selecting a paid engine** — `GATEWAY_ENGINE=openrouter` or `openai` — on a stack the
  user did not ask to make billable.
- **Changing `LITELLM_MASTER_KEY`**, or minting a key with no `max_budget` or no
  `duration`. Both hand out spend against real provider accounts.
- **`lms load` / `lms unload`** on the host. It can evict a model another session is
  mid-request against, and several sessions run here at once.
- **Changing the published ports**, or publishing `postgres`. All three re-enter the
  collision the 2xxxx band exists to avoid.
- **`mlflow/seed.py --prune`**, or dropping the `mlflow` database. `--prune` deletes every
  endpoint the run does not name — which is **every other engine's** — and their
  `gateway/*` traces lose the endpoint they belong to.
- **Changing `MLFLOW_CRYPTO_KEK_PASSPHRASE` on a stack that has already run.** Stored
  credentials stop decrypting, and it surfaces as an auth error at call time, not at
  startup.
- Setting `lms-26b`'s `*_cost_per_token` to `0`. It silently disables every budget ceiling
  for local traffic.
- `git push`, force-push, branch deletes. **Never commit unless the user explicitly asks.**
- Anything touching secrets, TLS material or credential files →
  [`12-security.md`](rules/12-security.md).

When in doubt, ask. **Every project on this laptop calls this gateway** — a bad edit here
does not break one repo, it takes LLM access away from all of them at once.
