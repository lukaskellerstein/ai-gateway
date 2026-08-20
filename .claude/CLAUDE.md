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
answer out of the alias you touched.** Editing `litellm/config.yaml` and
reporting success because the YAML parses is the failure this line exists to
prevent — a mistyped `api_base` parses perfectly and returns a connection error
on the first call. Verification is YOUR responsibility — the user should never
need to ask you to test.

**Trivial changes** (a typo in a comment, a wording fix in prose that changes no
command): skip step 2. State what you'll do and proceed.

## ai-gateway at a glance

- **Two containers, `podman compose` or `docker compose`** — `litellm` published
  on **`localhost:24000`** (admin UI at `/ui`) and `postgres`, **not published**,
  holding virtual keys, spend logs and budget ceilings.
- **No application code.** The entire repo is `compose.yml` +
  `litellm/config.yaml` + docs. Every change is a config change, and both images
  are stock — there is no build step.
- **Port `24000` is deliberate**, a 2xxxx band. The failure it avoids is not a
  bind error but the silent one: a health probe against `localhost:4000` that
  `mlflow-tutorial`'s or `ai-agent-platform`'s gateway answers, going green.
- **Callers name aliases, never models.** `local` / `cheap` / `standard` /
  `frontier` are tiers; `embed` / `uncensored` are roles. `cheap-free` and
  `standard-hf` are fallback targets and **not** part of that vocabulary.
- **`local` is not guaranteed to stay local** — it falls back to OpenRouter when
  LMStudio is down, so a "free" session can accrue real spend. It is also
  *shadow-priced*, so budget ceilings still apply to it.
- **LMStudio runs natively on the host and must be hand-loaded.** A JIT load does
  not inherit the flags: a model loaded at 262144 context comes back at 8192 with
  a 1 h TTL. `lms ps --json` is the source of truth, not the UI.
- **Health**: `curl -fsS http://localhost:24000/health/liveliness` → `I'm alive!`
  It is the only unauthenticated route; `/health` needs the master key. First
  boot takes ~60 s for LiteLLM's schema migrations.
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
  `/v1/chat/completions` or `/v1/messages`. Calling a **free** alias (`local`,
  `embed`, `uncensored`) to check something is always fine; a priced one costs
  money, so keep it to one short call.
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

- Editing `compose.yml`, `litellm/config.yaml`, `README.md`, `NOTES.md`,
  `.env.example` and anything under `.claude/` **in this repo**.
- `podman compose up -d`, `podman compose restart litellm`, and
  `podman compose down` **without `-v`** — the stack is laptop-local and
  restarting it costs a minute, not data.
- Minting a **capped, expiring** virtual key — a `/key/generate` call that
  carries both `max_budget` and `duration`, with `max_budget` ≤ 2.00 and
  `duration` ≤ `7d`. That is the sanctioned pattern in `NOTES.md`; an uncapped or
  non-expiring key is below.

### Requires confirmation — always ask first

- **`podman compose down -v`**, or anything else that removes the
  `postgres_data` volume. It destroys every virtual key, all spend history and
  every budget ceiling, and none of it can be recovered — the keys other projects
  hold stop working at that moment.
- **Removing or weakening the provider pin** (`order: ["google-ai-studio"]`,
  `allow_fallbacks: false`) in `litellm/config.yaml`. It looks like dead
  configuration and is the only thing preventing raw-text tool calls that make
  agents silently do nothing.
- **Changing `LITELLM_MASTER_KEY`**, or minting a key with no `max_budget` or no
  `duration`. Both hand out spend against real provider accounts.
- **`lms load` / `lms unload`** on the host. It occupies the GPU and can evict a
  model another session is mid-request against — and several Claude Code sessions
  run on this machine at once.
- **Changing the published port off `24000`**, or publishing `postgres`. Both
  re-enter the collision this repo's port band exists to avoid.
- Setting the `local` alias's `*_cost_per_token` to `0`. It stops shadow-pricing
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
