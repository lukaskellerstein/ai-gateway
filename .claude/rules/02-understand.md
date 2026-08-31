# Step 1: Understand

- Read the relevant config and identify what the change touches.
- Baseline the repo's existing findings with `nvim-tools --json --all`, so findings you
  introduce stay distinguishable from ones already there
  ([`machine-tools.md`](machine-tools.md)). Expect every tool `gated-off` — this repo
  carries no marker files.
- Ask if the requirement is ambiguous. Understand it fully before changing anything.
- `grep` is the tool here. No `lsp-*` plugin is enabled for this repo, so the `LSP` tool
  will not be in your list ([`lsp.md`](lsp.md)).

## Reproduce a bug against a running gateway first

```bash
podman compose ps                                     # is it even up, and which services?
curl -fsS http://localhost:24000/health/readiness     # -> {"status":"healthy","db":"connected"}
curl -fsS -H "Authorization: Bearer ${AI_GATEWAY_KEY:-sk-litellm-master}" \
  http://localhost:24000/model/info                   # which aliases are registered
podman compose logs --tail=100 litellm
```

Every request also lands in the admin UI's Logs tab at <http://localhost:24000/ui>, prompt
and response included. **Look there before changing configuration.**

## Rule these out before blaming the repo

1. **`.env` is asking for something else.** `COMPOSE_PROFILES` decides which gateway runs,
   `GATEWAY_ENGINE` which engine. A refused port, or an alias that 404s on both gateways,
   is usually one of those two words. `compose ps` and `/model/info` say which. **`.env` is
   denied to you — ask the user what is in it.**
2. **You are calling another engine's alias.** One engine is served at a time; every other
   name is absent from the config. A 404 is correct.
3. **The model is not loaded.** LMStudio JIT-loads at 8192 context with a 1 h TTL
   (`lms ps --json`); Unsloth returns `400 No model loaded` unless auto-switch is on;
   Ollama evicts after 5 minutes idle (`ollama ps`).
4. **A provider key is missing from the shell.** `UNSLOTH_API_KEY`, `OPENROUTER_API_KEY`
   and `OPENAI_API_KEY` are blank in `.env` **on purpose** and arrive from
   `~/Projects/.envrc`. Compose reads the shell first, so an auth failure usually means the
   shell that ran `up -d` had no direnv.
