# `5_claude_agent_sdk` — the Anthropic surface, and a worked agent

The one folder here that does not speak the OpenAI protocol. The Claude Agent SDK
speaks the **Anthropic Messages API**, and LiteLLM serves `POST /v1/messages`
beside its OpenAI routes. Point three environment variables at it and the SDK
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
| `01_query.py` | `query()` — one shot | `/v1/messages` is not answering |
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
is byte-identical to `../../../envoy/tests/5_claude_agent_sdk/` and reads it: the
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

## The plain alias is enough here, and that is the difference worth knowing

`anthropic_alias()` in `settings.py` returns the alias as given. **Nothing is
worked around**, because LiteLLM carries an agent conversation on the ordinary
route: a multi-turn request carrying a `thinking` block returned 200 on plain
`unsloth-gemma4-e4b` (verified 2026-09-04).

Envoy cannot. It translates Anthropic → OpenAI onto the engine's OpenAI schema
and passes the reply's own `thinking` blocks into the OpenAI body, where a
`content` part may only be `text` or `image_url` — so the engine answers
`400 messages.N.content.str` on turn two. Its folder therefore resolves a second,
`Anthropic`-schema alias called `<alias>-anthropic` and refuses to run without
one. See `../../../envoy/tests/5_claude_agent_sdk/README.md`.

**That is the strongest argument this repo has for LiteLLM**, and it costs Envoy
two extra rules per engine rather than a feature.

## Reasoning reaches the caller here, after one config line

`07_thinking.py` asks for thinking explicitly and asserts the declaration
`THINKING_REACHES_CLIENT = True` in `settings.py`. It was not always true:
`/v1/messages` picks its upstream route by provider, and every `openai/` backend —
`unsloth-*` and `ollama-*` — went through a Responses API bridge that drops
`reasoning_content`. `use_chat_completions_url_for_anthropic_messages: true` in
`../../config/settings.yaml` forces the chat-completions path, where the adapter
falls back to `reasoning_content`: 6 streaming runs out of 6 carried thinking on
`unsloth-gemma4-e4b`, against 0 out of 5 before (2026-09-05). `settings.py` has the
whole story, including why the two closed upstream issues were not the cure.

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
`../../../envoy/tests/5_claude_agent_sdk/`.** Porting the folder to a third
gateway is a copy plus one new `settings.py`.

## Requirements

The SDK is a wrapper over the `claude` CLI, not an HTTP client. `uv run` installs
the Python half; the CLI half comes from npm and must already be on PATH:

```bash
npm install -g @anthropic-ai/claude-code
```

`common.py` checks for it and says so rather than failing inside the SDK.
