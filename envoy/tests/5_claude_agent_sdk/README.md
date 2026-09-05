# `5_claude_agent_sdk` — the Anthropic surface, and a worked agent

The one folder here that does not speak the OpenAI protocol. The Claude Agent SDK
speaks the **Anthropic Messages API**, and this gateway serves it on
`/anthropic/v1/messages`. Point three environment variables at it and the SDK
never learns it is not talking to Anthropic.

It is also the folder to **copy when starting an agent project**. Seven scenarios
go from one HTTP call to an agent with tools, an MCP server in another process, a
subagent and a skill — each one file, each asserting on structure rather than on
what the model happened to say.

```bash
uv run run_all.py                     # all six
uv run run_all.py --model unsloth-26b # the same six on another alias
uv run 03_sdk_mcp.py                  # one scenario, directly
uv run run_all.py --verbose           # stream each scenario instead of capturing it
```

## The seven scenarios

| File | Feature | What a red row means |
|:--|:--|:--|
| `01_query.py` | `query()` — one shot | the Anthropic route is not answering |
| `02_session.py` | `ClaudeSDKClient` — a session | the conversation does not survive the round trip |
| `03_sdk_mcp.py` | an MCP server **in this process** | tool calls do not reach the model, or its reply carries no `tool_use` |
| `04_stdio_mcp.py` | an MCP server **in its own process** | `tool_use` / `tool_result` blocks are mangled across the process boundary |
| `05_subagent.py` | `AgentDefinition` — delegation | the sub-run's result does not join back into the parent |
| `06_skill.py` | a skill loaded from disk | the `Skill` tool is missing or its content never reaches the answer |
| `07_thinking.py` | a **reasoning** turn, and what the gateway does with it | the bug this folder was built around is back, or the gateway changed how it handles reasoning |

Each one asserts on **an unguessable value** — `187.42`, `SN-4417-QX`, `Rufus`,
`ZEBRA-77` — that exists only in the tool, the subagent's prompt or `SKILL.md`. A
model that invents an answer instead of using the feature fails.

## The pass-through alias, and why this folder refuses to run without one

**Every scenario calls `<alias>-anthropic`, not `<alias>`.** `common.py` resolves
it against `/v1/models` and **exits with instructions** if it is missing. That is
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
`THINKING_REACHES_CLIENT = True` in `common.py`. **Envoy returns the engine's
reasoning whole**, because the `-anthropic` alias does not translate — the
engine's own `/v1/messages` reply reaches the caller as it was written. Measured
2026-09-04: unsloth 8 runs in 8 (377–1410 characters), one call each on LMStudio
(1033) and Ollama (891).

**LiteLLM does not, on this route.** Its OpenAI routes carry reasoning fine —
`/v1/chat/completions` gave 1606 characters of `reasoning_content` for the same
engine and prompt — but its Anthropic `/v1/messages` adapter returns a text block
and nothing else. That is a known upstream bug
([#29518](https://github.com/BerriAI/litellm/issues/29518),
[#27946](https://github.com/BerriAI/litellm/issues/27946), both open
2026-09-04), and `/v1/messages` is the only route the Claude Agent SDK speaks. So
for a reasoning agent, this gateway is the one that carries it.

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
├── common.py          THE ONLY FILE THAT KNOWS WHICH GATEWAY THIS IS
├── run_all.py         globs NN_*.py — a new scenario needs no edit
├── 01_query.py … 07_thinking.py
├── mcp_server.py      the external MCP server 04 spawns. NOT a test
└── bench_plugin/      a local plugin carrying the skill 06 loads
```

**`01`–`06`, `run_all.py` and `mcp_server.py` are byte-identical to
`../../../litellm/tests/5_claude_agent_sdk/`.** Every difference between the two
gateways lives in `common.py`, which is what makes these six files worth copying
into another project. Porting them to a third gateway is a copy plus one new
`common.py`.

## Requirements

The SDK is a wrapper over the `claude` CLI, not an HTTP client. `uv run` installs
the Python half; the CLI half comes from npm and must already be on PATH:

```bash
npm install -g @anthropic-ai/claude-code
```

`common.py` checks for it and says so rather than failing inside the SDK.
