# tests — seven ways to call the Envoy AI Gateway

Seven folders, each a working program against **this project's gateway on 26000**.
They are ordered by distance from the wire: raw HTTP first, then OpenAI's own
client, then five agent frameworks.

| Folder | Reaches the gateway through | Proves |
|:--|:--|:--|
| [`1_http_client`](1_http_client/README.md) | `urllib` — **no dependencies at all** | the request every other folder wraps, plain and streaming |
| [`2_openai_client`](2_openai_client/README.md) | `openai` | four scenarios: chat, tools, an image, and this gateway's calling contract |
| [`3_langchain_langgraph`](3_langchain_langgraph/README.md) | `ChatOpenAI(base_url=…)` | LangChain's prebuilt agent, and the same ReAct loop built by hand in LangGraph |
| [`4_deepagents`](4_deepagents/README.md) | the same `ChatOpenAI` | a deep agent — seven scenarios: query, todos, filesystem, tools, mcp, subagent, skill |
| [`5_claude_agent_sdk`](5_claude_agent_sdk/README.md) | `ANTHROPIC_BASE_URL` → `/anthropic/v1/messages` | **the Anthropic surface**, and the worked agent: query, session, in-process MCP, stdio MCP, subagent, skill, thinking |
| [`6_codex_sdk`](6_codex_sdk/README.md) | a `model_providers` override → `/v1/responses` | **the Responses surface** — the only protocol Codex speaks |
| [`7_opencode_sdk`](7_opencode_sdk/README.md) | an `@ai-sdk/openai-compatible` provider | OpenCode over its HTTP server API — query, session, agent, MCP, structured output |

**All seven run here**, and all seven run on `../../litellm` too.

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

`run_all.py` probes **`26000/v1/models`, not `26064/health`**. The admin server
answers `OK` several seconds before Envoy's listener accepts a connection, so
probing it races the thing being tested and the first folder then fails with a
connection reset (measured 2026-09-04).

## Seven folders, seven projects

Each folder carries its **own** `pyproject.toml` and its own `.venv`. That is
deliberate: the dependency sets have nothing in common — `1_http_client` has none
at all, and DeepAgents, the Codex runtime and the Claude Agent SDK have no reason
to share a resolver. `uv run --directory` builds whichever venv is missing, so a
fresh clone needs no `uv sync` first.

**What they share is [`gateway.py`](gateway.py)**, one level up: the base URL, the
key and the alias. Three facts written down seven times would be six places to
forget when `GATEWAY_ENGINE` changes. It imports **nothing but the standard
library**, which is what lets it import inside `1_http_client`'s empty venv, and it
reads only this project's own files — nothing here looks at `../../litellm`.

Adding a folder is two edits: write it, and add its name to `FOLDERS` in
`run_all.py`.

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

## Which alias gets called — and the one thing to check first

`gateway.py` reads `GATEWAY_ENGINE` from `../.env` and picks that engine's small
chat route: `lms-4b`, `unsloth-4b`, `ollama-4b` or `openrouter-26b`.

> **Check `../.env` matches the running container.** Compose reads the **shell**
> before the file, so a gateway started from a shell carrying `GATEWAY_ENGINE`
> serves that engine while this suite, run from a different shell, reads the file.
> When the two disagree every folder 404s from a perfectly healthy gateway, and
> the `claude` CLI reports it as `unrecognized_model` rather than as a 404 — which
> is how it was found on 2026-09-04, when this project had no `.env` at all.
> `curl localhost:26000/v1/models` says which aliases are really being served.
> Override without editing anything:
>
> ```bash
> AI_GATEWAY_TEST_MODEL=unsloth-4b uv run run_all.py
> ```

**One engine runs at a time**, so a fixed default would 404 on a healthy gateway
serving another engine. An unrecognised engine is an **error, not a fallback**.

| Override | Scope |
|:--|:--|
| `--model <alias>` | one run |
| `AI_GATEWAY_TEST_MODEL` | permanently, for this shell |

## `max_tokens` is not optional here

`BODY_EXTRAS` in `gateway.py` carries `{"max_tokens": 2048}`, and every folder
sends it. An `AIGatewayRoute` rule carries a request **timeout** but no token
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

## What is NOT tested here

- **Embeddings.** The `*-embed` aliases route fine, but the chat client these
  folders share does not drive `/v1/embeddings`.
- **`/mcp`.** The MCP gateway needs `--mcp-config`, which `../compose.yml` does not
  pass. Nothing is wired up, so there is nothing to test yet.
- **`/metrics` on 26064.** Prometheus output, untested.
- **The two PAID engines.** `config/openrouter.yaml` and `config/openai.yaml` parse
  and register their aliases, but no call has been made through either — that would
  bill a real account.
- **`openrouter-free`.** Absent here by design: no `extra_body`, so no provider pin.
- **That the same alias answers on 24000.** See the note above.

## Verified

2026-09-04, `unsloth-4b`, all seven folders passing. Timings on this machine:

| Folder | Seconds, warm |
|:--|--:|
| `1_http_client` | 0.2 |
| `2_openai_client` | 6 |
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

Run with `AI_GATEWAY_TEST_MODEL=unsloth-4b`, because this project carries no `.env`
— see the call-out above.

Two extra requirements when the engine is `unsloth`, and both fail quietly:

1. **`UNSLOTH_API_KEY` must be in the shell** that ran `podman compose up -d`, or
   `${UNSLOTH_API_KEY}` substitutes empty and every `unsloth-*` call 401s.
2. **`Settings → API → Model auto-switch` must be on**, or the first call returns
   `400 No model loaded`. Unsloth holds **one model at a time**, so more than one
   gateway on `unsloth` will thrash it — run one suite at a time.
