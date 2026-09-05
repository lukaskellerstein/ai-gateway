# `7_opencode_sdk` — OpenCode over its HTTP server API

**OpenCode has no Python SDK.** What it has is a documented HTTP server API: you
start `opencode serve` and everything after that is ordinary REST. So the "SDK"
here is sixty lines of `httpx` in `common.py`, which is the honest shape of the
integration and reads better than a wrapper would.

The gateway is selected with a **custom provider, declared inline**. OpenCode
resolves providers through the Vercel AI SDK, and `@ai-sdk/openai-compatible` is
the driver for anything speaking the OpenAI protocol. The whole configuration is
a dict handed to the server through `OPENCODE_CONFIG_CONTENT`, so nothing is
written to your `~/.config/opencode` and a run cannot disturb your own setup.

```bash
uv run run_all.py                     # all five
uv run run_all.py --model unsloth-26b # the same five on another alias
uv run 04_mcp.py                      # one scenario, directly
```

## The five scenarios

| File | Feature | What a red row means |
|:--|:--|:--|
| `01_query.py` | one shot | the server will not start, or the provider does not resolve |
| `02_session.py` | a session that remembers | the conversation does not survive the round trip |
| `03_agent.py` | a named agent from config | the `agent` config never reached the server, or its prompt did not apply |
| `04_mcp.py` | an MCP server added at **runtime** | `POST /mcp` failed, or the model answered without the tool |
| `05_structured.py` | `format` with a JSON schema | the gateway drops structured output |

Each asserts on **an unguessable value** — `Rufus`, `SN-4417-QX` — or on parsed
JSON, never on the model's wording.

## Four things worth copying

- **`POST /mcp` adds a server to a LIVE OpenCode.** Nothing is written to a
  config file; the server is spawned as a child process and spoken to over
  stdio. `GET /mcp` then reports `{"hardware": {"status": "connected"}}`.
- **`tools={"bash": False, "read": False, …}` per prompt is the lever that makes
  the MCP scenario deterministic.** With the shell available a small model
  answers a tool question by shelling out. Switching the built-ins off for that
  one prompt leaves the MCP tool as the only way to answer. **Codex has no
  equivalent, which is why its MCP scenario cannot assert the tool call** — see
  `../6_codex_sdk/README.md`.
- **Structured output is NOT in the text parts.** OpenCode validates the reply
  and puts the parsed object in `info.structured`; the text may hold a plain
  sentence. Reading the text and calling `json.loads` on it fails even when
  everything worked. A schema failure appears as `info.error` named
  `StructuredOutputError`.
- **`mcp_server.py` writes marker files, and `04` asserts on them.** A model with
  shell access can read the serial number out of the server's source and report
  it correctly without calling anything — measured 2026-09-04. An answer-only
  assertion would have passed.

## Requirements

The `opencode` binary must be on PATH — `common.py` checks for it and says so
rather than failing inside an HTTP call. Install it from <https://opencode.ai>.

## Layout

```text
7_opencode_sdk/
├── common.py          the server lifecycle, the config, the runner
├── run_all.py         globs NN_*.py
├── 01_query.py … 05_structured.py
└── mcp_server.py      the MCP server 04 spawns. NOT a test
```

**`01`–`05`, `run_all.py` and `mcp_server.py` are byte-identical to
`../../../envoy/tests/7_opencode_sdk/`.** Only `common.py` differs, in the health URL `run_all.py` probes.
