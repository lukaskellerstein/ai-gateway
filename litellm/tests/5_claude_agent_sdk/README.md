# `5_claude_agent_sdk` — the Anthropic surface, and a worked agent

> [!warning]
> **KNOWN UPSTREAM BUG — LiteLLM does not return the model's reasoning on this
> route.** All seven scenarios PASS; what is missing is the `thinking` block.
> LiteLLM's OpenAI routes carry reasoning fine (1606 characters of
> `reasoning_content`, measured 2026-09-04) — its Anthropic `/v1/messages`
> adapter, the only route the Claude Agent SDK speaks, returns a text block and
> nothing else.
>
> - [BerriAI/litellm#29518](https://github.com/BerriAI/litellm/issues/29518) — the
>   adapter reads only `thinking_blocks` and never falls back to `reasoning_content`
> - [BerriAI/litellm#27946](https://github.com/BerriAI/litellm/issues/27946) — the
>   same conversion in the other direction
>
> **Both open on 2026-09-04.** Tried and did not help: `supports_reasoning: true`,
> `merge_reasoning_content_in_choices: true`, and a bigger `max_tokens` /
> `budget_tokens`. **Not a misconfiguration here.**
>
> **TO RE-CHECK**: open the two issues, then run `uv run 07_thinking.py`. It prints
> the warning on every run. If the fix has landed the row goes RED, and the repair
> is one line — flip `THINKING_REACHES_CLIENT` to `True` in `common.py` and delete
> this box. Use **Envoy** meanwhile if an agent needs to see reasoning.

The one folder here that does not speak the OpenAI protocol. The Claude Agent SDK
speaks the **Anthropic Messages API**, and LiteLLM serves `POST /v1/messages`
beside its OpenAI routes. Point three environment variables at it and the SDK
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
| `01_query.py` | `query()` — one shot | `/v1/messages` is not answering |
| `02_session.py` | `ClaudeSDKClient` — a session | the conversation does not survive the round trip |
| `03_sdk_mcp.py` | an MCP server **in this process** | tool calls do not reach the model, or its reply carries no `tool_use` |
| `04_stdio_mcp.py` | an MCP server **in its own process** | `tool_use` / `tool_result` blocks are mangled across the process boundary |
| `05_subagent.py` | `AgentDefinition` — delegation | the sub-run's result does not join back into the parent |
| `06_skill.py` | a skill loaded from disk | the `Skill` tool is missing or its content never reaches the answer |
| `07_thinking.py` | a **reasoning** turn, and what the gateway does with it | the bug this folder was built around is back, or the gateway changed how it handles reasoning |

Each one asserts on **an unguessable value** — `187.42`, `SN-4417-QX`, `Rufus`,
`ZEBRA-77` — that exists only in the tool, the subagent's prompt or `SKILL.md`. A
model that invents an answer instead of using the feature fails.

## The plain alias is enough here, and that is the difference worth knowing

`common.py` calls the alias as given. **Nothing is worked around**, because
LiteLLM carries an agent conversation on the ordinary route: a multi-turn request
carrying a `thinking` block returned 200 on plain `unsloth-4b` (verified
2026-09-04).

Envoy cannot. It translates Anthropic → OpenAI onto the engine's OpenAI schema
and passes the reply's own `thinking` blocks into the OpenAI body, where a
`content` part may only be `text` or `image_url` — so the engine answers
`400 messages.N.content.str` on turn two. Its folder therefore resolves a second,
`Anthropic`-schema alias called `<alias>-anthropic` and refuses to run without
one. See `../../../envoy/tests/5_claude_agent_sdk/README.md`.

**That is the strongest argument this repo has for LiteLLM**, and it costs Envoy
two extra rules per engine rather than a feature.

## Reasoning works here — except on the one route this folder uses

**LiteLLM carries reasoning fine on its OpenAI routes.** Measured 2026-09-04, same
engine and same prompt:

| Route | Reasoning returned |
|:--|:--|
| `POST /v1/chat/completions` | **1606 characters** of `reasoning_content` |
| `POST /v1/messages` | a text block and nothing else |

So folders 1, 2, 3, 4 and 7 see the model's reasoning. **This folder is the only
one that cannot**, because the Claude Agent SDK speaks `/v1/messages` and nothing
else. `07_thinking.py` asks for thinking explicitly and asserts the declaration
`THINKING_REACHES_CLIENT = False` in `common.py`.

**It is a known upstream bug, not a setting anyone here got wrong.** The adapter
in `litellm/llms/anthropic/experimental_pass_through/adapters/transformation.py`
only looks for `thinking_blocks` and never falls back to `reasoning_content` —
the field an OpenAI-compatible backend actually fills in:

- [BerriAI/litellm#29518](https://github.com/BerriAI/litellm/issues/29518)
- [BerriAI/litellm#27946](https://github.com/BerriAI/litellm/issues/27946)

Both were open on 2026-09-04. **Three things were tried and none works**:
`supports_reasoning: true` in `model_info`, `merge_reasoning_content_in_choices:
true` in `litellm_params`, and a generous ceiling — `max_tokens: 4096` with
`budget_tokens: 2048` still returns a bare text block.

Envoy's `-anthropic` alias does not translate, so it carries the reasoning whole.
**That is the one thing it does better than this gateway on this route**, and 07
goes red the day either of them changes.

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
`../../../envoy/tests/5_claude_agent_sdk/`.** Every difference between the two
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
