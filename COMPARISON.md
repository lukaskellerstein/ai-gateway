# LiteLLM or Envoy — which gateway, and when

Both gateways in this repo serve **the same alias names from the same engine**. A caller can
move between them by changing a port. So the choice is never about what they can serve; it is
about what they do *around* the request.

This file answers that. It is the only place in the repo that compares them.

- **[The short answer](#the-short-answer)** — if you read one section, read this one.
- **[Features](#features-side-by-side)** — what each one has.
- **[Seeing what went through](#seeing-what-went-through)** — the difference people hit first.
- **[What they cost to run](#what-they-cost-to-run)** — memory, disk, startup. Measured.
- **[What they cost per request](#what-they-cost-per-request)** — the benchmark.
- **[Does the prompt cache hold](#does-the-prompt-cache-hold)** — every agent, both gateways, three engines.
- **[Pick by situation](#pick-by-situation)** — a table you can point at.

---

## The short answer

| | **LiteLLM** · 24000 | **Envoy AI Gateway** · 26000 |
|:--|:--|:--|
| In one line | a **control plane** for LLM traffic | a **data plane** that would run in production |
| Weight | 3 services, a database, ~1 GB RAM | **1 service, no database, ~130 MB RAM** |
| Sees your traffic | **yes, in a web UI, out of the box** | no UI at all — you bring your own |
| Caps spending | **yes** — virtual keys, budgets, spend logs | no, and cannot in this mode |
| Would deploy to a cluster | no | **yes — the config is the cluster's config** |
| Per-request cost | 10–20 ms | 10–20 ms — **the same** |
| What the engine reuses from its cache | the same | **the same** — the client decides it, not the proxy |
| Tells the client what was cached, on LMStudio | only on an `openai/` route's `/v1/responses` | on `/v1/messages` and `/v1/responses` |

**Run LiteLLM.** It is the one every project on this laptop should call. It is the only one
that can tell you what a request cost, cap what a caller spends, and show you the prompt and
the reply without installing anything else.

**Reach for Envoy when you need what LiteLLM has no answer for**: a config that ships to
Kubernetes unchanged, Prometheus metrics, or a proxy small enough that its footprint does
not matter. Both serve an MCP gateway on `/mcp`.

**Never choose on speed.** They are within 10 ms of each other, and both are within 20 ms of
no gateway at all. The model is what you wait for.

---

## What each one is

**LiteLLM is a control plane.** It sits on a postgres database and its job is to *know things*
about traffic: who called, what it cost, how much budget is left, what the prompt and the reply
were. The proxying is almost incidental — the database is the product.

**Envoy AI Gateway is a data plane.** `aigw run` starts a real Envoy from a config file, and
Envoy's job is to move bytes correctly and quickly, then get out of the way. It stores nothing,
because storing things is not a proxy's job. Its config is the same Kubernetes custom-resource
API a cluster would read, so what is proven on this laptop is what would ship.

That difference explains almost every row below. A control plane needs a database, a UI and
about a gigabyte of Python. A data plane needs none of them.

---

## Features, side by side

### Routing and protocols — nearly identical

| | LiteLLM 24000 | Envoy 26000 |
|:--|:--|:--|
| `POST /v1/chat/completions` | yes | yes |
| `POST /v1/embeddings` | yes | yes |
| `POST /v1/responses` — the Codex SDK needs it | yes | yes |
| `GET /v1/models` | yes | yes |
| The Anthropic route — Claude Code needs it | `/v1/messages`, on the plain alias | `/anthropic/v1/messages`, on an `<alias>-anthropic` alias |
| SSE streaming | yes | yes |
| Alias → model mapping | `model_list` entry | an `AIGatewayRoute` rule |
| `/mcp` — MCP servers behind one endpoint, tools renamed by server | yes, `<server>-<tool>`; **checks the caller's key** | yes, `<backend>__<tool>`; checks no caller. **Codex drops its tool list** |
| Test folders that pass | **7/7** on every engine | **7/7** on four engines, 5/7 on hosted OpenAI |

**This is why the choice is safe.** Whichever you pick, all seven ways of calling a gateway
work: raw HTTP, the OpenAI client, LangChain, DeepAgents, the Claude Agent SDK, Codex and
OpenCode. See [`TESTING.md`](TESTING.md) § 3 for the full matrix and the two red cells.

### Governance — LiteLLM only

| | LiteLLM 24000 | Envoy 26000 |
|:--|:--|:--|
| Authenticates the **caller** | **yes** — a bad key is a `401`, measured 2026-09-05 | **no.** The same bad key returns `200`. Anything on this Mac that reaches 26000 can call it; both publish on `127.0.0.1` only |
| Virtual keys, minted per project | **yes**, `/key/generate` | no |
| Budget ceilings that actually stop a caller | **yes** | no |
| Per-request cost, recorded | **yes** — 3550 rows here, each with model, spend and token counts | no |
| Rate limiting (RPM / TPM) | **yes**, per virtual key — available, not configured here | needs Redis plus a full Envoy Gateway install |
| Pre-call context-window check | **yes**, `enable_pre_call_checks` | no |
| A per-route `max_tokens`, price and timeout | **yes** | timeout only |

**This block is the reason LiteLLM is the primary.** Envoy cannot cap a caller in standalone
mode and it is not a configuration mistake: `QuotaPolicy` and token rate limiting need Redis
and the Kubernetes control plane, and `aigw run` writes an Envoy config with no rate-limit
block at all.

**A consequence worth stating plainly:** on 26000 there is no such thing as "this key may
spend $2". If you point a paid engine at Envoy, nothing in this repo will stop a runaway agent.

### Operations and portability — Envoy only

| | LiteLLM 24000 | Envoy 26000 |
|:--|:--|:--|
| The config would run in a **Kubernetes cluster** | no — it is LiteLLM's own YAML | **yes**, unchanged. It is the cluster's API |
| Prometheus metrics | `/metrics` returns **404** on this stock image | **yes**, `26064/metrics`, no auth |
| OpenTelemetry tracing, OpenInference spans | through a callback you configure | **built in** — point it at a collector |
| Runs with no database | no | **yes** |
| Survives a `down -v` with nothing lost | no — that destroys every key and spend row | **yes**, there is nothing to lose |

Measured 2026-09-05: after one request, Envoy's `/metrics` serves
`gen_ai_client_token_usage` and `gen_ai_server_request_duration_seconds`, both as histograms,
following the OpenTelemetry GenAI semantic conventions. Before any traffic it serves only
`target_info` — an empty scrape is not a broken exporter.

### Configuration style

| | LiteLLM 24000 | Envoy 26000 |
|:--|:--|:--|
| An alias costs | one `model_list` entry, plus a price and a context window | one `AIGatewayRoute` rule |
| One config file that serves every engine | **yes** — `all.yaml` is six `include:` lines and copies nothing | **yes** — `all.yaml`, but it **copies** the five engine files, because `aigw run` takes one path and has no `include:` |
| Vendor-specific body fields (`extra_body`) | **yes** — this is what carries the OpenRouter provider pin | **no**, which is why `openrouter-gemma4-26b-free` cannot exist on 26000 |
| Rewrites a parameter the upstream renamed | **yes** — `max_tokens` → `max_completion_tokens` for GPT-5 | **no**, it is a pass-through |
| Reload after a config edit | `restart` the service | `restart` the service |

**The last two rows bite in opposite directions.** LiteLLM's rewriting is why a client that
sends the old parameter name still works on 24000 and fails on 26000. Envoy's pass-through is
why nothing it forwards can be mangled — which is exactly what makes its `-anthropic` aliases
work where a translation would break.

---

## Seeing what went through

**This is the difference most people hit first, and it is bigger than it looks.**

| | LiteLLM 24000 | Envoy 26000 |
|:--|:--|:--|
| A web UI | **yes**, `http://localhost:24000/ui` | **none. There is no UI at all** |
| Prompt and reply, readable, out of the box | **yes** — the Logs tab | no |
| Per-request cost and token counts | **yes** — the Logs tab and `/spend/logs` | no |
| Per-request logging to stdout | yes | only with `AIGW_DEBUG=true` |
| Metrics | no | **yes**, Prometheus on 26064 |
| Traces | through a callback you configure | **OpenTelemetry, built in** |

**On LiteLLM you open a browser and read the conversation.** Nothing to install, nothing to
configure; it is running right now. That is worth more during development than any other single
feature on this page.

**On Envoy you see nothing by default, and that is not a bug.** Envoy runs as a child process
of `aigw` and its access log goes to a file **inside a distroless container** — no shell, so
`compose exec` cannot work and `compose logs` shows only the startup lines however much traffic
you send. Setting `AIGW_DEBUG=true` gives you a JSON access line per request *and* a full
prompt and reply dump, which is why it is off by default.

**To get an Envoy equivalent of the Logs tab you install a second thing.** Envoy emits
OpenTelemetry spans with OpenInference semantics, so the two obvious receivers are:

| Receiver | What it gives you |
|:--|:--|
| **Arize Phoenix** | an LLM trace UI: prompt, reply, tokens, latency, per-span. The closest thing to LiteLLM's Logs tab |
| **Langfuse** | the same plus sessions, scoring and datasets, if you want evaluation rather than debugging |
| Any OTLP collector | spans into whatever you already run |

Neither is wired up in this repo, and neither runs in either compose project. Pointing Envoy at
one is an environment variable and a running collector — check
[the aigw docs](https://aigateway.envoyproxy.io/docs) for the current variable name rather than
guessing, because this repo has never set it.

> **The honest summary.** LiteLLM gives you observability you did not ask for. Envoy gives you
> observability you have to build, and then it is better — real metrics and real traces instead
> of a table in a web page. On a laptop, the first one wins.

---

## What they cost to run

**Measured 2026-09-05 on this machine, both gateways idle on `GATEWAY_ENGINE=unsloth`, under
Podman.**

| | LiteLLM 24000 | Envoy 26000 |
|:--|:--|:--|
| Services running | **2** (`litellm`, `postgres`) + a one-shot that exits | **1** |
| Resident memory | `litellm` **851–963 MB** + `postgres` **155 MB** ≈ **1.0 GB** | **127–136 MB** |
| Container images on disk | 1.22 GB + 483 MB = **1.70 GB** | **410 MB** |
| Database on disk | **124 MB** (4 virtual keys, 3550 spend rows) | **none — it has no database** |
| Restart to serving | **9.4 s** — `restart litellm`, postgres already up | **1.3 s** — `restart`, the whole project |
| First boot, cold | **~60 s**, it runs schema migrations — the `start_period` in `compose.yml`, not measured here | there is no schema to migrate |
| Published ports | 1 (24000) | 2 (26000 data, 26064 admin) |

**Envoy is roughly one seventh of the memory, one quarter of the disk, and seven times faster
to restart.** That is a real difference and it is also, on a 128 GB laptop, mostly an academic
one — a single 26B model resident in LMStudio outweighs both gateways together by an order of
magnitude.

**Where it stops being academic:**

- **Many gateways.** One per team or per environment, and 1 GB each adds up while 130 MB does
  not.
- **A small machine or a container budget.** A 410 MB image starting in a second is a different
  proposition from a 1.7 GB pair that needs a minute and a database.
- **Anywhere you must not lose data.** LiteLLM's 124 MB volume holds every key and every spend
  row, and `down -v` destroys it unrecoverably. Envoy has nothing to protect.

**On CPU, neither is worth measuring.** Both idle at effectively zero, and Podman's `stats`
reports a cumulative average since container start, so a number taken shortly after a restart
is dominated by the startup burst and means nothing. Over 30 minutes of light traffic the
averages were 0.76 % of one core for LiteLLM and 0.41 % for Envoy — a difference with no
practical consequence.

---

## What they cost per request

**Same engine, same model, same body, same `max_tokens`. Only the gateway changes.**

Run it yourself — [`benchmark/`](benchmark/README.md), no dependencies:

```bash
cd benchmark && uv run main.py --rounds 10
```

Measured **2026-09-04**, alias `unsloth-gemma4-e4b` → `unsloth/gemma-4-E4B-it-qat-GGUF` on Unsloth
Studio, MacBook with 128 GB. 10 rounds per scenario, round-robin, one warm-up round discarded,
`max_tokens: 512`, `temperature: 0`. **Medians.**

| Scenario | completion tokens | direct, no gateway | LiteLLM 24000 | Envoy 26000 |
|:--|--:|--:|--:|--:|
| `tiny` — a 2-token reply | 2 | 0.05 s | 0.05 s | **0.05 s** |
| `chat` — one sentence | 8 | 0.06 s | 0.07 s | **0.07 s** |
| `tools` — a `tool_calls` round trip | 157 | 0.29 s | 0.30 s | **0.29 s** |
| `long-prompt` — a ~4 KB body | 264 | 0.31 s | 0.32 s | **0.32 s** |

| Streaming | direct | LiteLLM | Envoy |
|:--|--:|--:|--:|
| time to **first token** | 0.03 s | 0.04 s | 0.06 s |
| whole reply | 0.06 s | 0.08 s | 0.10 s |

### What the numbers say

- **Every gateway costs 10–20 ms, and that is the whole answer.** The overhead is flat: the
  same on a 2-token reply as on a 264-token one, and the same on a 4 KB prompt as on a tiny
  one. A proxy that *processed* the body would scale with it. Neither does.
- **The two are within 10 ms of each other.** Any difference you see between them in a test
  suite is the engine's warm or cold state, or the harness — not the proxy.
- **The completion-token column is the proof that the work was identical.** Every row returns
  the same count in every scenario: same engine, same model, same generation.
- **`max_tokens` had to be sent explicitly, or the comparison would have been a lie.** LiteLLM
  stores a route default and Envoy stores none, so a body without a ceiling asks LiteLLM to do
  *less work*. That single control is the difference between a benchmark and a number.

> **A test suite's wall clock is not a gateway benchmark.** A folder's seconds are dominated by
> building a venv, importing LangChain, spawning a CLI, and whether the engine had the model
> warm — the **same script on the same gateway** ranged from 5.8 s to 46.7 s over eight runs.
> That is why `benchmark/` times one HTTP request and holds everything else still.

---

## Does the prompt cache hold

**Per client and per model, the numbers are in each test folder's `RESULTS.md`** — the same
three-turn task through every client, seven models, both gateways, written by that folder's
`uv run run_benchmark.py` (§ Per client, below). The tables before it come from a one-off run
the same day that also read LMStudio's own log, which is how they know what the engine
REALLY reused and not only what the client was told: each agent's own multi-turn scenario,
live, on both gateways, three engines, two models, at thinking level `medium` — 96 sessions,
**95 passed first time**, and the one failure passes after the fix below. Claude runs twice —
as shipped, and with the two settings that stop it rewriting its prompt.

### What the engine reused — LMStudio, last turn of each session

LMStudio's own log says what it took from its cache, and **it was the same through both
gateways**: same agent, same model, same share, to within a 256-token block. So one column per
model, not per gateway:

| Agent | Gemma 4 26B | Qwen 3.8 27B |
|:--|--:|--:|
| `1_http_client` | 23% | 0% — its two calls share no prefix |
| `2_openai_client` | 80% | 56% |
| `3_langchain_langgraph` | 79% | 57% |
| `4_deepagents` | 97% | 93% |
| **Claude Agent SDK, as shipped** | **22%** | **0%** |
| Claude Agent SDK, two settings | 85–93% | 76–79% |
| Codex | 97–98% | 98% |
| OpenCode | 98% | 96–97% |

- **The gateway does not change the reuse. The client does.** The only low rows with a real
  conversation are Claude as shipped.
- **Claude Code rewrites its own system prompt after every tool result.** It adds a
  `<total_tokens>` line there, in front of the tool list and every message, so the whole
  conversation is recomputed each turn. `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=off` and
  `CLAUDE_CODE_ATTRIBUTION_HEADER=0` fix it — `litellm/README.md` § Use it from Claude Code,
  trap 4. The second one matters across sessions: the billing header carries a suffix that
  changes per conversation, so no two Claude sessions share even the system prompt. Codex and
  OpenCode reuse their whole harness from the session before.
- **Short prompts read low because LMStudio mostly reuses in 256-token blocks.** 47 of the 49
  reuse counts above 256 were exact multiples of 256, so a 450-token prompt can lose up to 255
  tokens of a perfect hit. At Codex's 8 500 tokens the loss is 2%.

### What the client is told

| | LiteLLM | Envoy |
|:--|:--|:--|
| LMStudio, `/v1/chat/completions` | 0 — LMStudio reports none on this route, even on a 98% hit | 0, the same |
| LMStudio, Claude (`/v1/messages`) | 0 — LiteLLM makes it a chat call | **reported**, 24–44% of the session; 0 for Claude as shipped on Qwen |
| LMStudio, Codex (`/v1/responses`) | 0 on `lm_studio/`; 80% on `lms-qwen38-27b`, which is on `openai/` | **reported**, 49–79% |
| Unsloth, chat | reported, 42–69% | reported, 42–69% |
| OpenRouter Gemma | reported, 40–69% | reported, 40–69% |
| OpenRouter Qwen | 0 on most sessions | 45–53% on three sessions, 0 on the rest |

These are shares of the **whole session**, first request included, so a two-request session
with a perfect second hit reads **50%**. OpenRouter's Qwen figure depends on which provider
OpenRouter picks for the call, not on the gateway. Unsloth reported 0 on Claude through Envoy
and on Codex through both — whether it hit is unknown, because it keeps no log to read.

### Per client and per model — the `RESULTS.md` files

Each test folder's `run_benchmark.py`: one three-turn task — a ~1500-token policy, a file to
read with a tool, a follow-up, a customer message — through seven clients and both gateways.
Medians over each alias's 14 runs (7 clients × 2 gateways). **140 sessions in the table, every
one answered correctly.**

The local rows were measured on **2026-10-02 with ONE model loaded at a time**, at 262144
context, with `--no-write` — so they are not what the `RESULTS.md` files hold. Those are
2026-09-30, with every model loaded at once and Unsloth's Qwen at Q8. The two OpenRouter rows
are from that run; the laptop does not change them.

| Alias | Build | Decode tok/s | First token, request 1 | First token, last request |
|:--|:--|--:|--:|--:|
| `lms-gemma4-26b` | MLX 4-bit QAT · 26B MoE | 105 (47–112) | 1.1 s | 0.32 s |
| `lms-gemma-4-31b` ¹ | MLX 4-bit · 31B dense | 18 (14–25) | 7.8 s | 1.4 s |
| `lms-qwen38-27b` | MLX 4-bit · 27B dense | 24 (17–26) | 7.1 s | 0.87 s |
| `unsloth-gemma4-26b` | UD-Q4_K_XL QAT · 26B MoE | 142 (73–247) | 1.4 s | 0.31 s |
| `unsloth-gemma-4-31b-qat` ¹ | UD-Q4_K_XL QAT · 31B dense | 27 (13–31) | 16.3 s | 1.3 s |
| `unsloth-qwen38-27b` | UD-Q8_K_XL · 27B dense | 23 (13–34) | 9.4 s | 0.95 s |
| *the same, UD-Q4_K_XL* | UD-Q4_K_XL · 27B dense | 21 (12–41) | 10.1 s | 0.93 s |
| `ollama-gemma4-26b` | Q4_K_M · 26B MoE | 108 (89–164) | 1.6 s | 0.20 s |
| `openrouter-gemma4-26b` | the provider's · 2026-09-30 | 85 (57–112) | 2.0 s | 2.2 s |
| `openrouter-qwen38-27b` | the provider's · 2026-09-30 | 44 (29–55) | 0.7 s | 0.6 s |

¹ In the personal `config/lukas.yaml` only, on both gateways — not in the shared vocabulary.

- **Gemma 4 31B against Qwen 3.8 27B — both dense, both 4-bit, measured back to back — and
  the engine decides which is faster.** On LMStudio Gemma is 25% slower (18 against 24 tok/s).
  On Unsloth it is 29% faster than Qwen's Q4 (27 against 21), and 17% faster than its Q8 (23). Unsloth drafts tokens ahead for both — Gemma
  from a separate MTP file, Qwen from the head inside its GGUF, both shown by `/v1/status` —
  and no draft model was set in LMStudio. Why drafting helps Gemma more was not measured.
- **Q4 is not faster than Q8 for Qwen on Unsloth**: 21 against 23 tok/s the same day, and the
  Q8 was faster in 12 of 14 paired sessions. What the Q4 buys is memory, 17.6 GB against 31.5.
  Why the speed does not follow the bytes was not measured. So `unsloth-qwen38-27b` is pinned
  to `:UD-Q8_K_XL`.
- **The dense rows ran about 20% slower than on 2026-09-30**: `lms-qwen38-27b` 24 against 31,
  Unsloth's Q8 23 against 27. The three 26B MoE rows matched that day within 11% (105 / 100,
  142 / 145, 108 / 121). A dense model reads all its weights for every token, a MoE about a
  sixth, so memory bandwidth hits the dense ones hardest — and 10 GB of swap was in use. Another
  caller also used the engines that day: Unsloth's logs show Gemma 26B reloaded between this
  run's Gemma 31B sessions. Neither cause is proven. **Compare rows measured on the same day.**
- **The last request's first token is the prompt cache at work.** On all three local engines it
  falls to 0.2–1.4 s whatever the client, because the conversation so far is a prefix the
  engine already holds. OpenRouter's does not fall: it spreads requests over providers, and a
  hit needs the same one twice.
- **Unsloth's range is wide for the same reason it is fast.** Drafting pays most on short,
  predictable replies such as a tool call: 247 tok/s on Deep Agents' task, 73 on Claude's.
- **A dense model waits 7–16 s for its first token on a local engine; a 26B MoE waits 1–2 s.**
  Codex and OpenCode send 7 000–8 500 prompt tokens, and those rows set the upper end.

What the client itself adds, and what bit:

| Client | Prompt, request 1 | Watch out |
|:--|--:|:--|
| raw HTTP, `openai`, LangChain | 2 020 | nothing. LangChain reports no token counts without `stream_usage=True` |
| Deep Agents | 4 350 | its harness adds about 2 300 tokens |
| Claude Agent SDK | 2 530 | one session-title request of its own beside request 1. Through Envoy the engine wrote ~1 000 tokens for it, and request 1 waited 13–29 s |
| Codex | 8 240 | through LiteLLM on an `lm_studio/` alias: 10 500 tokens, no streamed tokens, no cache count. The provider, not Codex — `lms-qwen38-27b` on `openai/` streams |
| OpenCode | 7 200 | its provider id must not collide with `~/.config/opencode`, which it merges model by model |

Codex's prompt reads 10 400–11 400 on Ollama and OpenRouter, which count the same request
differently. The setup behind every row — thinking level, streaming, isolation, ceilings — is
at the top of each `RESULTS.md`; that list is the part another project copies.

The one-off cache run above cost about **$0.04** across both gateways, OpenRouter's own figure.

**The one fix.** Codex failed on `lms-qwen38-27b` through LiteLLM after the thinking-level fix
of the same day: LiteLLM turned Codex's `reasoning` object into a malformed field on the
`lm_studio/` provider. Moving that alias to `openai/` fixed it — `TESTING.md` §6.12.

---

## Pick by situation

| If you are… | Choose | Because |
|:--|:--|:--|
| running everyday work from your projects | **LiteLLM** | it is the one with keys, ceilings and a UI, and the one this repo treats as primary |
| debugging a prompt, or asking "what did it actually send?" | **LiteLLM** | the Logs tab has the prompt and the reply, now, with nothing to install |
| pointing anything at a **paid** engine | **LiteLLM** | it is the only one that can cap a caller. Envoy will not stop a runaway agent |
| asking "what did this month cost?" | **LiteLLM** | `/spend/logs` records a cost per request; Envoy records nothing |
| handing a project a scoped credential | **LiteLLM** | virtual keys with a budget and an expiry |
| about to deploy this to Kubernetes | **Envoy** | its config *is* the cluster's config. LiteLLM's YAML is not |
| putting MCP servers behind one endpoint | **LiteLLM** | both serve `/mcp`, and only LiteLLM checks who calls a tool |
| feeding Prometheus or an OTel collector | **Envoy** | metrics and spans are built in; LiteLLM's `/metrics` is a 404 here |
| running many gateways, or on a small machine | **Envoy** | 130 MB and a 1.3 s start, against 1 GB and a database |
| comparing two engines' behaviour | **either** | they serve the same aliases; that is the point |
| choosing on latency | **either** | 10–20 ms apart. This is not the decision |
| checking whether an agent's prompt cache holds | **Envoy** | it reports cached tokens on the Claude and Codex routes; LiteLLM reports 0 there on LMStudio. The engine reuses the same through both |

### Running both

They are separate compose projects on separate ports with separate `.env` files, so **running
both at once is normal** and neither notices the other. That is how the numbers on this page
were measured.

Two things to know if you do:

- **They can be on different engines**, and nothing checks that they agree. An alias that
  answers on one port and 404s on the other is as likely to be two different `GATEWAY_ENGINE`
  words as a missing route.
- **Unsloth Studio swaps one active model**, across chat and embeddings alike. Two gateways
  asking it for different aliases will swap the model back and forth — unless both models were
  loaded in Studio with `Keep other models loaded` first, which keeps them side by side
  (v0.1.903-beta, verified 2026-10-07). LMStudio and Ollama do not have this problem.

---

## What neither of them does

Worth knowing before you expect it from the wrong one.

- **Neither falls back to another alias.** No retry chains, no silent reroute to a second
  provider. It is deliberate: a comparison stops being a comparison the moment a request can
  run somewhere else, and a free session can silently become a paid one.
- **Neither serves more than one engine at a time.** `GATEWAY_ENGINE` names one file. Every
  other engine's aliases are absent from the running config, so a 404 on one is correct.
- **Neither checks that the other's alias list agrees with its own.** An alias is one edit per
  gateway, and nothing catches a missed one.
- **Neither is exposed beyond localhost**, and Envoy in particular must not be — it
  authenticates no caller at all.
- **Neither covers embeddings in its test suite.** Both routes work — verified 2026-09-05, 768
  dimensions on each — but no test folder exercises them.

---

Full alias table, engine facts and design decisions: [`README.md`](README.md).
Test coverage, versions and open bugs: [`TESTING.md`](TESTING.md).
Each gateway's own detail: [`litellm/README.md`](litellm/README.md) ·
[`envoy/README.md`](envoy/README.md).
