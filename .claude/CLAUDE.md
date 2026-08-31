# WORKFLOW — MANDATORY FOR ANY PROMPT THAT RESULTS IN CHANGES

**If you are going to use the Edit or Write tool, or run `podman compose` /
`docker compose` against this stack, you MUST complete the workflow in `rules/`
before reporting completion.** Applies to every type of work — compose and
service changes, alias and routing changes, documentation, troubleshooting. No
exceptions.

Steps, in order (each phase's detailed procedure is in the correspondingly-numbered
`rules/` file — already loaded into context, no need to open it):

1. **Understand** → [`rules/02-understand.md`](rules/02-understand.md)
2. **Plan** → [`rules/03-plan.md`](rules/03-plan.md) *(skip for trivial changes)*
3. **Implement** → [`rules/05-implement.md`](rules/05-implement.md)
4. **Test** → [`rules/06-testing.md`](rules/06-testing.md)
5. **Report** → [`rules/08-report.md`](rules/08-report.md)

Reference files: [`rules/01-project-config.md`](rules/01-project-config.md)
(services, ports, aliases), [`rules/09-code-quality.md`](rules/09-code-quality.md),
[`rules/10-tech-stack.md`](rules/10-tech-stack.md),
[`rules/11-communication.md`](rules/11-communication.md),
[`rules/12-security.md`](rules/12-security.md),
[`rules/machine-tools.md`](rules/machine-tools.md) (the `nvim-tools` and
`lukas-ps` CLIs — pre-approved, read-only),
[`rules/lsp.md`](rules/lsp.md) (the `LSP` tool — only in repos that opted in,
and deferred, so it must be loaded before it can be called).

**NEVER report completion without first bringing the stack up and getting a real
answer out of the alias you touched.** Editing `litellm/starter/lms.yaml` and
reporting success because the YAML parses is the failure this line exists to
prevent — a mistyped `api_base` parses perfectly and returns a connection error
on the first call. Verification is YOUR responsibility — the user should never
need to ask you to test.

**Trivial changes** (a typo in a comment, a wording fix in prose that changes no
command): skip step 2. State what you'll do and proceed.

## ai-gateway at a glance

- **Four containers, `podman compose` or `docker compose`** — `litellm` published
  on **`localhost:24000`** (admin UI at `/ui`), `postgres`, **not published**,
  holding virtual keys, spend logs and budget ceilings, `mlflow` published on
  **`localhost:25000`**, and `mlflow-seed`, a one-shot that exits.
  **BOTH GATEWAYS SIT BEHIND COMPOSE PROFILES** (`litellm`, `mlflow`, plus `all`
  on both), so `COMPOSE_PROFILES` in `.env` decides which runs. `postgres` carries
  no profile and always starts. **With no `.env` at all, `up -d` starts postgres
  and nothing else** — that is the configured behaviour, not a fault.
- **Two gateways, one vocabulary.** `mlflow` serves the SAME alias names through
  the MLflow AI Gateway, so the two can be compared without changing a caller's
  vocabulary. **LiteLLM stays primary** — it is what every project calls, and the
  only one with virtual keys, spend logs and budget ceilings. MLflow has no key
  at all.
- **Almost no application code.** The repo is `compose.yml` + LiteLLM YAML + docs
  + **eight Python files in `mlflow/`**. Those exist because MLflow has no config
  file to mount: its endpoints live in the database and arrive over an API, so
  MLflow's alias list IS Python. All three images are stock — there is no build
  step.
- **EACH GATEWAY OWNS ITS OWN ALIAS LIST, and nothing in `mlflow/` reads anything
  in `litellm/`** (changed 2026-08-28; before that the seed parsed LiteLLM's
  YAML). The point is that the `litellm` service and the whole `litellm/`
  directory can be deleted and the MLflow gateway still comes up and serves —
  verified 2026-08-28, the seed container mounts only `./mlflow`, and since
  2026-08-31 `COMPOSE_PROFILES=mlflow` does the same thing without deleting
  anything. **The price is that adding an alias is TWO edits, one per side.** Do
  only one and the name answers on 24000 and 404s on 25000, with nothing in either
  log to say why. Do not "fix" this by making the seed read the YAML again; the
  user asked for the independence deliberately.
- **`tests/` is the only other code, and the only manifest.** A `uv` project
  (Python 3.12, `openai` + `python-dotenv`) with three scripts — plain call,
  tools, multimodal — each run against **both** gateways through the real OpenAI
  client: `cd tests && uv sync && uv run run_all.py`. Default alias `lms-3b`,
  the smallest route that is both vision-capable and tool-trained.
- **Ports `24000` and `25000` are deliberate**, a 2xxxx band. The failure they
  avoid is not a bind error but the silent one: a health probe against
  `localhost:4000` that `mlflow-tutorial`'s or `ai-agent-platform`'s gateway
  answers, going green. `mlflow-tutorial` holds `5555` for its own MLflow.
- **Callers name aliases, never models, and EVERY alias names its engine.**
  `lms-*` is LMStudio, `unsloth-*` is Unsloth, `ollama-*` is Ollama. There is no
  engine-neutral name on purpose: an earlier `local` alias was renamed to
  `lms-26b` (2026-08-27) precisely because it hid which engine answered. Do not
  reintroduce one. `cheap-free` and `standard-hf` are fallback targets and **not**
  vocabulary; every `lms-*` / `unsloth-*` / `ollama-*` name *is* vocabulary.
- **THREE WORDS IN `.env` DECIDE WHAT RUNS**, and they are independent
  (2026-08-31; before that there was only the middle one, called
  `GATEWAY_PROFILE`).

  | Variable | Values | Default | Picks |
  |:--|:--|:--|:--|
  | `COMPOSE_PROFILES` | `litellm`, `mlflow`, `litellm,mlflow`, `all` | *(nothing starts)* | which gateway runs |
  | `GATEWAY_MODELS` | `starter`, `full` | `starter` | which alias list |
  | `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `all` | `all` | which engine |

  The last two name **one file per gateway**, and it is the same pair on both, so
  the gateways can never be on different lists — though they can still drift in
  *content*:

  | | LiteLLM (24000) | MLflow (25000) |
  |:--|:--|:--|
  | compose selects | `litellm/config.<models>.<engine>.yaml` | `mlflow/seed.py` + both words in its env |
  | the aliases are in | `litellm/<models>/<engine>.yaml` | `mlflow/<models>/<engine>.py` |

  - **starter** — one chat model (Gemma 4 E4B) and one embedder (nomic v1.5) per
    engine: 6 aliases with `all`, ~17 GB. What a fresh clone runs, small on purpose
    so nobody downloads 90 GB to try the repo.
  - **full** — 20 aliases with `all` (12 lms, 4 unsloth, 4 ollama), ~90 GB.
  - **A composed `config.<models>.<engine>.yaml` declares NOTHING.** It is an
    `include:` list — `litellm/settings.yaml` plus one to three engine fragments.
    Edit the fragment, never the composed file. **A composed file must never
    include another composed file**: LiteLLM does not recurse, so the nested
    `include` is merged as data and deleted, and the proxy boots with no master
    key.
  - **Which file to edit depends on the change.** A new model this machine runs
    goes in the **full** fragment for its engine. Only something that teaches the
    *pattern* belongs in the **starter** fragment, and anything added there must
    also exist in the full one, which is a strict superset. Either way it is **two
    files**, one per gateway.
  - `mlflow/gateway.py` is machinery and `mlflow/seed.py` is the CLI; neither holds
    a list. A fix in either reaches every engine file.
  - **The E4B row — `lms-4b` / `unsloth-4b` / `ollama-4b` — is the only chat model
    in both lists**, which is why `tests/` defaults to it and picks the one
    matching `GATEWAY_ENGINE`. Do not change that default to a full-only alias.
- **Everything is local and free today.** The cloud tiers `cheap`, `standard`,
  `frontier` and both fallback maps are **commented out** in
  `litellm/settings.yaml` (and again in `mlflow/seed.py`) — they belong to no
  engine, which is why they live beside the settings rather than in a fragment. So
  nothing here can currently accrue spend — but the local routes are still
  *shadow-priced*, so budget ceilings do trip.
- **Each engine serves BOTH chat and embeddings**: `lms-embed` / `lms-embed-hq`,
  `unsloth-embed`, `ollama-embed`. `lms-embed-hq` and `unsloth-embed` are the same
  nomic build on two engines; `ollama-embed` is a different model (all-MiniLM, 384
  dims, 512 window), so its vectors do not mix with either.
- **LMStudio runs natively on the host and must be hand-loaded.** A JIT load does
  not inherit the flags: a model loaded at 262144 context comes back at 8192 with
  a 1 h TTL. `lms ps --json` is the source of truth, not the UI.
- **Unsloth Studio is the SECOND local engine**, native on the host at
  `127.0.0.1:8888`, serving `unsloth-31b`, `unsloth-26b` and `unsloth-embed` — the
  same weights as `lms-31b` / `lms-26b` / `lms-embed-hq`, so the engines can be
  compared by changing only the alias. Three things differ from LMStudio: it
  **requires** `UNSLOTH_API_KEY` (every route 401s without it, `/v1/models`
  included), it serves **one model at a time** — a limit that spans chat and the
  embedder, so `unsloth-embed` evicts `unsloth-26b` and back — and it turns
  **reasoning on** for weights LMStudio runs without it, which is why both
  `unsloth-*` chat routes carry `max_tokens: 8192`. Its truth is
  `GET /v1/status`, and that needs the key.
- **Health**: `curl -fsS http://localhost:24000/health/liveliness` → `I'm alive!`
  It is the only unauthenticated route; `/health` needs the master key. First
  boot takes ~60 s for LiteLLM's schema migrations. MLflow's own probe is
  `curl -fsS http://localhost:25000/health` → `OK`, and `mlflow-seed` showing as
  **exited (0)** is its finished state, not a failure.
- **No secrets live here.** Provider keys arrive from `~/.secrets/secrets.enc.yaml`
  via `~/Projects/.envrc`, and compose's shell environment wins over `.env` — so
  those three lines in `.env` stay blank on purpose.

Full facts → [`rules/01-project-config.md`](rules/01-project-config.md); stack and
conventions → [`rules/10-tech-stack.md`](rules/10-tech-stack.md).

## Standing authorizations — do NOT ask before doing these

These actions are pre-approved. Run them yourself when the situation calls for it.

### Read-only inspection (always safe)

- `podman compose ps`, `podman compose config`, `podman compose logs [service]`
  — and the `docker compose` equivalents — **in this repo**.
- `curl` against `http://localhost:24000`: `/health/liveliness`, `/health`,
  `/key/info`, `/spend/logs`, `/model/info`, and completions through
  `/v1/chat/completions` or `/v1/messages`. Calling a **free** alias (`lms-26b`,
  `lms-embed`, `lms-uncensored`) to check something is always fine; a priced one costs
  money, so keep it to one short call.
- `curl` against `http://localhost:25000`: `/health`, `/version`, and completions
  through `/gateway/mlflow/v1/chat/completions` or
  `/gateway/openai/v1/embeddings`. The same rule applies — a **free** alias is
  always fine, a priced one costs money.
- `cd tests && uv sync && uv run run_all.py` — and any single script in there.
  Same rule as `curl`: a **free** alias is always fine, a priced one costs money.
- `lms ps --json`, `lms status` — reading what LMStudio currently has loaded.
- `podman compose exec postgres psql -U postgres -d litellm -c "SELECT ..."` —
  **`SELECT` only**. Anything that writes is a mutation and belongs below.
- `git status`, `git diff`, `git log`, and reading any file in this repo — with
  the sole exception of `.env`, which is denied in `settings.json` and stays
  denied.

This machine's own `nvim-tools` and `lukas-ps` are pre-approved too, and are
documented once in [`rules/machine-tools.md`](rules/machine-tools.md) — do not
restate them here.

### Pre-approved mutations

- Editing `compose.yml`, anything under `litellm/` or `mlflow/`,
  `postgres/init-databases.sh`, `README.md`, `LICENSE`, `.env.example` and
  anything under `.claude/` or `tests/` **in this repo**.
- Re-running the seed: `podman compose up -d`, or `mlflow/seed.py --reset`, which
  rebuilds every endpoint that run names. It creates nothing that costs money.
- Bringing the stack up on a different combination for a test —
  `COMPOSE_PROFILES=... GATEWAY_MODELS=... GATEWAY_ENGINE=... podman compose up -d`.
  **Put it back the way you found it before you report.**
- `podman compose up -d`, `podman compose restart litellm`, and
  `podman compose down` **without `-v`** — the stack is laptop-local and
  restarting it costs a minute, not data.
- Minting a **capped, expiring** virtual key — a `/key/generate` call that
  carries both `max_budget` and `duration`, with `max_budget` ≤ 2.00 and
  `duration` ≤ `7d`. That is the sanctioned pattern in `README.md`; an uncapped or
  non-expiring key is below.

### Requires confirmation — always ask first

- **`podman compose down -v`**, or anything else that removes the
  `postgres_data` volume. It destroys every virtual key, all spend history and
  every budget ceiling, and none of it can be recovered — the keys other projects
  hold stop working at that moment.
- **Removing or weakening the provider pin** (`order: ["google-ai-studio"]`,
  `allow_fallbacks: false`) in `litellm/settings.yaml`. It looks like dead
  configuration and is the only thing preventing raw-text tool calls that make
  agents silently do nothing.
- **Changing `LITELLM_MASTER_KEY`**, or minting a key with no `max_budget` or no
  `duration`. Both hand out spend against real provider accounts.
- **`lms load` / `lms unload`** on the host. It occupies the GPU and can evict a
  model another session is mid-request against — and several Claude Code sessions
  run on this machine at once.
- **Changing the published ports off `24000` / `25000`**, or publishing
  `postgres`. All three re-enter the collision this repo's port band exists to
  avoid — `5000` and `5555` are taken by `mlflow-tutorial`.
- **`mlflow/seed.py --prune`**, or dropping the `mlflow` database. `--prune`
  deletes every MLflow endpoint that run does not name — the other list's aliases,
  **the other ENGINES' aliases**, and any a person made by hand in the UI — and the
  `gateway/*` traces lose the endpoint they belong to. With a single engine named
  it is at its most destructive.
- **Changing `MLFLOW_CRYPTO_KEK_PASSPHRASE` on a stack that has already run.**
  Every stored provider credential was encrypted under the old value and stops
  decrypting — and it surfaces as an auth error at call time, not at startup.
- Setting the `lms-26b` alias's `*_cost_per_token` to `0`. It stops shadow-pricing
  and silently disables every budget ceiling for local traffic.
- `git push`, `git push --force`, branch deletes — **never commit unless the user
  explicitly asks**.
- Anything touching secrets, TLS material, tokens, or credential files. A secret
  never enters this repo in plaintext; if one must be versioned at all it is
  SOPS+age — [`rules/12-security.md`](rules/12-security.md).

When in doubt: ask. **Every project on this laptop calls this gateway** — a bad
edit here does not break one repo, it takes LLM access away from all of them at
once, and the two failure modes that cost the most (an uncapped key, a removed
provider pin) both look completely fine right up until the bill or the silently
empty agent run.
