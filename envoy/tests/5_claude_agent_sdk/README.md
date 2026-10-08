# `5_claude_agent_sdk` — the Anthropic surface, and a worked agent

The one folder here that does not speak the OpenAI protocol. The Claude Agent SDK
speaks the **Anthropic Messages API**, and this gateway serves it on
`/anthropic/v1/messages`. Point three environment variables at it and the SDK
never learns it is not talking to Anthropic.

It is also the folder to **copy when starting an agent project**. Eight scenarios
go from one HTTP call to an agent with tools, an MCP server in another process or
behind the gateway, a subagent and a skill — each one file, each asserting on structure rather than on
what the model happened to say.

```bash
uv run run_all.py                     # all eight
uv run run_all.py --model unsloth-gemma4-26b # the same eight on another alias
uv run 03_sdk_mcp.py                  # one scenario, directly
uv run run_all.py --verbose           # stream each scenario instead of capturing it
```

## The eight scenarios

| File | Feature | What a red row means |
|:--|:--|:--|
| `01_query.py` | `query()` — one shot | the Anthropic route is not answering |
| `02_session.py` | `ClaudeSDKClient` — a session | the conversation does not survive the round trip |
| `03_sdk_mcp.py` | an MCP server **in this process** | tool calls do not reach the model, or its reply carries no `tool_use` |
| `04_stdio_mcp.py` | an MCP server **in its own process** | `tool_use` / `tool_result` blocks are mangled across the process boundary |
| `05_subagent.py` | `AgentDefinition` — delegation | the sub-run's result does not join back into the parent |
| `06_skill.py` | a skill loaded from disk | the `Skill` tool is missing or its content never reaches the answer |
| `07_thinking.py` | a **reasoning** turn, and what the gateway does with it | the bug this folder was built around is back, or the gateway changed how it handles reasoning |
| `08_gateway_mcp.py` | an MCP server **behind the gateway**, through `/mcp` | the gateway did not offer the renamed tools, or did not forward the call |

Each one asserts on **an unguessable value** — `187.42`, `SN-4417-QX`, `Rufus`,
`ZEBRA-77` — that exists only in the tool, the subagent's prompt or `SKILL.md`. A
model that invents an answer instead of using the feature fails.

**`08` reaches its server only through the gateway.** It starts `mcp_server.py`
over HTTP on the port the gateway's config names — `MCP_SERVER_PORT` in
`settings.py` — and gives the agent nothing but `MCP_URL`. The tools arrive renamed,
`bench_hardware-bench_serial` on LiteLLM and `bench-hardware__bench_serial` on
Envoy, and `08` asserts the renamed name, so a tool that reached the agent any other
way fails.

## Copying this folder, and measuring it

**`settings.py` is the one file to edit when you copy this folder.** Everything else
is byte-identical to `../../../litellm/tests/5_claude_agent_sdk/` and reads it: the
base URL, the key, which alias carries the Anthropic protocol, and `CLI_ENVIRONMENT`
— what the `claude` CLI is started with. Two of those keep a local engine's prompt
cache working, `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=off` and
`CLAUDE_CODE_ATTRIBUTION_HEADER=0`: the last turn reused 22% (Gemma 4 26B) and 0%
(Qwen 3.8 27B) as shipped, 76–93% with both (2026-09-30). The thinking level goes as
`CLAUDE_CODE_EFFORT_LEVEL`, `medium` unless `AI_GATEWAY_REASONING_EFFORT` says
otherwise — unset, the CLI sends `xhigh`.

```bash
uv run run_benchmark.py --aliases lms-gemma4-26b --no-write   # one alias, table only
uv run run_benchmark.py                                        # every default alias
```

`run_benchmark.py` runs the three-turn task every folder runs, one row per model
request, and writes the numbers to `RESULTS.md`. The CLI also sends one request of
its own per session — the session title, carrying the whole first message — which
is not in the stream and so has no row; the notes in `RESULTS.md` give its tokens.
Through this gateway it is expensive: LMStudio wrote 2852–3927 tokens for the title and
the first request waited 38–52 s (2026-09-30). `settings.py` names the variable that
stops it and why it is not set by default.

## The pass-through alias, and why this folder refuses to run without one

**Every scenario calls `<alias>-anthropic`, not `<alias>`.** `anthropic_alias()` in
`settings.py` resolves it against `/v1/models` and **exits with instructions** if it is missing. That is
deliberate: there is no skip and no fallback, because a run on the plain alias
goes red at random rather than never.

The plain alias reaches an `OpenAI`-schema backend, so Envoy **translates**
Anthropic → OpenAI on the way in. That translation cannot carry an agent
conversation:

1. Envoy builds a `thinking` block into its reply out of the engine's
   `reasoning_content`.
2. Claude Code stores that reply and sends it back on the next turn.
3. The translator passes the block straight into the OpenAI body.
4. An OpenAI `content` part may only be `text` or `image_url`, so the **engine**
   rejects it: `400 messages.N.content.str: Input should be a valid string`.

**It is not Envoy's bug.** The identical error comes back from Unsloth on port
8888 with no gateway in the path (measured 2026-09-04). It was intermittent —
about one run in five — because the engine emits `reasoning_content` on some
replies and not others.

`<alias>-anthropic` points at an `Anthropic`-schema `AIServiceBackend`, so the
body reaches the engine **untranslated**. All three local engines serve
`POST /v1/messages` themselves — verified 2026-09-04, 200 from each — so there is
nothing to bridge. The rules are in `../../config/<engine>.yaml`, two per engine.

> `MAX_THINKING_TOKENS=0` used to be required here and no longer is. It existed
> to stop `400 thinking.type` from the same translator. On the pass-through path
> the engine accepts Claude Code's `thinking` field as sent.

## Reasoning reaches the caller here, and that is worth knowing

`07_thinking.py` asks for thinking explicitly and asserts the declaration
`THINKING_REACHES_CLIENT = True` in `settings.py`. **Envoy returns the engine's
reasoning whole**, because the `-anthropic` alias does not translate — the
engine's own `/v1/messages` reply reaches the caller as it was written. Measured
2026-09-04: unsloth 8 runs in 8 (377–1410 characters), one call each on LMStudio
(1033) and Ollama (891).

LiteLLM carries it too since 2026-09-05, after one line in its own config; its copy
of `settings.py` says which line and why.

## Four traps, all measured 2026-09-04

- **`tools=[]` and `allowed_tools=[]` are different levers.** `tools` is the
  VISIBILITY list; `allowed_tools` only auto-approves. Left wide, the CLI also
  offers `Read`, `Bash`, `SendMessage` and `ListAgents` — and a 4B model reaches
  for whichever it recognises. `05` failed two runs in three that way, reporting
  that no teammate called `bench-historian` existed.
- **A subagent must be `background=False`.** Left unset the parent can end its
  turn with "I will tell you when the agent finishes" — a reply that never
  contains the answer.
- **Assert on values, never on wording.** A model told `1204` writes `1,204`.
  `Transcript.says()` strips commas and Markdown bold for exactly that reason.
- **The skill comes from `bench_plugin/`, not `.claude/skills/`.** A local plugin
  is self-contained, so `setting_sources` stays empty and the CLI never walks up
  the tree to load a `CLAUDE.md` from above this folder. The run then behaves the
  same in every checkout.

## Layout

```text
5_claude_agent_sdk/
├── settings.py        THE ONLY FILE THAT KNOWS WHICH GATEWAY THIS IS
├── common.py          the options, the transcript and the runner every scenario shares
├── run_all.py         globs NN_*.py — a new scenario needs no edit
├── 01_query.py … 08_gateway_mcp.py
├── mcp_server.py      the MCP server: 04 spawns it, 08 runs it behind the gateway. NOT a test
├── run_benchmark.py   the benchmark task through this client → RESULTS.md
└── bench_plugin/      a local plugin carrying the skill 06 loads
```

**Every file but `settings.py` is byte-identical to
`../../../litellm/tests/5_claude_agent_sdk/`.** Porting the folder to a third
gateway is a copy plus one new `settings.py`.

## Requirements

The SDK is a wrapper over the `claude` CLI, not an HTTP client. `uv run` installs
the Python half; the CLI half comes from npm and must already be on PATH:

```bash
npm install -g @anthropic-ai/claude-code
```

`common.py` checks for it and says so rather than failing inside the SDK.
