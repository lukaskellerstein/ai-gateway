# Step 1: Understand

- Read the relevant config and identify what the change touches. **Identify which of the
  three projects it belongs to first** — `litellm/`, `mlflow/` and `envoy/` are independent
  compose projects and a change is almost always to one of them, not several.
- Baseline the repo's existing findings with `nvim-tools --json --all`, so findings you
  introduce stay distinguishable from ones already there
  ([`machine-tools.md`](machine-tools.md)). Expect every tool `gated-off` — this repo
  carries no marker files.
- Ask if the requirement is ambiguous. Understand it fully before changing anything.
- `grep` is the tool here. No `lsp-*` plugin is enabled for this repo, so the `LSP` tool
  will not be in your list ([`lsp.md`](lsp.md)).

## Record the starting state before you touch anything

There is no root `compose.yml`, so "is the stack up" is now three questions. Answer all of
them, and write the answers down — you have to restore them.

```bash
podman ps --format '{{.Names}}  {{.Status}}'      # which projects are running at all
cd litellm && podman compose ps                   # and the same in mlflow/ and envoy/
```

Container names say which project: `ai-gateway-*` is LiteLLM, `ai-gateway-mlflow-*` is
MLflow, `ai-gateway-envoy-*` is Envoy. **Each project also has its own `GATEWAY_ENGINE`**,
and they can differ — ask the user for all three, because you cannot read any `.env`.

## Reproduce a bug against a running gateway first

```bash
curl -fsS http://localhost:24000/health/readiness     # -> {"status":"healthy","db":"connected"}
curl -fsS http://localhost:25000/health               # -> OK
curl -fsS http://localhost:26000/v1/models            # Envoy: the DATA plane, not 26064
curl -fsS -H "Authorization: Bearer ${AI_GATEWAY_KEY:-sk-litellm-master}" \
  http://localhost:24000/model/info                   # which aliases are registered
cd litellm && podman compose logs --tail=100 litellm
```

Every request also lands in the admin UI's Logs tab at <http://localhost:24000/ui>, prompt
and response included. **Look there before changing configuration.** MLflow has no such
view — its equivalent is `podman compose logs mlflow-seed`, which says what was built.
Envoy's is `compose logs envoy`, **but only with `AIGW_DEBUG=true`**: with it false there is
no per-request output at all, because Envoy's stdout goes to a file inside a distroless
container.

> **Do not run a bare `podman compose config` while investigating.** It interpolates from
> the shell and prints the real provider keys. Use `--services`.

## Rule these out before blaming the repo

1. **That gateway is not running.** They start and stop independently now. `podman ps`
   says which. A refused port is usually this — and on Envoy it can also be the startup
   race: 26064 answers `OK` seconds before 26000 accepts a connection.
2. **The projects are on different engines.** Each folder has its own `.env` and its own
   `GATEWAY_ENGINE`, and nothing checks that they agree — so an alias answering on one port
   and 404ing on another is as likely to be two different engine words as a missing route.
   **Every `.env` is denied to you — ask the user what is in them.**
3. **You are calling another engine's alias.** One engine is served at a time per project;
   every other name is absent from the config. A 404 is correct.
4. **The alias was added on one side only.** `litellm/config/<engine>.yaml`,
   `mlflow/config/<engine>.py` and `envoy/config/<engine>.yaml` are maintained separately
   and no test compares them.
5. **The model is not loaded.** LMStudio JIT-loads at 8192 context with a 1 h TTL
   (`lms ps --json`); Unsloth returns `400 No model loaded` unless auto-switch is on, and
   holds one model at a time — **more than one gateway on `unsloth` thrashes it**; Ollama evicts
   after 5 minutes idle (`ollama ps`).
6. **A provider key is missing from the shell.** `UNSLOTH_API_KEY`, `OPENROUTER_API_KEY`
   and `OPENAI_API_KEY` are blank in every `.env` **on purpose** and arrive from
   `~/Projects/.envrc`. Compose reads the shell first, so an auth failure usually means the
   shell that ran `up -d` had no direnv.
