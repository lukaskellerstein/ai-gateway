# `6_codex_sdk` — the Responses surface

**Codex speaks the Responses API and nothing else.** `WireApi` in the Codex
source has exactly one variant, `Responses`; the `chat` variant older guides
configure was removed. So a gateway without `POST /v1/responses` cannot host
Codex at all, however well it serves chat completions. This one serves it at
`24000/v1/responses`.

```bash
uv run run_all.py                     # all four
uv run run_all.py --model unsloth-26b # the same four on another alias
uv run 04_mcp.py                      # one scenario, directly
```

## The four scenarios

| File | Feature | What a red row means |
|:--|:--|:--|
| `01_query.py` | one shot | `/v1/responses` is not answering |
| `02_session.py` | a `Thread` that remembers | the conversation does not survive the round trip |
| `03_structured.py` | `output_schema` | the gateway drops structured output — the reply is prose, not JSON |
| `04_mcp.py` | an MCP server over stdio | Codex could not start the server or read its config |

## ⚠ The MCP scenario asserts the wiring, not the tool call — and here is why

`04_mcp.py` proves Codex spawns the server, completes the handshake and asks
for its tools. It does **not** assert that the model calls the tool, because of
an open upstream bug:

> **[openai/codex#19871](https://github.com/openai/codex/issues/19871)** — *"MCP
> tool invocation regressed for custom/local providers (Ollama Responses API) in
> v0.117.0+"*. The model answers without making MCP calls even when the prompt
> requires them. Last known good runtime: **0.116.0**.

Measured here on 2026-09-04, same server, same prompt, same `unsloth-4b`:

| Codex runtime | Tool actually ran |
|:--|:--|
| **0.116.0** | **yes** — `The serial number ... is SN-4417-QX` |
| 0.147.0 (the newest, and ours) | no — the model shells out instead |

The wire proves the wiring is right:

```text
--> initialize            clientInfo "codex-mcp-client"
<-- capabilities: tools…
--> notifications/initialized
--> tools/list
<-- tools: [bench_serial …]   with a full inputSchema
```

**A second open bug sits behind it**, and matters the moment the first is fixed:
**[openai/codex#24135](https://github.com/openai/codex/issues/24135)** — there is
no supported way to approve MCP tool calls non-interactively.
`approval_policy="never"`, `tools_require_approval`, `trusted_mcp_servers` and
per-server `approval_policy` are all silently ignored. A frontier model called
the tool correctly through this gateway and Codex answered *"This action was
rejected due to unacceptable risk."*

**We stay on the newest release deliberately.** Pinning 0.116.0 would cost the
Python SDK (its app-server protocol predates it — it rejects the `auto_review`
reviewer and omits `thread.sessionId`), and Envoy returns 400 for its payload,
the class of bug in
[envoyproxy/ai-gateway#2586](https://github.com/envoyproxy/ai-gateway/issues/2586).

**NEXT TIME**: open both issues. If they are closed, run `uv run 04_mcp.py` — it
prints `tool really called:` on every run. When that says `True`, delete this
section and turn the check into an assertion.

## Two things that are not obvious

- **`mcp_servers={}` and `plugins={}` are load-bearing.** Codex merges
  `~/.codex/config.toml` into every run, so a developer with plugins installed
  hands the model their whole toolbox — on this machine **~80 tools**, a full
  Playwright API and Codex Apps included. Clearing both cuts it to 17. This is
  the Codex equivalent of `setting_sources=[]` in folder 5, and without it the
  run depends on who is at the keyboard.
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
`../../../envoy/tests/6_codex_sdk/`.** Only `common.py` differs, in the health URL `run_all.py` probes.
