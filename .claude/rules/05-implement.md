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
comments in `compose.yml` and the four alias lists are the reasoning — keep them
accurate rather than tidy.

## `compose.yml` — the four services

Belongs here: service definitions, profiles, published ports, healthchecks,
volumes, and the environment wiring that reaches the containers.

Two things about the mounts and profiles are load-bearing:

- **`./litellm` mounts at `/app/config`, not `/app/litellm`.** The image already
  ships `/app/litellm` — the proxy's own Python package — and mounting over it
  breaks the container. The whole directory is mounted, not one file, because a
  composed config includes its fragments by relative path.
- **Both gateways carry `profiles:`, `postgres` carries none.** That is what lets
  `COMPOSE_PROFILES` switch a gateway off, and it is also why an empty `.env`
  starts postgres alone. Do not "fix" that by removing the profiles.

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

## The TWELVE alias lists — two gateways x two lists x three engines

**This is the thing to get right, and it is the easy mistake.** Since 2026-08-28
each gateway owns its own list and neither reads the other; since 2026-08-31 each
list is split by engine as well:

| | LiteLLM (24000) | MLflow (25000) |
|:--|:--|:--|
| `starter` *(default)* | `litellm/starter/{lms,unsloth,ollama}.yaml` | `mlflow/starter/{lms,unsloth,ollama}.py` |
| `full` | `litellm/full/{lms,unsloth,ollama}.yaml` | `mlflow/full/{lms,unsloth,ollama}.py` |

**You still only ever edit TWO of those twelve** — the engine and list your change
belongs to, once per gateway. The split multiplies files, not edits.

Three words in `.env` pick what runs: `COMPOSE_PROFILES` (which gateway),
`GATEWAY_MODELS` (which list) and `GATEWAY_ENGINE` (which engine). The last two go
into a filename on the LiteLLM side and into `seed.py`'s environment on the MLflow
side — so the two gateways can never be on different lists, but they absolutely
can drift in *content*.

| Change | Goes in |
|:--|:--|
| a model this machine runs | the **full** row — **one engine cell per gateway**, so two files |
| something that teaches the pattern to a newcomer | that engine's **starter and full** cells on **both** gateways — starter is a strict subset of full |
| a LiteLLM settings block (`router_settings`, `general_settings`, …) | `litellm/settings.yaml` — once; every composed config includes it |
| a hosted/cloud route, which belongs to no engine | `litellm/settings.yaml` and `mlflow/seed.py`, where the commented tiers already live |
| a fix to the MLflow seeding logic | `mlflow/gateway.py` — every engine file gets it |
| a fix to how a list or engine is chosen | `mlflow/seed.py` on one side, the composed `config.*.yaml` names on the other |

**An alias is never one edit.** Add it on one side only and the name answers on
24000 and 404s on 25000, with nothing in either log to say why. After any alias
change, call it on **both** ports — `rules/06-testing.md`.

**Never edit a composed `config.<models>.<engine>.yaml`.** It is an `include:`
list and nothing else: `settings.yaml` plus one to three fragments. The eight of
them exist so compose can name one file; the aliases live in the fragments. And a
composed file must **never** include another composed file — LiteLLM does not
recurse, so the nested `include` is merged as data and then deleted, leaving a
proxy with no `general_settings` and therefore no master key.

The starter list is the six-alias default a fresh clone gets, and it is small on
purpose: nobody should download ~90 GB to try the repo. Never add a model to it
that is not also in the full list, and never let it grow past demonstrating one
chat model and one embedder per engine — that shape *is* the lesson.

## `litellm/` — gateway 1

Three kinds of file, and the difference matters:

| File | Holds |
|:--|:--|
| `settings.yaml` | the three settings blocks, the commented fallback maps, the commented hosted tiers, and the notes true of every alias (timeouts, shadow pricing, reasoning tokens) |
| `<models>/<engine>.yaml` | `model_list` and nothing else — the aliases, their prices and their windows |
| `config.<models>.<engine>.yaml` | an `include:` list and nothing else. Eight of them. **Never edit one to add an alias** |

Belongs in a fragment: `model_list` entries, per-alias pricing, fallback chains,
provider pins. Every number gets a comment saying where it came from. **MLflow has
no place for prices, `max_tokens`, context windows or per-route timeouts**, so
those live here and only here.

- **Do not remove the provider pin.** `order: ["google-ai-studio"]` +
  `allow_fallbacks: false` exists because OpenRouter load-balances its free tier
  and one provider returns tool calls as raw text
  (`<|tool_call>call:write_todos{...}`) with `tool_calls` absent. Nothing errors:
  the agent sees an assistant message with no tool calls, executes nothing, and
  stops. Removing the pin to "simplify" reintroduces exactly that.
- **Adding an alias is a five-part edit**: the `model_list` entry in that engine's
  fragment, its price (or a deliberate note that it is in LiteLLM's own cost map),
  its fallback chain (or a stated reason it has none), **the matching
  `Endpoint(...)` in `mlflow/<models>/<engine>.py`**, and the alias table in
  `README.md`. An alias that exists in the config and not in the README is an
  alias nobody will call; one that exists here and not in `mlflow/` is an alias
  that 404s on 25000. It is still two files, because the engine and the list
  already pick which two.
- **The alias name must carry its engine** — `lms-*`, `unsloth-*`, `ollama-*`.
  There is no engine-neutral name and there must not be one; a `local` alias
  existed until 2026-08-27 and was renamed because it hid which engine answered.
- **`success_callback` is empty on purpose.** A trace store is a *project's*
  system of record, not the machine's — two projects sharing one experiment
  namespace makes "did this get better" ambiguous. A project that wants tracing
  runs its own MLflow and traces client-side.

## `mlflow/` — gateway 2, and the only code in this repo

Eight files. They exist because MLflow's gateway has no config file: its endpoints
live in the `mlflow` database and arrive over an API, so MLflow's alias list has
to BE Python.

| File | Is |
|:--|:--|
| `gateway.py` | the machinery: `Endpoint`, `env()`, the secret / definition / endpoint calls. **No alias list and no CLI.** |
| `seed.py` | the CLI: reads `GATEWAY_MODELS` / `GATEWAY_ENGINE`, validates both words by name, imports the engine files and calls `seed()`. **No alias list either.** |
| `<models>/<engine>.py` | six files, each `ENDPOINTS = [...]` and nothing else |

- **The two words are validated by hand, not with argparse `choices`.** A default
  that came from the environment is never checked against `choices`, and the
  environment is exactly where the typo comes from. Keep the explicit check, or a
  misspelling becomes a `ModuleNotFoundError` naming a file nobody meant to write.

- **It must NOT read anything in `litellm/`.** That coupling existed until
  2026-08-28 and was removed on purpose: the user wants to be able to delete
  LiteLLM from this repo with MLflow still working. Re-introducing a YAML parse
  here to "stop the drift" undoes the change that was asked for. The drift is a
  known, documented cost — see the two headers and `README.md`.
- **The six engine files stay symmetric and list-first.** A reader opens any one
  and sees endpoints with the reasoning beside them. Machinery belongs in
  `gateway.py`, selection in `seed.py`; do not let one engine file grow logic the
  others lack.
- **`check_secrets` fails fast on purpose.** One `secret` name must mean one
  `api_base` + `api_key` pair. Two endpoints disagreeing under one name would
  store whichever was written last, and the other alias would 401 with nothing in
  the log to explain it.
- **`fallback_config` is what activates a fallback chain.** A `FALLBACK` linkage
  is stored, and shown in the UI, whether or not it is passed; the gateway only
  wraps the primary in a fallback provider when the config object is there.
  Removing it leaves a chain that looks right everywhere except in production.
- **It stays idempotent.** compose runs it on every `up -d`, so a second run must
  reuse, not duplicate. Secrets are the deliberate exception — they are rewritten
  each run, which is how a rotated provider key reaches the gateway.
- **`--prune` got sharper teeth.** It deletes every endpoint the run does not
  name, which now includes the other ENGINES' aliases. Never reach for it to tidy
  up after an engine switch without saying so first.
- **A LiteLLM feature with no MLflow equivalent is documented, not faked.** The
  list is in `README.md` § The MLflow gateway. Adding a shim that half-implements
  one is worse than the missing feature, because it reads as working.

## `tests/` — the three call kinds, on both gateways

Belongs here: one script per KIND of call, never per alias. `--model` already
covers "the same test against a different alias", so a `04_local_qwen.py` would
be a copy of an existing file with one string changed.

- **A scenario never names a gateway.** It takes one and calls it. The whole
  point is that the OpenAI client, the alias and the message body are identical
  on 24000 and 25000 — a scenario that branches on `gateway.name` has stopped
  testing that.
- **`02_tools_call.py` checks `finish_reason` and the `tool_calls` structure**,
  not the words in the reply. A model that emits raw-text tool syntax returns a
  perfectly good-looking assistant message, and that is the failure the file
  exists to catch.
- **Its tools return fixed numbers.** A test that calls a market API cannot tell
  "the gateway is broken" from "the market is closed".
- `run_all.py` globs `NN_*.py`, so a new script needs no edit there. Keep the
  numbered prefix.

## `README.md`

**The one document, and it is written for the public.** This repo is shared with
the community, so `README.md` is a stranger's front door, not a lab notebook:
what the gateway is, how to start it, the alias table, how to call it, how to run
`tests/`, driving it from Claude Code, configuration, and one troubleshooting
table. The old `NOTES.md` was merged into it — do not recreate a second doc.

Two rules when you edit it:

- **Keep it slim.** It is ~630 lines and that is already at the limit — the two-gateway
  split added a section and a column to several tables. A new fact replaces a vaguer
  one; it does not get appended. Deep per-alias measurement belongs in the
  comments of `litellm/full/<engine>.yaml`, which is where a maintainer looks anyway.
- **A stranger has to be able to read it.** No absolute home paths, no reference
  to another repo on this machine, and no claim that is true only of this laptop
  without saying so.

It carries **verified-on** dates against specific claims (tool calling through
`lms-26b`, for instance). If you re-verify one, move the date. If you change what
it describes without re-testing, delete the claim rather than leaving a date that
now vouches for something untested.

## Repository structure

```text
ai-gateway/
├── .claude/            this contract
├── .env.example        tracked; the three provider keys are blank BY DESIGN
├── .gitignore
├── compose.yml         four services, profiles, ports, healthchecks
├── litellm/            GATEWAY 1's alias list — YAML
│   ├── settings.yaml       the 3 settings blocks + the commented hosted tiers
│   ├── starter/            lms.yaml unsloth.yaml ollama.yaml — 2 aliases each
│   ├── full/               lms.yaml unsloth.yaml ollama.yaml — 12 / 4 / 4
│   └── config.<models>.<engine>.yaml   8 include-only files; compose loads one
├── mlflow/             GATEWAY 2's alias list — Python; reads nothing in litellm/
│   ├── gateway.py          the MLflow API machinery
│   ├── seed.py             the CLI: picks a list and an engine, validates both
│   ├── starter/            lms.py unsloth.py ollama.py — 2 endpoints each
│   └── full/               lms.py unsloth.py ollama.py — 12 / 4 / 4
├── postgres/
│   └── init-databases.sh   CREATE DATABASE mlflow, on a fresh volume only
├── tests/              a uv project: three call kinds x both gateways
│   ├── common.py           the two base URLs, the client, the pass/fail printing
│   ├── 01_simple_call.py   plain chat completion
│   ├── 02_tools_call.py    tools, and the second turn that uses the result
│   ├── 03_multimodal.py    an image plus a question
│   └── run_all.py          every NN_*.py x every gateway, as a table
├── LICENSE             MIT
└── README.md           the ONE doc — aliases, quick start, tests, Claude Code
```
