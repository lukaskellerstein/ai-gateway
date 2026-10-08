# `4_deepagents` — a deep agent, and the harness it brings with it

DeepAgents is LangGraph with a harness bolted on. Reaching the gateway is the
same one line as folder 3 — `create_deep_agent(model=ChatOpenAI(base_url=…))` —
so this folder speaks the **ordinary OpenAI protocol**, with no Anthropic route
and no special alias.

What makes it a harder test than folder 3 is the harness. Your tools are ADDED to
a suite the agent already has, so the model must choose among a dozen schemas
rather than one or two. A 4B model that sails through folder 3 can lose the plot
here — and when it does, that is a fact about the model, not the gateway.

```bash
uv run run_all.py                     # all eight
uv run run_all.py --model unsloth-gemma4-26b # the same eight on another alias
uv run 05_mcp.py                      # one scenario, directly
uv run run_all.py --verbose           # stream each scenario instead of capturing it
uv run run_benchmark.py               # the shared benchmark task; writes RESULTS.md
```

## Copying this folder into another project

**`settings.py` is the one file to edit.** It names the gateway — URL, key, alias,
health probe — and the two settings every request carries: the thinking level
(`reasoning_effort`, `medium` unless `AI_GATEWAY_REASONING_EFFORT` says otherwise)
and, on a gateway that stores none, a token ceiling. Every other file is
byte-identical between `litellm/` and `envoy/`, and none imports anything outside
this folder.

`run_benchmark.py` runs the task every folder shares (its shared part, never edited
here): one deep agent, one thread, three turns, reading a real `order.json`
with its own `read_file`. A LangChain callback on the model records every request
the harness makes — first token, decode speed, prompt, cached and thinking tokens —
and `RESULTS.md` holds the numbers, with the settings that produced them.

## The eight scenarios

| File | Feature | What a red row means |
|:--|:--|:--|
| `01_query.py` | one shot, no tools added | the harness will not start, or the gateway is not answering |
| `02_todos.py` | the planner, via `TodoListMiddleware` | list-shaped tool arguments are being mangled |
| `03_filesystem.py` | the virtual filesystem | a two-step chain loses the first tool's result |
| `04_tools.py` | two custom `@tool` functions | the model cannot pick the right tool out of a dozen |
| `05_mcp.py` | an MCP server in its **own process** | `tool_calls` are mangled across a process boundary |
| `06_subagent.py` | `subagents=` and the `task` tool | a sub-run's result does not join back into the parent |
| `07_skill.py` | a skill read from `skills/` | the skill is listed but its body never reaches the answer |
| `08_gateway_mcp.py` | the same MCP server **behind the gateway**, through `/mcp` | the gateway did not offer the renamed tools, or did not forward the call |

Each asserts on **an unguessable value** — `187.42`, `SN-4417-QX`, `Rufus`,
`ZEBRA-77` — that exists only in a tool, a subagent's prompt or `SKILL.md`. A
model that invents an answer instead of using the feature fails.

**`08` reaches its server only through the gateway.** It starts `mcp_server.py`
over HTTP on the port the gateway's config names — `MCP_SERVER_PORT` in
`settings.py` — and gives the agent nothing but `MCP_URL`. The tools arrive renamed,
`bench_hardware-bench_serial` on LiteLLM and `bench-hardware__bench_serial` on
Envoy, and `08` asserts the renamed name, so a tool that reached the agent any other
way fails.

## Four things measured here, all 2026-09-04

- **`write_todos` is not in the free harness, and that is a PROFILE decision.** On
  deepagents 0.7.13 — the newest release — the default suite is exactly `ls`,
  `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `delete`, `execute` and
  `task`. Two shipped harness profiles (`_openai_codex`,
  `_nvidia_nemotron_3_ultra`) add `TodoListMiddleware`; the three Anthropic
  profiles and the default do not. A local gemma matches no profile, so `02` adds
  the middleware itself. Without it the model writes its plan to a **file** —
  request satisfied, planner never touched, green row proving nothing.
- **Skills are read through the BACKEND.** `skills=["/skills/"]` is a path inside
  the agent's filesystem, so it needs `FilesystemBackend(root_dir=…)` to mean this
  folder. With the default in-state backend there is nothing to read and the skill
  is simply never found. `virtual_mode=True` keeps every other file operation in
  state, so nothing here touches your disk.
- **MCP tools are async.** `langchain-mcp-adapters` returns coroutine tools, so an
  agent holding them must be driven with `astream`; `stream` raises rather than
  degrading. That is why `common.py` has both `drive` and `adrive`.
- **`mcp` here is 1.x because the ADAPTER caps it, not because we pinned it.**
  `langchain-mcp-adapters` 0.3.2 — the newest release — declares
  `mcp>=1.24.0,<2.0.0`, so upstream has not adopted mcp 2 yet. **The wire is
  version-agnostic**: this folder's mcp 1.29.1 client discovered and called folder
  5's mcp 2.1.1 server across two venvs without complaint. `mcp_server.py` exists
  in two dialects only so each folder stays copyable on its own — each spawns the
  server with its own `sys.executable`.

## Layout

```text
4_deepagents/
├── settings.py          THE ONE FILE TO EDIT: gateway, key, alias, level, ceiling
├── common.py            the model builder, the transcript, the runner
├── run_all.py           globs NN_*.py — a new scenario needs no edit
├── 01_query.py … 08_gateway_mcp.py
├── mcp_server.py        the MCP server: 05 spawns it, 08 runs it behind the gateway. NOT a test
├── skills/              the skill 07 reads through the backend
├── run_benchmark.py     the shared task through this client. NOT a test
└── RESULTS.md           written by run_benchmark.py
```

**Every `.py` file but `settings.py` is byte-identical to
`../../../litellm/tests/4_deepagents/`.** Both gateways speak the same OpenAI
protocol here, so `settings.py` differs only where the gateways do: the port, the
key, the health probe and the ceiling.
