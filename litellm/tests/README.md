# tests — seven ways to call the LiteLLM gateway

Seven folders, each a working program against **this project's gateway on 24000**.
They are ordered by distance from the wire: raw HTTP first, then OpenAI's own
client, then five agent frameworks.

| Folder | Reaches the gateway through | Proves |
|:--|:--|:--|
| [`1_http_client`](1_http_client/README.md) | `urllib` — **no dependencies at all** | the request every other folder wraps, plain and streaming |
| [`2_openai_client`](2_openai_client/README.md) | `openai` | six scenarios: chat, tools, an image, this gateway's calling contract, the thinking level, and thinking off |
| [`3_langchain_langgraph`](3_langchain_langgraph/README.md) | `ChatOpenAI(base_url=…)` | LangChain's prebuilt agent, the same ReAct loop built by hand in LangGraph, and a tool behind the gateway's `/mcp` |
| [`4_deepagents`](4_deepagents/README.md) | the same `ChatOpenAI` | a deep agent — eight scenarios: query, todos, filesystem, tools, mcp, subagent, skill, gateway mcp |
| [`5_claude_agent_sdk`](5_claude_agent_sdk/README.md) | `ANTHROPIC_BASE_URL` → `/v1/messages` | **the Anthropic surface** and the worked agent: query, session, in-process MCP, stdio MCP, subagent, skill, thinking, gateway MCP |
| [`6_codex_sdk`](6_codex_sdk/README.md) | a `model_providers` override → `/v1/responses` | **the Responses surface** — the only protocol Codex speaks. Its gateway MCP scenario is wired, not called (codex#19871) |
| [`7_opencode_sdk`](7_opencode_sdk/README.md) | an `@ai-sdk/openai-compatible` provider | OpenCode over its HTTP server API — query, session, agent, MCP, structured output, gateway MCP |

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

Every program exits `0` on pass and `1` on fail, so they work in a shell chain.
`run_all.py` refuses to start if 24000 is not answering, rather than letting seven
folders fail the same way.

## Seven folders, seven projects — copy one

Each folder carries its **own** `pyproject.toml`, its own `.venv` and its own
`settings.py`. The folders are examples to copy: take one into another project, edit
its `settings.py`, and it calls this gateway the way this repo measured to be right —
the thinking level set, and nothing in the request that breaks the engine's prompt
cache.

**`settings.py` is the one file that differs from the same folder in `../../envoy/tests`.**
Everything else in a folder is byte-identical between the two projects and names no
port, key or model. Nothing is shared between folders: `tests/gateway.py` held the
URL, the key and the alias for all seven until 2026-09-30, and it went because a
folder that imports `../gateway.py` cannot be copied alone.

`uv run --directory` builds whichever venv is missing, so a fresh clone needs no
`uv sync` first. Adding a folder is two edits: write it, and add its name to
`FOLDERS` in `run_all.py`.

## What this gateway offers that the others do not

Every folder here runs, and every folder runs on the sibling suite too. Measured
2026-09-04:

| Surface | LiteLLM `:24000` | Envoy `:26000` |
|:--|:--|:--|
| `/v1/chat/completions` | 200 | 200 |
| `/v1/models` | 200 | 200 |
| `/v1/responses` — Codex needs this | **200** | **200** |
| Anthropic messages — the Claude SDK needs this | `/v1/messages` | `/anthropic/v1/messages`, on a pass-through alias |
| a stored `max_tokens` per route | **yes** | no |

The last row is why each folder's `settings.py` sends no ceiling here and `max_tokens:
8192` in the sibling: LiteLLM stores a ceiling on every route in `../config/`, so a caller
who sends none still gets a bounded reply.

> **This suite drives one gateway.** Until 2026-09-03 there was one `tests/` at the
> repo root that ran every script against two ports at once, and it was the thing
> that caught two alias lists drifting apart. Each gateway is a standalone compose
> project now, so that check has no owner: **nothing here, and nothing anywhere in
> the repo, verifies that an alias answering on 24000 also answers on 26000.** Call
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
other engine, name one of its aliases. `curl localhost:24000/v1/models` says which are served.

## Two binaries these folders need, and `uv` cannot install

| Folder | Needs | Install |
|:--|:--|:--|
| `5_claude_agent_sdk` | the `claude` CLI — the SDK spawns it | `npm install -g @anthropic-ai/claude-code` |
| `7_opencode_sdk` | the `opencode` binary | `curl -fsSL https://opencode.ai/install \| bash` |

Both scripts check PATH first and print the install line rather than failing inside
a library. `6_codex_sdk` needs nothing extra: `openai-codex` ships its own pinned
runtime.

## Verified

2026-09-30, `lms-gemma4-26b`: all seven folders passing, every scenario in them too, after
the move to per-folder `settings.py`. The timings below are older — 2026-09-04,
`unsloth-gemma4-e4b`:

| Folder | Seconds, warm |
|:--|--:|
| `1_http_client` | 0.2 |
| `2_openai_client` | 4 |
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

`2_openai_client` is six scripts in six processes; `5_claude_agent_sdk` spawns the
`claude` CLI once per demo. Every other row is one process and one or two calls.

Two extra requirements when `GATEWAY_ENGINE=unsloth`, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   every `unsloth-*` route 401s at call time.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. A gateway call swaps Unsloth's **one active model**, so more
   than one gateway on `unsloth` will thrash it — run one suite at a time, or pre-load the
   models in Studio with `Keep other models loaded` so they stay side by side.

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
in `settings.py`, 24090 here — and gives the agent nothing but `MCP_URL`. The tools
arrive renamed `bench_hardware-bench_serial`, and that name is what the scenarios assert.

| Folder | The tool is called through `/mcp` |
|:--|:--|
| `3_langchain_langgraph`, `4_deepagents`, `5_claude_agent_sdk`, `7_opencode_sdk` | **yes**, asserted |
| `6_codex_sdk` | **no** on a local alias — openai/codex#19871, as in its `04_mcp.py`. **Yes** on `openrouter-gemma4-26b`, which bills, so only `--model` runs it |

A port that is already taken fails the scenario loudly. The other suite uses 26090, so
both suites can run at the same time.

## What is NOT tested here

- **Embeddings.** Every `*-embed` alias needs a different route from the chat one
  these folders share.
- **Budgets and virtual keys.** [`../README.md`](../README.md) has the `curl`.
- **That the same alias answers on 26000.** See the note above.
