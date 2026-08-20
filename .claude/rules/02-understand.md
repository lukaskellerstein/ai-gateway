---
description: "Step 1: Understand — read code, ask questions, identify gaps before any implementation"
---

# Step 1: Understand

- Read relevant code and identify impacted areas
- Baseline the repo's existing problems with `nvim-tools --json --all`, so
  findings you introduce stay distinguishable from ones that were already there.
  For performance or RAM questions, `lukas-ps --json [name]` measures the real
  process tree. Both: [`machine-tools.md`](machine-tools.md).
- **If `LSP` is in your tool list, load it and use it** for every question about
  a symbol — where defined, who implements, who calls. It is deferred, so
  `ToolSearch("select:LSP")` comes first or it cannot be called at all. Absent
  from the list means this repo did not opt in: use `grep`.
  [`lsp.md`](lsp.md). This repo contains no Python, TypeScript or Go, so no
  `lsp-*` plugin is enabled and `LSP` will not be there.
- Ask clarifying questions if requirements are ambiguous
- Identify gaps in the current design and opportunities for improvement
- Understand the requirement completely before proceeding
- **For bug reports**: reproduce the issue first to confirm the problem before
  attempting a fix. Here that means reproducing it *against a running gateway*:

  ```bash
  podman compose ps                                        # is it even up?
  curl -fsS http://localhost:24000/health/liveliness        # -> "I'm alive!"
  podman compose logs --tail=100 litellm
  curl -sX POST http://localhost:24000/v1/chat/completions \
    -H "Authorization: Bearer ${AI_GATEWAY_KEY:-sk-litellm-master}" \
    -H 'Content-Type: application/json' \
    -d '{"model":"local","messages":[{"role":"user","content":"hi"}]}'
  ```

  Every request also lands in the admin UI's Logs tab at
  <http://localhost:24000/ui>, prompt and response included
  (`store_prompts_in_spend_logs`). **Look there before changing configuration.**

## Before blaming this repo

Three things outside `compose.yml` and `litellm/config.yaml` cause most of what
looks like a gateway bug. Rule each out first:

1. **LMStudio was JIT-loaded.** A JIT load does not inherit hand-load flags — a
   model hand-loaded at 262144 context comes back at 8192, with a 1 h TTL. A
   session that worked this morning fails this afternoon with nothing changed.
   `lms ps --json` is the source of truth, **not** the LMStudio UI.
2. **The alias fell back.** `local` routes to OpenRouter when LMStudio is down.
   Non-zero spend on a "free" alias is this, and it is expected behaviour.
3. **A provider key is missing from the shell.** `OPENROUTER_API_KEY`,
   `OPENAI_API_KEY` and `HF_TOKEN` are blank in `.env` **on purpose** and arrive
   from `~/Projects/.envrc`. Compose's shell environment wins over `.env`, so a
   priced alias failing with an auth error usually means the shell that ran
   `up -d` had no direnv, not that the config is wrong.
