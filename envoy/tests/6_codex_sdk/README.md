# `6_codex_sdk` — the Responses surface

**Codex speaks the Responses API and nothing else.** `WireApi` in the Codex
source has exactly one variant, `Responses`; the `chat` variant older guides
configure was removed. So a gateway without `POST /v1/responses` cannot host
Codex at all, however well it serves chat completions. This one serves it at
`26000/v1/responses`.

```bash
uv run run_all.py                     # all four
uv run run_all.py --model unsloth-gemma4-26b # the same four on another alias
uv run 04_mcp.py                      # one scenario, directly
```

## The four scenarios

| File | Feature | What a red row means |
|:--|:--|:--|
| `01_query.py` | one shot | `/v1/responses` is not answering |
| `02_session.py` | a `Thread` that remembers | the conversation does not survive the round trip |
| `03_structured.py` | `output_schema` | the gateway drops structured output — the reply is prose, not JSON |
| `04_mcp.py` | an MCP server over stdio | Codex could not start the server or read its config — or, on `openrouter-gemma4-26b` only, the model did not call the tool |

## ⚠ The MCP scenario asserts the tool call on ONE alias, and the wiring on the rest

`04_mcp.py` proves Codex spawns the server, completes the handshake and asks
for its tools — on every alias. It asserts that the model **called** the tool
on `openrouter-gemma4-26b` only. Two things stood between the model and the tool:
**one is fixed here, one is not.**

```text
--> initialize            clientInfo "codex-mcp-client"
<-- capabilities: tools…
--> notifications/initialized
--> tools/list
<-- tools: [bench_serial …]   with a full inputSchema
```

### Fixed — the approval

**[openai/codex#24135](https://github.com/openai/codex/issues/24135)** — a
headless run has nobody to approve an MCP call. `approval_policy="never"`,
`tools_require_approval`, `trusted_mcp_servers` and a per-server
`approval_policy` are all silently ignored: on 2026-09-04 a frontier model called
the tool correctly and Codex answered *"This action was rejected due to
unacceptable risk."* **The key that works is per server**, and `04_mcp.py` sets
it:

```toml
[mcp_servers.hardware]
default_tools_approval_mode = "approve"   # auto | prompt | writes | approve
```

Measured 2026-09-23 — codex 0.155.1, `openrouter-gemma4-26b`, approval policy `never`,
read-only sandbox, an empty `CODEX_HOME`, **the same on both gateways**:

```text
items=userMessage,mcpToolCall,agentMessage   status=completed
tool really called: True        <- the SERVER's marker, not the answer
```

The issue is still open upstream, because it asks for a CLI flag. **Not
measured**: the same run on 0.155.1 *without* the key — it bills a real account,
and the 2026-09-04 refusal is the "before". **Guarded by** `04_mcp.py` on
`openrouter-gemma4-26b`: delete the key and that run goes red. It is a paid run, so
`run_all.py` on a free alias does not prove the key is still there.

### Not fixed — the shape Codex sends

> **[openai/codex#19871](https://github.com/openai/codex/issues/19871)** — *"MCP
> tool invocation regressed for custom/local providers (Ollama Responses API) in
> v0.117.0+"*. Still open on 2026-09-23.

From 0.117.0 Codex sends a whole MCP server as **one tool of type `namespace`**:

```json
{"type": "namespace", "name": "mcp__hardware",
 "tools": [{"type": "function", "name": "bench_serial", "…": "…"}]}
```

The OpenRouter route understands that shape. **No local engine does**, so the
model never sees `bench_serial` as something it can call — `unsloth-gemma4-e4b` says so
in as many words: *"I don't have a tool named `bench_serial` available."* It
shells out, or reads the serial number out of `mcp_server.py`.

**The cause is measured, not inferred.** One `/v1/responses` call per shape, no
Codex in the path, `unsloth-gemma4-26b`, 2026-09-21, the same on 24000 and 26000:

| The same tool, sent as | What came back |
|:--|:--|
| `"type": "namespace"` — what Codex sends | a plain message, **no call** |
| a flat `"function"` | `function_call {"appliance": "atlas"}` |

So the gateway and the engine are fine, and **nothing in Codex turns the shape
off**:

| Tried | Result |
|:--|:--|
| codex 0.155.1, the newest on PyPI, both gateways, `unsloth-gemma4-e4b` and `unsloth-gemma4-26b` | tool never ran |
| `model_providers.<id>` in 0.155.1 and in 0.156.0-alpha.16 | no capability key for it |
| `features.non_prefixed_mcp_tool_names = true` | renames the namespace to `hardware`; still a `namespace`, tool never ran |
| an empty `CODEX_HOME`, which cuts the request to 13 tools | tool never ran |
| codex-cli **0.116.0**, measured 2026-09-04 | **the tool ran** — it sent flat tools |

Upstream closed both fixes unmerged —
[#28271](https://github.com/openai/codex/pull/28271) and
[#29602](https://github.com/openai/codex/pull/29602). The issue that tracks the
real one is [openai/codex#26234](https://github.com/openai/codex/issues/26234).

**The fixes that "work" are proxies**: they flatten the tools on the way out and
restore the names on the way back. That is a shim between Codex and the gateway,
and this repo proves a gap rather than shimming it.

**Pinning 0.116.0 is not an option.** PyPI has no `openai-codex` 0.116.x, so the
Python SDK cannot drive that runtime.

**NEXT TIME**: open #19871 and #26234. If either is closed, run
`uv run 04_mcp.py` on a **local** alias — it prints `tool really called:` on
every run. When that says `True` there too, delete this section and add the
alias to `CALLS_THE_TOOL`, or drop the set and assert for everyone.

## Two things that are not obvious

- **An empty `CODEX_HOME` is load-bearing.** Codex reads
  `$CODEX_HOME/config.toml` — `~/.codex` by default — into every run, so a
  developer with plugins installed hands the model their whole toolbox: on this
  machine **~108 tools** on 2026-09-21, and the file's hooks then ran inside
  every test. `mcp_servers={}` plus `plugins={}` in the overrides used to be the
  guard and no longer was — that is exactly what leaked. `common.py` now gives
  the runtime a fresh temporary directory, which cuts the request to the **13**
  tools the harness itself needs (measured 2026-09-23), and `features.plugins`
  is off because an empty home otherwise clones the plugin marketplace in the
  background. This is the Codex equivalent of `setting_sources=[]` in folder 5,
  and without it the run depends on who is at the keyboard.
- **`mcp_server.py` writes marker files**, and `04` asserts on them rather than
  on the answer. That is not belt-and-braces: a model with shell access read the
  serial number straight out of the server's source and reported it correctly
  without calling anything (measured 2026-09-04). An answer-only assertion would
  have passed.

## Layout

```text
6_codex_sdk/
├── common.py          the provider config, the thread defaults, the runner
├── run_all.py         globs NN_*.py
├── 01_query.py … 04_mcp.py
└── mcp_server.py      the MCP server 04 spawns. NOT a test
```

**`01`–`04`, `run_all.py` and `mcp_server.py` are byte-identical to
`../../../litellm/tests/6_codex_sdk/`.** Only `common.py` differs, in the health URL `run_all.py` probes.
