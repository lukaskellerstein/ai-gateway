# tests — seven ways to call the LiteLLM gateway

Seven folders, each a working program against **this project's gateway on 24000**.
They are ordered by distance from the wire: raw HTTP first, then OpenAI's own
client, then five agent frameworks.

| Folder | Reaches the gateway through | Proves |
|:--|:--|:--|
| [`1_http_client`](1_http_client/README.md) | `urllib` — **no dependencies at all** | the request every other folder wraps, plain and streaming |
| [`2_openai_client`](2_openai_client/README.md) | `openai` | four scenarios: chat, tools, an image, and this gateway's calling contract |
| [`3_langchain_langgraph`](3_langchain_langgraph/README.md) | `ChatOpenAI(base_url=…)` | LangChain's prebuilt agent, and the same ReAct loop built by hand in LangGraph |
| [`4_deepagents`](4_deepagents/README.md) | the same `ChatOpenAI` | a deep agent — seven scenarios: query, todos, filesystem, tools, mcp, subagent, skill |
| [`5_claude_agent_sdk`](5_claude_agent_sdk/README.md) | `ANTHROPIC_BASE_URL` → `/v1/messages` | **the Anthropic surface** and the worked agent: query, session, in-process MCP, stdio MCP, subagent, skill, thinking |
| [`6_codex_sdk`](6_codex_sdk/README.md) | a `model_providers` override → `/v1/responses` | **the Responses surface** — the only protocol Codex speaks |
| [`7_opencode_sdk`](7_opencode_sdk/README.md) | an `@ai-sdk/openai-compatible` provider | OpenCode over its HTTP server API — query, session, agent, MCP, structured output |

## Run

The gateway must be up first — `podman compose up -d` in the parent directory.

```bash
cd tests
uv run run_all.py                      # all seven, one row each
uv run run_all.py --only 6_codex_sdk   # one folder
uv run run_all.py --model lms-26b      # a different alias everywhere
uv run run_all.py --verbose            # stream each folder instead of capturing it
```

Or one folder on its own — this is the normal way to read them:

```bash
cd 3_langchain_langgraph
uv run main.py
```

Every program exits `0` on pass and `1` on fail, so they work in a shell chain.
`run_all.py` refuses to start if 24000 is not answering, rather than letting seven
folders fail the same way.

## Seven folders, seven projects

Each folder carries its **own** `pyproject.toml` and its own `.venv`. That is
deliberate: the dependency sets have nothing in common — `1_http_client` has none
at all, and DeepAgents, the Codex runtime and the Claude Agent SDK have no reason
to share a resolver. `uv run --directory` builds whichever venv is missing, so a
fresh clone needs no `uv sync` first.

**What they DO share is [`gateway.py`](gateway.py)**, one level up: the base URL,
the key and the alias. Three facts written down seven times would be six places to
forget when `GATEWAY_ENGINE` changes, and nothing would report the ones you missed.
It imports **nothing but the standard library**, which is what lets it import
inside `1_http_client`'s empty venv, and it reads only this project's own files —
nothing here looks at `../../envoy`.

Adding a folder is two edits: write it, and add its name to `FOLDERS` in
`run_all.py`.

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

The last row is why `BODY_EXTRAS` in `gateway.py` is **empty** here and carries
`{"max_tokens": 2048}` in the sibling: LiteLLM stores a ceiling on every route in
`../config/`, so a caller who sends none still gets a bounded reply.

> **This suite drives one gateway.** Until 2026-09-03 there was one `tests/` at the
> repo root that ran every script against two ports at once, and it was the thing
> that caught two alias lists drifting apart. Each gateway is a standalone compose
> project now, so that check has no owner: **nothing here, and nothing anywhere in
> the repo, verifies that an alias answering on 24000 also answers on 26000.** Call
> the other port by hand when it matters.

## Which alias gets called

`gateway.py` reads `GATEWAY_ENGINE` from `../.env` — this project's own, not a
repo-root one — and picks that engine's small chat route: `lms-4b`, `unsloth-4b`,
`ollama-4b` or `openrouter-26b`. Each is the one alias on its engine that is both
vision- and tool-capable, which is what every folder here needs from a single
loaded model.

**One engine runs at a time**, so a fixed `lms-4b` default would fail with "model
not found" on a perfectly healthy gateway serving Ollama. An unrecognised engine is
an **error, not a fallback** — defaulting quietly reads as a broken gateway rather
than a stale `.env`.

| Override | Scope |
|:--|:--|
| `--model <alias>` | one run |
| `AI_GATEWAY_TEST_MODEL` | permanently, for this shell |

`openai` maps to nothing on purpose: `gpt-5.4-mini` has no vision, so
`2_openai_client/03_multimodal.py` cannot pass against it.

**On LMStudio the model must be loaded first** — `lms ps --json` is the truth, not
the LMStudio UI. A JIT load comes back at 8192 context with a 1 h TTL. Ollama loads
on demand and needs none of this.

```bash
lms load google/gemma-4-e4b --context-length 131072 --parallel 1 --gpu max
```

## Two binaries these folders need, and `uv` cannot install

| Folder | Needs | Install |
|:--|:--|:--|
| `5_claude_agent_sdk` | the `claude` CLI — the SDK spawns it | `npm install -g @anthropic-ai/claude-code` |
| `7_opencode_sdk` | the `opencode` binary | `curl -fsSL https://opencode.ai/install \| bash` |

Both scripts check PATH first and print the install line rather than failing inside
a library. `6_codex_sdk` needs nothing extra: `openai-codex` ships its own pinned
runtime.

## Verified

2026-09-04, `unsloth-4b`, all seven folders passing. Timings on this machine:

| Folder | Seconds, warm |
|:--|--:|
| `1_http_client` | 0.2 |
| `2_openai_client` | 4 |
| `3_langchain_langgraph` | 1.5 |
| `4_deepagents` | 15-60 — SEVEN scenarios |
| `5_claude_agent_sdk` | 40-120 — SEVEN scenarios, each spawning the `claude` CLI |
| `6_codex_sdk` | 20-50 — FOUR scenarios, Codex sends a large harness per turn |
| `7_opencode_sdk` | 15-60 — FIVE scenarios, each spawns an `opencode` server |

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

`2_openai_client` is four scripts in four processes; `5_claude_agent_sdk` spawns the
`claude` CLI once per demo. Every other row is one process and one or two calls.

Two extra requirements when `GATEWAY_ENGINE=unsloth`, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   every `unsloth-*` route 401s at call time.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. Unsloth holds **one model at a time**, so more than one
   gateway on `unsloth` will thrash it — run one suite at a time.

## What is NOT tested here

- **Embeddings.** Every `*-embed` alias needs a different route from the chat one
  these folders share.
- **Budgets and virtual keys.** [`../README.md`](../README.md) has the `curl`.
- **MCP**, in any folder.
- **That the same alias answers on 26000.** See the note above.
