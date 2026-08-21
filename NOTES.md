# Connecting Claude Code to this gateway

Claude Code speaks the **Anthropic Messages API** and nothing else. LiteLLM exposes
`/v1/messages` alongside the OpenAI routes and translates it to whatever the alias points
at, so `local` (LMStudio, on this laptop) and `standard` (OpenRouter) both become things
Claude Code can drive. That translation is the entire trick — point `ANTHROPIC_BASE_URL`
at the proxy and Claude Code never learns it is not talking to Anthropic.

Conventions here follow
`~/Projects/Github/lukaskellerstein/vibe-coding-course/4_Claude_Code/10_custom_models/NOTES.md`.
What changes for this gateway: **port 24000**, and the model names are this repo's
aliases (`local`, `cheap`, `standard`, `frontier`) rather than raw model ids.

## The variables

| Variable | Value | Why |
|:--|:--|:--|
| `ANTHROPIC_BASE_URL` | `http://localhost:24000` | **No `/v1` suffix** — Claude Code appends `/v1/messages` itself. With `/v1` you get 404s on `/v1/v1/messages` |
| `ANTHROPIC_AUTH_TOKEN` | a gateway key | sent as `Authorization: Bearer` — the header LiteLLM actually reads |
| `ANTHROPIC_API_KEY` | the same value | sent as `x-api-key`. Set both; which one is used has moved between versions |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | an alias | what `/model sonnet` resolves to |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | an alias | what `/model opus` resolves to |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | an alias | background work — titles, summaries, file suggestions |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | `1` | beta headers a non-Anthropic backend does not implement |
| `CLAUDE_CODE_ATTRIBUTION_HEADER` | `0` | drops the attribution header |
| `API_TIMEOUT_MS` | `3600000` all-local, `600000` mixed | how long Claude Code waits before hanging up. The default expires while a local model is still reading the prompt — § *A local model is slow*. **One global value**, so a mixed config gives cloud calls the same patience |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `253952` all-local, `245760` mixed | the alias's real input window. Without it Claude Code assumes **200000** for every alias here and both the status line and auto-compact are wrong — § *The context window Claude Code assumes*. **One global value** like the timeout, so set it to the window of the alias the main loop runs on and prefer the smaller number in a mixed config |

**Set all three model variables, every time.** Leave one unset and Claude Code sends the
real Claude model id for that slot — the gateway has no such alias and answers
`Invalid model name passed in model=claude-...`, which looks like a broken proxy and is
just an unmapped slot.

## The context window Claude Code assumes

Claude Code carries a table of Anthropic model ids and their windows. An alias is not in
it, so it falls back to **200000** and the status line reports `82k/200k` for a model whose
real window is 253952 — the same number auto-compact fires against, so a quarter of the
window this gateway paid a GPU for goes unused.

`CLAUDE_CODE_MAX_CONTEXT_TOKENS` replaces that assumption. It is honoured **only for model
ids that do not start with `claude-`**, which every alias here satisfies — set it in a
first-party session and it is silently ignored, so it is safe to leave in a shell profile.

The value is the alias's `max_input_tokens` from `litellm/config.yaml`, not its context
length: the window minus the output reserve, `262144 - 8192 = 253952` for the two LMStudio
routes. `GET /model/info` is the authority if the config has moved on.

> [!warning]
> **Never pick the `[1m]` variant in `/model`.** It appends `[1m]` to the alias — the
> status line then reads `local[1m]` and claims a **1.0M** window. That number is
> fabricated: Claude Code tests the name for `[1m]` before it consults anything else and
> returns 1000000 unconditionally, so `CLAUDE_CODE_MAX_CONTEXT_TOKENS` is never read and
> auto-compact will not fire until four times what the gateway can accept. LiteLLM's
> `enable_pre_call_checks` catches the overflow and `context_window_fallbacks` routes it to
> `frontier` — so an "offline" session becomes a paid OpenAI one, the same failure the
> `local` callout below describes, reached a different way. Pick the plain alias and the
> status line reads `254.0k`, which is the truth.

## Get a key first

Do **not** hand Claude Code the master key. It mints other keys and has no spending
ceiling of its own, and a coding agent in a loop against `standard` or `frontier` is
exactly the workload a ceiling exists for. Mint a capped, expiring one:

```bash
curl -sX POST http://localhost:24000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"models":["local","cheap","standard"],"max_budget":2.00,"duration":"7d"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])'
```

Keep the result in your shell (`export AI_GATEWAY_KEY=sk-...`), not in a tracked file.
Every example below reads `$AI_GATEWAY_KEY`.

Check it reaches a model before starting a session — this is the exact call Claude Code
makes, so if it fails, Claude Code will too:

```bash
curl -sX POST http://localhost:24000/v1/messages \
  -H "Authorization: Bearer $AI_GATEWAY_KEY" \
  -H 'anthropic-version: 2023-06-01' \
  -H 'Content-Type: application/json' \
  -d '{"model":"local","max_tokens":64,"messages":[{"role":"user","content":"say hi"}]}'
```

It proves routing, auth and the alias — nothing about speed. A two-token prompt returns in
about a second from a local model that will still take minutes on a real agent turn, so
**this passing does not predict a session working**. When it passes and Claude Code still
fails, the timeout section below is the place to look, not this call.

## Three ways to apply it

**A) Settings file** — `.claude/settings.json` in the project, `env` block. Persistent,
applies to every `claude` session started in that project.

**B) Command line** — variables inline, right before `claude`. Nothing is persisted; only
that session is affected. Good for A/B-ing two models in two terminals.

**C) `--settings` flag** — the same JSON as the file, passed inline:

```bash
claude --settings '{"env":{"ANTHROPIC_BASE_URL":"http://localhost:24000"}}'
```

### Gotchas

- **The settings file wins.** If `.claude/settings.json` has an `env` block, its values
  override what you set on the command line. Delete or rename that block when you want
  form B to take effect — otherwise the prefix variables are silently ignored.
- The prefix form applies to one command only, and works in `bash` and `zsh`. Empty
  values (`ANTHROPIC_API_KEY=""`) are fine.
- **Never commit the key into `.claude/settings.json`.** That file is normally tracked, and
  a gateway key in git is a spendable credential in git — it authorises calls to
  OpenRouter and OpenAI through this proxy. Use form B, or a settings file that is
  gitignored.

## Configurations

### Mixed — the one to start with

Cheap models where quality does not matter, a real one where it does. **`haiku` is the
lever most people miss**: Claude Code calls it constantly for conversation titles,
summaries and suggestions, and none of that needs a paid model. Pointing it at `local`
takes that traffic off the network entirely.

```json
"env": {
  "ANTHROPIC_BASE_URL": "http://localhost:24000",
  "ANTHROPIC_API_KEY": "sk-REPLACE-ME",
  "ANTHROPIC_AUTH_TOKEN": "sk-REPLACE-ME",
  "ANTHROPIC_DEFAULT_SONNET_MODEL": "standard",
  "ANTHROPIC_DEFAULT_OPUS_MODEL": "frontier",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL": "local",
  "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
  "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
  "API_TIMEOUT_MS": "600000",
  "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "245760"
}
```

```bash
ANTHROPIC_BASE_URL="http://localhost:24000" \
ANTHROPIC_API_KEY="$AI_GATEWAY_KEY" \
ANTHROPIC_AUTH_TOKEN="$AI_GATEWAY_KEY" \
ANTHROPIC_DEFAULT_SONNET_MODEL="standard" \
ANTHROPIC_DEFAULT_OPUS_MODEL="frontier" \
ANTHROPIC_DEFAULT_HAIKU_MODEL="local" \
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 \
CLAUDE_CODE_ATTRIBUTION_HEADER=0 \
API_TIMEOUT_MS=600000 \
CLAUDE_CODE_MAX_CONTEXT_TOKENS=245760 \
claude
```

`CLAUDE_CODE_MAX_CONTEXT_TOKENS` is `standard`'s window, not `frontier`'s, for the same
reason the timeout is 10 minutes: one global value, and the sonnet slot is what the main
loop runs on here. Switching to `/model opus` mid-session therefore undercounts
`frontier` — the safe direction, since it compacts early rather than overflowing.

`API_TIMEOUT_MS` is 10 minutes here, not the 60 minutes of an all-local config. Only the `haiku`
slot is local in this layout, and background calls carry small prompts — the multi-minute
waits belong to agent-scale turns, which here go to OpenRouter and OpenAI. Since the
variable is global, a longer value would also be how long you wait on a wedged cloud call.

### `local` — LMStudio, offline, free

`google/gemma-4-26b-a4b` on the host GPU. Free, private, and the 262144-token window is
the largest of any local model here — 253952 of it input, once the 8192-token output
reserve is taken off, which is the number `CLAUDE_CODE_MAX_CONTEXT_TOKENS` wants. That
matters more for Claude Code than for anything else, because its system prompt plus tool
schemas cost tens of thousands of tokens before you type a word. That was the pain point in the earlier course notes
("main painpoint is limited context size"); a 26B MoE at full context removes it.

**Tool calling verified working, 2026-08-20.** A `/v1/messages` request carrying one tool
schema came back with `stop_reason: "tool_use"` and a proper structured `tool_use` block
(`{"name":"read_file","input":{"path":"/etc/hosts"}}`) — not the raw-text tool syntax that
made every earlier local setup unusable. gemma-4 emits a `thinking` block before the tool
call, which Claude Code handles; it only matters if you set a tiny `max_tokens` by hand and
the model spends the whole budget thinking.

Read the LMStudio warning below before assuming this works.

```json
"env": {
  "ANTHROPIC_BASE_URL": "http://localhost:24000",
  "ANTHROPIC_API_KEY": "sk-litellm-master",
  "ANTHROPIC_AUTH_TOKEN": "sk-litellm-master",
  "ANTHROPIC_DEFAULT_SONNET_MODEL": "local",
  "ANTHROPIC_DEFAULT_OPUS_MODEL": "local",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL": "local",
  "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
  "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
  "API_TIMEOUT_MS": "3600000",
  "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "253952"
}
```

```bash
ANTHROPIC_BASE_URL="http://localhost:24000" \
ANTHROPIC_API_KEY="sk-litellm-master" \
ANTHROPIC_AUTH_TOKEN="sk-litellm-master" \
ANTHROPIC_DEFAULT_SONNET_MODEL="local" \
ANTHROPIC_DEFAULT_OPUS_MODEL="local" \
ANTHROPIC_DEFAULT_HAIKU_MODEL="local" \
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 \
CLAUDE_CODE_ATTRIBUTION_HEADER=0 \
API_TIMEOUT_MS=3600000 \
CLAUDE_CODE_MAX_CONTEXT_TOKENS=253952 \
claude
```

`sk-litellm-master` is the compose default and needs no `.env` to work. It is the one
alias where using it is defensible — `local` is free — but it still has no ceiling, and
the fallback callout below is why that is not purely academic. Swap in `$AI_GATEWAY_KEY`
for anything long-running.

> **`local` is not guaranteed to stay local.** `litellm/config.yaml` falls back
> `local → cheap-free → cheap` when LMStudio is unreachable. That is deliberate — the
> fallback lands on the *same weights* at OpenRouter, so a stopped LMStudio changes where
> the request ran, not what ran — but it means an "offline" session can quietly become a
> paid one. The budget cap on your key is the guardrail; `GET /spend/logs` is how you
> notice.

### `local-31b` — LMStudio, denser, never leaves the machine

`google/gemma-4-31b` on the host GPU: the same weights `standard` serves from OpenRouter,
run here instead. Same 262144 window as `local`, so configure it identically — `"local-31b"`
in the three model variables, `API_TIMEOUT_MS=3600000`, and the same
`CLAUDE_CODE_MAX_CONTEXT_TOKENS=253952`.

Two reasons to reach for it over `local`:

- **It is dense, not MoE.** `local` is a 26B with ~4B active parameters per token;
  this is 31B with all of them active. Better answers on hard prompts, and slower for the
  same reason — expect the ~100 tok/s prompt-processing floor measured on the other 31B
  below, not `local`'s speed. Its own hand-load is mandatory: it is a *different model*.
- **It cannot become a paid call.** `local` falls back to OpenRouter when LMStudio is
  down; this one has no chain at all and simply fails. For a session that must not leave
  the machine — or must not spend — it is the honest choice, and the callout under `local`
  above does not apply here.

**Tool calling not yet verified on this alias.** `local` and `uncensored` are both
verified with dates; this route is new and carries no such claim. Same gemma-4 family and
the same `require_parameters`-free local path, so it is expected to behave like the other
two — but expected is not verified.

### `uncensored` — LMStudio, abliterated, no safety net

`gemma-4-31b-it-abliterated`, same 262144 window. Configure it exactly like `local` with
`"uncensored"` in the three model variables and the same `API_TIMEOUT_MS=3600000` and
`CLAUDE_CODE_MAX_CONTEXT_TOKENS=253952` — the window and the output reserve are identical.

**Tool calling verified working, 2026-08-21.** A `/v1/messages` request carrying one tool
schema returned `stop_reason: "tool_use"` and a structured block
(`{"name":"get_weather","input":{"city":"Prague"}}`). Like `local` it emits a `thinking`
block first.

Two things differ from `local`, and both matter:

- **It is a different model, so it needs its own hand-load.** `local` is the 26B; this is
  the 31B. Loading both at 262144 puts two large models on one GPU — check `lms ps` rather
  than assuming the one you want is resident.
- **It is slower.** `local` is a 26B MoE with ~4B active parameters; this is 31B dense, so
  every token goes through all of them. The ~100 tok/s prompt-processing figure below was
  measured on *this* model — treat it as the floor, not the average.

> **`uncensored` never falls back, by design.** Every other alias has a chain;
> `litellm/config.yaml` leaves this one out on purpose, because the hosted twin would both
> refuse the request and see a prompt that was chosen to stay on this machine. The
> consequence is that any failure here is terminal — there is no second route to soften it,
> which is why a timeout on this alias surfaces as a bare `API Error`.

### `standard` / `cheap` — OpenRouter

Same shape, `"standard"` or `"cheap"` in the three model variables. Both are gemma-4 via
OpenRouter, `standard` being the 31B.

These are usable from Claude Code **only because of the provider pin** in
`litellm/config.yaml`. OpenRouter load-balances its free tier across providers, and one
of them returns tool calls as raw text (`<|tool_call>call:write_todos{...}`) with
`tool_calls` absent under an agent-scale request. Nothing errors: Claude Code sees an
assistant message with no tool calls, executes nothing, and stops. That is the "tool
calls are a problem" failure from the earlier notes, and the `order: ["google-ai-studio"]`
+ `allow_fallbacks: false` block is what prevents it. **Do not remove it** to "simplify"
the config.

### `frontier` — OpenAI

`"frontier"` in all three. Real money, real tool-calling, no local dependency. Worth
keeping mapped to `opus` so `/model opus` is a deliberate escalation rather than the
default.

## Reusable shortcut

In `~/.zshrc`:

```bash
claude-local() {
  ANTHROPIC_BASE_URL="http://localhost:24000" \
  ANTHROPIC_API_KEY="$AI_GATEWAY_KEY" \
  ANTHROPIC_AUTH_TOKEN="$AI_GATEWAY_KEY" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="local" \
  ANTHROPIC_DEFAULT_OPUS_MODEL="local" \
  ANTHROPIC_DEFAULT_HAIKU_MODEL="local" \
  CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 \
  CLAUDE_CODE_ATTRIBUTION_HEADER=0 \
  API_TIMEOUT_MS=3600000 \
  claude "$@"
}
```

Or keep each configuration in its own gitignored env file:

```bash
set -a; source ./models/local.env; set +a; claude
```

## LMStudio must be hand-loaded

The single most likely reason a `local` session dies at startup. LMStudio JIT-loads a
model that is not resident, and **a JIT load does not inherit hand-load flags** — a model
hand-loaded at 262144 comes back from JIT at 8192. Claude Code's opening request is far
larger than 8192 tokens, so the session fails immediately and looks like a gateway
problem.

Load the model behind the alias you are actually about to use — they are different models:

```bash
lms load google/gemma-4-26b-a4b        --context-length 262144 --parallel 1 --gpu max  # local
lms load google/gemma-4-31b            --context-length 262144 --parallel 1 --gpu max  # local-31b
lms load gemma-4-31b-it-abliterated    --context-length 262144 --parallel 1 --gpu max  # uncensored
lms ps --json    # the source of truth, not the UI
```

262144 is the maximum all three models advertise; `curl -s localhost:1234/api/v0/models`
reports `max_context_length` per model if you need to confirm after a swap.

A JIT-loaded model also gets a 1 h TTL while a hand-loaded one gets none — so a session
that worked this morning can fail this afternoon with nothing changed.

`--parallel 1` is deliberate. Claude Code fires the main turn and its background calls
(session titles, summaries) concurrently; at `--parallel 4` they split one GPU four ways
and everything slows together — a 1-token request measured **34 s** while large prompts
sat in front of it. Serialising is faster end to end.

## A local model is slow, and both timeouts have to know it

Prompt processing on this machine measures **~100 tok/s** — 17.6k tokens took 173 s. Claude
Code re-sends its system prompt plus every tool schema each turn, so a real agent prompt is
20k-80k tokens and needs **5-15 minutes before the first token appears**. Nothing about
that is broken; it is what a 31B model on a laptop costs.

Two timeouts sit in front of it and **both** must be raised, or the shorter one decides:

| Timeout | Default | Set it to |
|:--|:--|:--|
| LiteLLM, per route | 600 s — measured: two prompts were cancelled at 576 s and 590 s | already `timeout: 3600` on `local` and `uncensored` in `litellm/config.yaml` |
| Claude Code, client side | shorter than a local agent turn | `API_TIMEOUT_MS=3600000` in the env block beside the `ANTHROPIC_*` vars |

Raising only the gateway's changes nothing — Claude Code hangs up first, and the gateway
patiently finishes a response nobody is listening for.

## Troubleshooting

| Symptom | Cause | Fix |
|:--|:--|:--|
| `Invalid model name passed in model=claude-...` | one of the three `ANTHROPIC_DEFAULT_*_MODEL` vars is unset, so Claude Code sent a real Claude id | set all three |
| 404 on every request | `/v1` left on `ANTHROPIC_BASE_URL` | drop it — `http://localhost:24000` |
| 401 | key wrong, expired, or budget exhausted | `curl -H "Authorization: Bearer $AI_GATEWAY_KEY" http://localhost:24000/key/info` |
| Fails instantly on `local`, context error | LMStudio JIT-loaded at 8192 | hand-load, § above |
| `API Error` after a long wait; litellm logs `Engine protocol predict request failed: fetch failed` | a timeout fired mid-prompt and tore down LMStudio's engine socket. It maps to a 400, and a 400 is never retried — on `uncensored` there is no fallback to soften it either | raise **both** timeouts, § above |
| Runs a step or two, executes nothing, exits 0 | tool calls returned as text by the wrong OpenRouter provider | the provider pin in `litellm/config.yaml` — check it is intact |
| Your env vars appear to do nothing | `.claude/settings.json` `env` block overrides them | remove the block, or put the values in it |
| `local` session shows non-zero spend | LMStudio was down; the fallback chain ran | expected — see the callout above |
| Status line reads `200k` on any alias | `CLAUDE_CODE_MAX_CONTEXT_TOKENS` unset, so Claude Code assumed 200000 | set it, § *The context window Claude Code assumes* |
| Status line reads `1.0M`, model shows `<alias>[1m]` | the `[1m]` variant was picked in `/model`; it forces 1000000 and suppresses `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `/model` → the plain alias. Overflow past 253952 otherwise falls through to paid `frontier` |

Every request lands in the admin UI's Logs tab at <http://localhost:24000/ui>, prompt and
response included (`store_prompts_in_spend_logs`). When something is wrong, look there
before changing configuration.
