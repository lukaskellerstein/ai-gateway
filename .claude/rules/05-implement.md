---
description: "Step 3: Implement — coding rules and this project's layout"
---

# Step 3: Implement

Write clean code from the start. Follow these rules during implementation:

- Do NOT commit via `git` unless explicitly instructed by the user
- When creating diagrams or graphs, use `mermaid`
- Write clean code from the start — don't plan to "clean it up later"
- Refactor continuously — improve code structure immediately when you see issues
- Remove dead code — delete unused functions, variables, imports, and commented code
- Before changing any signature, renaming, or deleting something shared, find
  every caller with `findReferences` where the `LSP` tool is available — grep
  misses the ones spelled differently and finds ones that are not calls.
  [`lsp.md`](lsp.md)
- After writing code: review comments, clean up imports, check for side effects

This repo has **no application code**, so the rules above mostly bind the day one
appears. What they translate to here: a config change is still a change, and the
comments in `compose.yml` and `litellm/config.yaml` are the reasoning — keep them
accurate rather than tidy.

## `compose.yml` — the two services

Belongs here: service definitions, published ports, healthchecks, volumes, and
the environment wiring that reaches the containers.

Must **not** appear here: a credential value. `LITELLM_MASTER_KEY` is
`${LITELLM_MASTER_KEY:-sk-litellm-master}` and the three provider keys are
`${..:-}` — the defaults exist so `up -d` works with no `.env`, and the real
values arrive from the shell.

Two things in this file are load-bearing and easy to "simplify" wrongly:

- **`DATABASE_URL` is required, not optional.** Without it the proxy boots in
  no-DB mode: completions keep working while `/key/generate` fails with
  `{"error":"No connected db."}`. That is the worst possible failure for a budget
  guardrail — callers proceed uncapped and nothing looks broken.
- **The `start_period: 60s` on the healthcheck** covers LiteLLM's first-boot
  schema migrations against an empty database. Shorten it and a cold `up -d`
  reports unhealthy while it is working correctly.

## `litellm/config.yaml` — the aliases

Belongs here: `model_list` entries, per-alias pricing, fallback chains, provider
pins, and the router/general settings. Every number gets a comment saying where
it came from.

- **Do not remove the provider pin.** `order: ["google-ai-studio"]` +
  `allow_fallbacks: false` exists because OpenRouter load-balances its free tier
  and one provider returns tool calls as raw text
  (`<|tool_call>call:write_todos{...}`) with `tool_calls` absent. Nothing errors:
  the agent sees an assistant message with no tool calls, executes nothing, and
  stops. Removing the pin to "simplify" reintroduces exactly that.
- **Adding an alias is a four-part edit**: the `model_list` entry, its price (or
  a deliberate note that it is in LiteLLM's own cost map), its fallback chain (or
  a stated reason it has none), and the alias table in `README.md`. A tier that
  exists in the config and not in the README is a tier nobody will call.
- **`success_callback` is empty on purpose.** A trace store is a *project's*
  system of record, not the machine's — two projects sharing one experiment
  namespace makes "did this get better" ambiguous. A project that wants tracing
  runs its own MLflow and traces client-side.

## `README.md` and `NOTES.md`

`README.md` is the front door: aliases, ports, starting it, minting a capped key.
`NOTES.md` is one topic — driving this gateway *from Claude Code*, including the
`ANTHROPIC_*` variables, the three configurations and the troubleshooting table.
Keep that split; a Claude Code detail added to `README.md` is a detail nobody
maintaining the gateway needs.

Both carry **verified-on** dates against specific claims (tool calling through
`local`, for instance). If you re-verify one, move the date. If you change what
it describes without re-testing, delete the claim rather than leaving a date that
now vouches for something untested.

## Repository structure

```text
ai-gateway/
├── .claude/            this contract
├── .env.example        tracked; the three provider keys are blank BY DESIGN
├── .gitignore
├── compose.yml         two services, ports, healthchecks
├── litellm/
│   └── config.yaml     aliases, prices, fallback chains, provider pins
├── NOTES.md            connecting Claude Code to this gateway
└── README.md           start here — aliases, keys, ports
```
