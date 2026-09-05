# Step 4: Testing

**Every change is tested before you report it. No exceptions.** Verification is your job —
the user should never have to ask.

## Write the Definition of Done first

State in the conversation what you intend to verify, so the user can see it. For example:

> - [ ] `up -d` in the folder I touched brings every service to healthy
> - [ ] `/health/readiness` reports `db: connected`
> - [ ] a completion through the changed alias returns content, on **both** gateways
> - [ ] the request appears in the Logs tab with the expected model

## Bring it up and drive it

Never substitute "the YAML looks right" for a real answer. Run these **from inside the
gateway's folder** — there is no root `compose.yml`.

```bash
cd litellm                              # or envoy
podman compose config --services        # parses and interpolates. --services, NOT bare
podman compose up -d
podman compose ps -a                    # discover -> Exited (0) is DONE
curl -fsS http://localhost:24000/health/readiness    # -> {"status":"healthy","db":"connected"}
curl -fsS http://localhost:26000/v1/models          # Envoy: the DATA plane, NOT 26064
podman compose logs litellm             # what it loaded, and what it refused
```

> **`podman` needs the sandbox disabled.** It reads `~/.ssh/known_hosts`, which the sandbox
> denies, so every `podman` command fails with `unable to connect to Podman socket` until you
> re-run it with `dangerouslyDisableSandbox`. The machine is fine.

> **Never run a bare `podman compose config`.** Compose reads the shell first and
> `~/Projects/.envrc` exports the real provider keys, so it dumps `UNSLOTH_API_KEY` and the
> rest in plaintext into the transcript. Use `--services`, or pipe through
> `grep -v API_KEY`. This cost a key rotation on 2026-09-03.

On a cold start give it the full 60 s `start_period`; "unhealthy" inside that window is
expected. **On Envoy, never probe `26064/health`** — the admin server answers `OK` several
seconds before the data plane on 26000 accepts a connection, so a probe there passes while
the next call gets a connection reset.

## Then exercise the alias you actually changed

```bash
curl -sX POST http://localhost:24000/v1/chat/completions \
  -H "Authorization: Bearer ${AI_GATEWAY_KEY:-sk-litellm-master}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}]}'
```

> **A 200 does not prove the model you think answered.** LMStudio JIT-loads a
> non-resident model at 8192 context and answers a short prompt perfectly well. Check
> `lms ps --json` (or Unsloth's `GET /v1/status`, or `ollama ps`) first, and confirm the
> request in the Logs tab at <http://localhost:24000/ui>.

**If you touched an alias list, prove the SAME alias on BOTH gateways.** This is the check
that matters most, and **nothing automated does it any more** — the shared suite that used
to went when the projects were split. The two lists are separate and neither reads the other,
so an edit to one side alone is a silent drift only a call to the other port catches.

```bash
curl -sX POST http://localhost:26000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}],"max_tokens":2048}'
```

No key on Envoy, and **always send `max_tokens`** — it stores no route default. An alias that
answers on 24000 and 404s on 26000 means the edit was not made on that side, or the `.env`
files name different engines — **except `openrouter-free`, which is absent on 26000 by
design.**

## The suites

There are two, one per project, and each drives its own gateway. **Each is SEVEN folders**
since 2026-09-04, one per way of calling the gateway, and each folder is its own uv project —
so there is no `uv sync` step, because `uv run --directory` builds whichever venv is missing.

```bash
cd litellm/tests && uv run run_all.py    # 7 rows against 24000
cd envoy/tests   && uv run run_all.py    # 7 rows against 26000

uv run run_all.py --model <the alias you touched>   # every folder, one alias
uv run run_all.py --only 6_codex_sdk                # one folder
cd 3_langchain_langgraph && uv run main.py          # one folder, directly
```

| Folder | Calls the gateway with |
|:--|:--|
| `1_http_client` | `urllib`, **no dependencies at all** |
| `2_openai_client` | `openai` — the four scripts that used to BE `tests/` |
| `3_langchain_langgraph` | `ChatOpenAI(base_url=…)`, then the same loop built by hand |
| `4_deepagents` | a deep agent. **Seven scenarios: query, todos, filesystem, tools, MCP, subagent, skill** |
| `5_claude_agent_sdk` | `ANTHROPIC_BASE_URL` → the Anthropic Messages API. **Seven scenarios**: query, session, in-process MCP, stdio MCP, subagent, skill, thinking |
| `6_codex_sdk` | a `model_providers` override → the Responses API. **Four scenarios: query, session, structured output, MCP wiring** |
| `7_opencode_sdk` | an `@ai-sdk/openai-compatible` provider. **Five scenarios: query, session, agent, MCP, structured output** |

**`tests/gateway.py` holds the base URL, the key and the alias once per project.** Every
folder imports it, and it imports nothing outside the standard library — it has to load inside
`1_http_client`'s empty venv. Change an alias default there, never in seven places.

**All seven folders run on both gateways.** A folder that could not run used to carry a
script that PROVED the gap and passed while it lasted; both such folders went with `mlflow/`
on 2026-09-04. The rule stands if it ever comes up again: **prove a gap, never shim it**.

Each suite exits 1 on any failure and prints the failed run's output. **Neither is the whole
job**: each drives one alias per run, cannot tell you the stack came up, says nothing about
embeddings, budgets or keys, and **neither compares the gateways**.

## Extra checks, when they apply

- **You touched what selects a config** (either `compose.yml`, `discover/`) — prove more
  than one combination. At minimum bring the other project up too and confirm both answer at
  once, then check that stopping one leaves the other serving. **Then put them both back the
  way you found them**, including each project's `GATEWAY_ENGINE`.
- **You touched `litellm/discover/`** — prove it. It writes
  `litellm/config/discovered-<engine>.yaml`; drive it with `GATEWAY_DISCOVERY=on` and read the
  generated file. There is only one copy now: the second went with `mlflow/`.
- **You touched `litellm/compose.yml`** — check `name: ai-gateway` is still there, then
  prove the volume is still attached:
  `podman compose exec -T postgres psql -U postgres -d litellm -c 'SELECT count(*) FROM "LiteLLM_VerificationToken";'`
  A count of 0 on a machine that had keys means the volume was detached.
- **You touched `benchmark/`** — run it. It is the only thing that calls both ports, so a
  wrong URL or a stale gateway name there is invisible until someone runs it.
- **You touched `envoy/`** — prove all three LOCAL engines with a real completion. The two
  PAID ones can only be brought up and checked for their aliases on `/v1/models`, because a
  completion through either bills a real account. Check `AIGW_DEBUG` still defaults to
  `false` and not to empty, or the container crash-loops on a bool parse. **Each local engine
  file must also keep its two `<alias>-anthropic` rules and its `Anthropic`-schema
  `AIServiceBackend`**, or `tests/5_claude_agent_sdk` exits on that engine — by design, and
  the message names the file.
- **Tool calling or `/v1/messages`** — a plain completion is not enough. Send a request
  carrying a tool schema and confirm a structured `tool_calls` reply, not raw-text tool
  syntax. That distinction is the entire reason the provider pin exists.
- **Keys, budgets or spend** — mint a capped key and confirm the ceiling is real.
  `{"error":"No connected db."}` means the proxy booted without `DATABASE_URL`;
  completions still work, which is why this must be tested rather than assumed.
- **Documentation-only** — say explicitly why no runtime test was needed. But if you
  changed a **command or a claim**, run it. A wrong `curl` in a README is the failure
  the docs exist to prevent.
- **Every change** — `nvim-tools --json --all`. It must add no findings against your
  baseline. Expect everything `gated-off`: this repo carries no marker files, and nothing
  here formats YAML at all. That is configured, not broken.

## Fix, repeat, restore

If a test fails, fix it and retest until every DoD item passes. If you repeatedly cannot
resolve something, ask rather than reporting partial success — each gateway's `README.md`
has a troubleshooting table.

**Leave both projects as you found them.** They start and stop independently now, so
"as found" is two facts per project: whether it was up, and which engine it was on. Record
them before you touch anything.
