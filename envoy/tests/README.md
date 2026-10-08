# tests — seven ways to call the Envoy AI Gateway

Seven folders, each a working program against **this project's gateway on 26000**.
They are ordered by distance from the wire: raw HTTP first, then OpenAI's own
client, then five agent frameworks.

| Folder | Reaches the gateway through | Proves |
|:--|:--|:--|
| [`1_http_client`](1_http_client/README.md) | `urllib` — **no dependencies at all** | the request every other folder wraps, plain and streaming |
| [`2_openai_client`](2_openai_client/README.md) | `openai` | six scenarios: chat, tools, an image, this gateway's calling contract, the thinking level, and thinking off |
| [`3_langchain_langgraph`](3_langchain_langgraph/README.md) | `ChatOpenAI(base_url=…)` | LangChain's prebuilt agent, the same ReAct loop built by hand in LangGraph, and a tool behind the gateway's `/mcp` |
| [`4_deepagents`](4_deepagents/README.md) | the same `ChatOpenAI` | a deep agent — eight scenarios: query, todos, filesystem, tools, mcp, subagent, skill, gateway mcp |
| [`5_claude_agent_sdk`](5_claude_agent_sdk/README.md) | `ANTHROPIC_BASE_URL` → `/anthropic/v1/messages` | **the Anthropic surface**, and the worked agent: query, session, in-process MCP, stdio MCP, subagent, skill, thinking, gateway MCP |
| [`6_codex_sdk`](6_codex_sdk/README.md) | a `model_providers` override → `/v1/responses` | **the Responses surface** — the only protocol Codex speaks. Its gateway MCP scenario is wired, not called (codex#19871) |
| [`7_opencode_sdk`](7_opencode_sdk/README.md) | an `@ai-sdk/openai-compatible` provider | OpenCode over its HTTP server API — query, session, agent, MCP, structured output, gateway MCP |

**All seven run here**, and all seven run on `../../litellm` too.

## Run

The gateway must be up first — `podman compose up -d` in the parent directory.

```bash
cd tests
uv run run_all.py                      # all seven, one row each
uv run run_all.py --only 6_codex_sdk   # one folder
uv run run_all.py --model lms-gemma4-26b      # a different alias everywhere
uv run run_all.py --verbose            # stream each folder instead of capturing it
```

`uv run run_benchmark.py` in a folder measures that client instead — see below.

Or one folder on its own — this is the normal way to read them:

```bash
cd 3_langchain_langgraph
uv run run.py
```

`run_all.py` probes **`26000/v1/models`, not `26064/health`**. The admin server
answers `OK` several seconds before Envoy's listener accepts a connection, so
probing it races the thing being tested and the first folder then fails with a
connection reset (measured 2026-09-04).

## Seven folders, seven projects — copy one

Each folder carries its **own** `pyproject.toml`, its own `.venv` and its own
`settings.py`. The folders are examples to copy: take one into another project, edit
its `settings.py`, and it calls this gateway the way this repo measured to be right —
the thinking level set, and nothing in the request that breaks the engine's prompt
cache.

**`settings.py` is the one file that differs from the same folder in `../../litellm/tests`.**
Everything else in a folder is byte-identical between the two projects and names no
port, key or model. Nothing is shared between folders: `tests/gateway.py` held the
URL, the key and the alias for all seven until 2026-09-30, and it went because a
folder that imports `../gateway.py` cannot be copied alone.

`uv run --directory` builds whichever venv is missing, so a fresh clone needs no
`uv sync` first. Adding a folder is two edits: write it, and add its name to
`FOLDERS` in `run_all.py`.

## This gateway is not a copy of the other one

Measured 2026-09-04:

| Surface | Envoy `:26000` | LiteLLM `:24000` |
|:--|:--|:--|
| `/v1/chat/completions` | 200 | 200 |
| `/v1/models` | **200** | 200 |
| `/v1/responses` — Codex needs this | **200** | 200 |
| Anthropic messages | `/anthropic/v1/messages`, **translated** | `/v1/messages`, native |
| checks the caller's key | **no** | yes |
| `response.model` echoes the alias | **no** | yes |
| a stored `max_tokens` per route | **no** | yes |

It lists its models like LiteLLM and checks no caller key at all, so a test written
as "LiteLLM or not-LiteLLM" is wrong about it.

## The Anthropic surface costs one alias, and this suite is what found it

Folder 5 is where this suite earns its keep, and the finding is not visible from
any config file.

**`/anthropic/v1/messages` on a plain alias cannot carry an agent conversation.**
That route is TRANSLATED Anthropic → OpenAI. Envoy builds a `thinking` block into
every reply out of the engine's `reasoning_content`; Claude Code sends the reply
back on turn two; the translator passes the block straight into the OpenAI body;
and an OpenAI `content` part may only be `text` or `image_url`. So the **engine**
answers `400 messages.N.content.str: Input should be a valid string`.

**It is not this gateway's bug.** The identical error comes back from Unsloth on
port 8888 with no gateway in the path, and from LMStudio and Ollama too (measured
2026-09-04). It was intermittent — about 1 run in 5 — because the engine emits
`reasoning_content` on some replies and not others, which is worse than broken.

**The cure is `<alias>-anthropic`**, a second alias on an `AIServiceBackend` whose
schema is `Anthropic`, so the body goes upstream untranslated. All three local
engine configs carry two of them now, because all three engines serve
`POST /v1/messages` natively. Folder 5 resolves that alias at runtime and
**exits with instructions when it is missing — it does not skip**.

`MAX_THINKING_TOKENS=0` used to be required and no longer is: it existed for
`400 thinking.type` from the same translator, and the pass-through path accepts
Claude Code's `thinking` field as sent.

The Responses surface has neither problem, and needs no extra configuration at all
— the same `AIGatewayRoute` rule carries it, because the gateway takes the alias
from the request body's `model` field either way.

> **This suite drives one gateway.** Until 2026-09-03 there was one `tests/` at the
> repo root that ran every script against two ports, and it was the thing that
> caught two alias lists drifting apart. Each gateway is a standalone compose
> project now, so that check has no owner: **nothing here, and nothing anywhere in
> the repo, verifies that an alias answering on 26000 also answers on 24000.** Call
> the other port by hand when it matters.

## Which alias gets called

Each folder's `settings.py` names `lms-gemma4-e4b` — the small Gemma on LMStudio,
served by the `lms`, `all` and `lukas` configs, and both vision- and tool-capable,
which is what every scenario here needs from one loaded model.

| Override | Scope |
|:--|:--|
| `--model <alias>` | one run — every folder through `run_all.py`, or one folder |
| `AI_GATEWAY_MODEL` | this shell |
| `MODEL` in `settings.py` | that folder, for good — the edit to make when you copy it |

Until 2026-09-30 the default followed `GATEWAY_ENGINE` in `../.env`. It no longer
does, because a copied folder has no `../.env` to read. When this project serves one
other engine, name one of its aliases. `curl localhost:26000/v1/models` says which are served.

## `max_tokens` is not optional here

`body_extras()` in each folder's `settings.py` carries `max_tokens: 8192` — or
`max_completion_tokens` for `openai-*` — and every request sends it. An `AIGatewayRoute` rule carries a request **timeout** but no token
ceiling. Measured 2026-09-04, one "count from 1 to 3000" prompt with **no**
`max_tokens`:

| Gateway | `finish_reason` | completion tokens |
|:--|:--|--:|
| **Envoy** | `stop` | **13946** — nothing bounded it |
| LiteLLM | `length` | 4095 — the route's stored 4096 |

## Two binaries these folders need, and `uv` cannot install

| Folder | Needs | Install |
|:--|:--|:--|
| `5_claude_agent_sdk` | the `claude` CLI — the SDK spawns it | `npm install -g @anthropic-ai/claude-code` |
| `7_opencode_sdk` | the `opencode` binary | `curl -fsSL https://opencode.ai/install \| bash` |

Both scripts check PATH first and print the install line rather than failing inside
a library. `6_codex_sdk` needs nothing extra: `openai-codex` ships its own pinned
runtime.

## `run_benchmark.py` — what each way of calling costs, per model

`run_all.py` asks "does it work". Each folder's `run_benchmark.py` asks **"how fast, and
does the prompt cache hold"**, with that folder's own client, on several models:

```bash
cd 5_claude_agent_sdk
uv run run_benchmark.py                                     # the default models, writes RESULTS.md
uv run run_benchmark.py --aliases lms-gemma4-26b --no-write
```

Every folder runs the SAME task, from the shared part at the bottom of its
`run_benchmark.py` — byte-identical in all fourteen folders: a ~1500-token policy, a file to read (`order.json`), a follow-up, and
a customer message, as three turns of one conversation. Every request streams, so each
one's first token, decode speed and cached count are measured on that request. The
agents (folders 4 to 7) read the file with their own file tool.

The numbers are in each folder's `RESULTS.md`. **Its setup list is the part to copy**:
every setting of that client that changes the cache, the thinking level or the speed.
A `not reported` in the cached column is LMStudio's chat completions route, which never
sends the count (lmstudio-ai/lmstudio-bug-tracker#778) — the first-token times still
show the hit. The `openrouter-*` rows bill a real account.

The medians over all fourteen folders, both gateways, and what each client adds to the
prompt are in [`../../COMPARISON.md`](../../COMPARISON.md) § Per client and per model.

## MCP servers behind the gateway

Each agent folder, 3 to 7, has ONE scenario that reaches an MCP server **only through
this gateway's `/mcp`**: demo `mcp` in folder 3, `08_gateway_mcp.py` in 4 and 5,
`05_gateway_mcp.py` in 6 and `06_gateway_mcp.py` in 7. The scenario starts the folder's
own `mcp_server.py` over HTTP on the port the gateway's config names — `MCP_SERVER_PORT`
in `settings.py`, 26090 here — and gives the agent nothing but `MCP_URL`. The tools
arrive renamed `bench-hardware__bench_serial`, and that name is what the scenarios assert.

| Folder | The tool is called through `/mcp` |
|:--|:--|
| `3_langchain_langgraph`, `4_deepagents`, `5_claude_agent_sdk`, `7_opencode_sdk` | **yes**, asserted |
| `6_codex_sdk` | **no, on any model.** Codex lists the tools and drops them: this gateway's list carries `cacheScope: ""` — `../../TESTING.md` §5.7 |

A port that is already taken fails the scenario loudly. The other suite uses 24090, so
both suites can run at the same time.

## What is NOT tested here

- **Embeddings.** The `*-embed` aliases route fine, but the chat client these
  folders share does not drive `/v1/embeddings`.
- **`/metrics` on 26064.**
- **`openai.yaml`.** It parses and registers its aliases, but no call has been made
  through it — that would bill a real account. OpenRouter has: every folder's
  `run_benchmark.py` runs both OpenRouter aliases.
- **`openrouter-gemma4-26b-free`.** Absent here by design: no `extra_body`, so no provider pin.
- **That the same alias answers on 24000.** See the note above.

## Verified

2026-09-30, `lms-gemma4-26b`: all seven folders passing, every scenario in them too, after
the move to per-folder `settings.py`. The timings below are older — 2026-09-04,
`unsloth-gemma4-e4b`:

| Folder | Seconds, warm |
|:--|--:|
| `1_http_client` | 0.2 |
| `2_openai_client` | 6 |
| `3_langchain_langgraph` | 1.5 |
| `4_deepagents` | 15-60 — EIGHT scenarios |
| `5_claude_agent_sdk` | 40-120 — EIGHT scenarios, each spawning the `claude` CLI |
| `6_codex_sdk` | 20-50 — FIVE scenarios, Codex sends a large harness per turn |
| `7_opencode_sdk` | 15-60 — SIX scenarios, each spawns an `opencode` server |

> **These are wall-clock seconds for the whole folder, warm** — one process, its
> imports, and every model call it makes. **They are not a gateway benchmark, and
> they cannot be compared with the sibling suite's numbers.** Both gateways proxy
> the *same* engine, and measured round-robin on 2026-09-04 the request itself took
> 0.08 s on LiteLLM and 0.32 s on Envoy at the median — tens of milliseconds
> apart. What moves a folder's number is the
> engine's warm/cold state, how many calls the folder makes, and whether it spawns
> an external CLI. Never which proxy is in front.
>
> A folder's **first** run in a session also builds its venv, and the first call
> after the engine loads a model pays for the load. Both add tens of seconds and
> neither repeats. Compare a folder against itself, warm — not against a sibling.

Run with `AI_GATEWAY_MODEL=unsloth-gemma4-e4b`.

Two extra requirements when the engine is `unsloth`, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   `${UNSLOTH_API_KEY}` substitutes empty and every `unsloth-*` call 401s.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. A gateway call swaps Unsloth's **one active model**, so more
   than one gateway on `unsloth` will thrash it — run one suite at a time, or pre-load the
   models in Studio with `Keep other models loaded` so they stay side by side.
