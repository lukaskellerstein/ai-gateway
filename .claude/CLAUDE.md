# ai-gateway — the working contract

## Workflow — mandatory for any prompt that changes something

If you will use Edit or Write, or run `podman compose` / `docker compose` here, complete
all five steps before reporting. Applies to every kind of work — compose, aliases, docs,
troubleshooting.

1. **Understand** → [`rules/02-understand.md`](rules/02-understand.md)
2. **Plan** → [`rules/03-plan.md`](rules/03-plan.md) *(skip for trivial changes)*
3. **Implement** → [`rules/05-implement.md`](rules/05-implement.md)
4. **Test** → [`rules/06-testing.md`](rules/06-testing.md)
5. **Report** → [`rules/08-report.md`](rules/08-report.md)

**Never report completion without bringing the gateway up and getting a real answer out of
the alias you touched.** A mistyped `api_base` parses perfectly and fails on the first
call. Verification is your job — the user should never have to ask.

Reference: [`01-project-config.md`](rules/01-project-config.md) (services, ports, engines,
aliases) · [`09-code-quality.md`](rules/09-code-quality.md) ·
[`11-communication.md`](rules/11-communication.md) ·
[`12-security.md`](rules/12-security.md) ·
[`machine-tools.md`](rules/machine-tools.md) (`nvim-tools`, `lukas-ps` — pre-approved,
read-only) · [`lsp.md`](rules/lsp.md) (no `lsp-*` plugin here, so use `grep`).

## The repo in a dozen points

- **TWO STANDALONE COMPOSE PROJECTS, AND NOTHING AT THE ROOT.** There is no root
  `compose.yml`, no root `.env` and no root `tests/`. You start a gateway by entering its
  folder. Split 2026-09-03; `envoy/` added 2026-09-04:

  | Folder | Project name | Port | Services |
  |:--|:--|:--|:--|
  | `litellm/` | **`ai-gateway`** | 24000 | `postgres`, `discover`, `litellm` |
  | `envoy/` | `ai-gateway-envoy` | 26000, 26064 | `envoy` — **one service, no database** |

  `discover` is a one-shot whose finished state is **exited (0)**. Only `litellm/` runs a
  postgres, and it does not publish a port. `envoy/` is `aigw run`, Envoy AI Gateway's
  standalone mode: a real Envoy data plane from one config file, no Kubernetes, no build step.

  **A THIRD PROJECT, `mlflow/` ON 25000, WAS DELETED ON 2026-09-04.** It lost on every
  contract row and carried all the Python in the repo; the root `README.md` § What was removed
  has the table. Do not propose bringing it back, and treat any leftover reference to it as a
  doc bug.

  **THE ONE THING AT THE ROOT IS `benchmark/` (added 2026-09-04), and it is not a project.**
  It starts nothing and reads no project's files — only the two documented URLs — so the two
  stay as independent as before. It times ONE HTTP request against both ports with the engine,
  model, body and `max_tokens` held identical, and it is the closest thing here to the
  cross-gateway check that went away at the split. Results live in the root `README.md`.
- **`name: ai-gateway` IN `litellm/compose.yml` IS LOAD-BEARING.** The volume resolves to
  `<project>_postgres_data`, so that word is what keeps it attached to
  `ai-gateway_postgres_data` — every virtual key, spend log and budget ceiling ever issued.
  Rename the project and compose creates a NEW EMPTY volume, LiteLLM migrates a fresh
  schema, and every key other projects hold stops working. **Nothing errors.**
- **THERE IS NO `COMPOSE_PROFILES` ANY MORE.** It was the gateway switch until the split;
  the directory is now that switch. Two words remain, per project, in that project's own
  `.env`:

  | Variable | Values | Default | Picks |
  |:--|:--|:--|:--|
  | `GATEWAY_ENGINE` | `lms`, `unsloth`, `ollama`, `openrouter`, `openai` | `lms` | which engine |
  | `GATEWAY_DISCOVERY` | *(empty)*, `on` | *(empty)* | which models |

- **THE TWO PROJECTS CAN SERVE DIFFERENT ENGINES, and nothing notices.** Each has its own
  `.env` and its own `GATEWAY_ENGINE`. Before the split one word drove both and they could
  not diverge. If a comparison is the point, check both `.env` files first.
- **AUTO-DISCOVERY IS OFF BY DEFAULT AND IS PURELY ADDITIVE.** With `GATEWAY_DISCOVERY`
  empty nothing changes: each gateway serves exactly the aliases its hand-written file
  names, and those files stay as the worked example of hand configuration. Set it and the
  gateway ADDS every model the engine holds on disk, named `<engine>-<slugged model id>`
  (`lms-google-gemma-4-e4b`, `ollama-gemma4-26b`). LiteLLM's generated
  `litellm/config/discovered-<engine>.yaml` **includes** the hand-written file, so a
  hand-written alias can never be replaced or shadowed. **Discovery is local-only** —
  `openrouter` and `openai` are never enumerated, because money is never discovered. Since
  2026-09-05 they get a **PASS-THROUGH** `discovered-<engine>.yaml` that includes the
  hand-written file and adds nothing: discovery decides WHAT is served, never WHETHER the
  gateway runs. Before that they exited 2, no file was written, and LiteLLM crash-looped on
  `Config file not found` — so discovery on plus a paid engine meant NO GATEWAY.
  **Only `litellm/` has discovery at all.**
- **`GATEWAY_DISCOVERY=off` DOES NOT TURN IT OFF.** compose builds the config filename with
  `${GATEWAY_DISCOVERY:+discovered-}`, which reacts to the word being non-empty, not to its
  meaning. `litellm/` catches `off`, `false`, `0` and `no` and refuses. **The way to turn it
  off is an EMPTY value.**
- **ONE ENGINE AT A TIME, per project.** No list, no `all`. `GATEWAY_ENGINE` names one file
  — `litellm/config/<engine>.yaml` or `envoy/config/<engine>.yaml`. Each engine has two or
  three aliases; every other alias is absent from the running config, and a 404 on one is
  correct.
- **NOTHING IS SHARED BETWEEN THE FOLDERS.** Each carries everything it needs, so either can
  be deleted whole — which is exactly what happened to `mlflow/` on 2026-09-04, and nothing
  else stopped working. `discover/gateway_discovery.py` existed twice for that reason and is
  now down to LiteLLM's copy alone.
- **`envoy/` HAS NO DISCOVERY AT ALL, and that is a gap not a decision.** It would need
  another renderer (AIGatewayRoute rules), and the aigw image is distroless — no shell, no
  Python — so there is nowhere to run one without a third image. `envoy/README.md` says so.
- **ENVOY'S OWN TRAPS, all measured 2026-09-04:**
  - `AIGW_DEBUG` must never be EMPTY. aigw parses it as a bool and crash-loops on `""`
    before reading any config. `${AIGW_DEBUG:-false}`, not `${AIGW_DEBUG:-}`.
  - **`/health` on 26064 goes green BEFORE 26000 accepts a connection.** Probe
    `26000/v1/models` instead, which needs no key.
  - **With `AIGW_DEBUG=false` there is NO per-request logging at all.** Envoy's stdout goes
    to a file inside a distroless container. `true` gives the JSON access line AND a full
    prompt/response dump.
  - **`compose exec` cannot work** — distroless, no shell. Use `compose logs`.
  - The config mounts at `/etc/aigw`, never `/app`: `/app` IS the binary.
- **AN ALIAS IS TWO EDITS, AND NOTHING CHECKS THAT YOU DID BOTH.** Add it to
  `litellm/config/<engine>.yaml` **and** `envoy/config/<engine>.yaml`. Do one and the name
  answers on that port and 404s on the other, with nothing in any log to say why. The shared
  test suite that used to catch this went with the split — each project now tests only itself.
  Do not "fix" this by making one project read another's files.
- **Every alias names its engine** — `lms-*`, `unsloth-*`, `ollama-*`, `openrouter-*`,
  `openai-*`. There is no engine-neutral name (`local` was removed) and no capability name
  (`cheap`, `standard`, `frontier` were removed): the first hid which engine answered, the
  second hid who was billed. **The prefix is the money warning** — the three local engines
  are free; `openrouter` and `openai` bill a real account. **No alias falls back to
  another**, so a request costs money only when a caller names a route that costs money.
- **Local routes are shadow-priced** — free, but carrying a cloud twin's rate so budget
  ceilings still trip. Anything summing `/spend/logs` must say whether it reports money
  billed or the cost of the same workload in the cloud.
- **Almost no code, and then `tests/`.** Two `compose.yml`, six YAML in `litellm/config/`,
  five YAML in `envoy/config/`, one discovery module, three `README.md`. Every image is stock
  — there is no build step, and `discover/` reaches for nothing outside the standard library.
  Deleting `mlflow/` removed about 1200 lines of Python, which was all of it.
- **EACH `tests/` IS SEVEN FOLDERS, ONE PER WAY OF CALLING THE GATEWAY** (added 2026-09-04):
  `1_http_client` (urllib, **no dependencies**), `2_openai_client` (the four scripts that used
  to be `tests/` itself), `3_langchain_langgraph`, `4_deepagents`, `5_claude_agent_sdk`,
  `6_codex_sdk`, `7_opencode_sdk`. **Each folder is its own uv project** with its own
  `pyproject.toml` and `.venv`; `uv run --directory` builds whichever is missing, so there is
  no `uv sync` step. `tests/run_all.py` runs all seven; `tests/gateway.py` holds the base URL,
  the key and the alias **once per project** and imports nothing outside the standard library,
  because it must import inside `1_http_client`'s empty venv.
- **ALL SEVEN FOLDERS RUN ON BOTH GATEWAYS.** That was not true of `mlflow/`, which had
  neither an Anthropic route nor `/v1/responses` (both 404, measured 2026-09-04) and carried
  two probe-only folders to prove it. Those went with the folder. **A gateway that cannot do
  something gets a script that proves it, never a shim that fakes it** — the rule stands even
  though nothing here needs it now.
- **ENVOY'S ANTHROPIC ROUTE NEEDS A PASS-THROUGH ALIAS, AND THE REASON IS THE ENGINE**
  (measured 2026-09-04). `/anthropic/v1/messages` on a plain alias TRANSLATES Anthropic →
  OpenAI, and passes the reply's own `thinking` blocks — which Envoy builds out of the
  engine's `reasoning_content` — straight into the OpenAI body. An OpenAI `content` part may
  only be `text` or `image_url`, so the ENGINE answers `400 messages.N.content.str`. The
  identical error comes back from Unsloth on 8888 with NO GATEWAY in the path, and from
  LMStudio and Ollama too. It was intermittent, about 1 run in 5, because the engine emits
  `reasoning_content` on some replies and not others. **The cure is `<alias>-anthropic` on an
  `Anthropic`-schema `AIServiceBackend`**, now present for all three local engines: every one
  serves `POST /v1/messages` natively, so nothing is translated and nothing is mangled.
  `tests/5_claude_agent_sdk` RESOLVES THAT ALIAS AND REFUSES TO RUN WITHOUT IT.
  **`MAX_THINKING_TOKENS=0` IS NO LONGER NEEDED** — it existed for `400 thinking.type` from
  the same translator, and the pass-through path accepts the field as sent.
- **LITELLM CARRIES REASONING ON ITS OPENAI ROUTES AND DROPS IT ON `/v1/messages`; ENVOY
  CARRIES IT ON BOTH** (measured 2026-09-04, same engine, same prompt). LiteLLM's
  `/v1/chat/completions` returned 1606 characters of `reasoning_content`; the same request
  through its Anthropic adapter came back as a text block and nothing else, 8 runs in 8.
  **It is a known upstream bug** — BerriAI/litellm#29518 and #27946, both open — where the
  adapter checks only `thinking_blocks` and never falls back to `reasoning_content`.
  `supports_reasoning: true`, `merge_reasoning_content_in_choices: true` and a generous
  `max_tokens`/`budget_tokens` were all tried and none fixes it. **It only bites the Claude
  Agent SDK**, which speaks no other route. Envoy's `-anthropic` alias does not translate, so
  the engine's own thinking block arrives whole on all three local engines. Both folders'
  `07_thinking.py` DECLARE this as `THINKING_REACHES_CLIENT` and assert it.
- **UNSLOTH SOMETIMES 500s ON A VISION CALL, AND IT IS THE ENGINE** (seen 2026-09-04):
  `500 The model produced output that does not match the expected peg-gemma4 format`, from a
  request that succeeded three times out of three on retry. It surfaced through Envoy on
  `2_openai_client/03_multimodal.py` while LiteLLM passed the same scenario in the same run.
  **Do not chase it in the gateway** — re-run first, and only investigate if it repeats.
- **PODMAN IS THE RUNTIME HERE, NOT DOCKER** (decided 2026-09-04). Both compose files work
  under either, and every instruction in the repo now says `podman compose`. The reason it
  matters is not preference but STORAGE: **each runtime keeps its own volumes**, so
  `ai-gateway_postgres_data` exists TWICE — once under Podman, once under Docker — and each
  holds a different key and spend history. Starting LiteLLM under the other runtime does not
  destroy anything, but it serves a different database, and every virtual key issued from the
  other one stops working until you switch back. Podman's copy is the one in use: 4 virtual
  keys and 2294 spend rows, checked 2026-09-04. **`podman ps` and `docker ps` each show only
  their own containers** — a gateway that looks "not running" is often running under the
  other one.
- **EVERY TEST FOLDER IS ON THE NEWEST PUBLISHED RELEASE, AND SAYS SO IN ITS MANIFEST**
  (checked against PyPI 2026-09-04): deepagents 0.7.13, langchain 1.4.0, langgraph 1.2.11,
  openai 3.8.0, claude-agent-sdk 0.2.152, openai-codex 0.147.0, langchain-mcp-adapters
  0.3.2, mcp 2.1.1 (1.29.1 in `4_deepagents` — see below). **The declared floor in each
  `pyproject.toml` IS the version that was proven**, not a historical minimum: `>=0.7.13`,
  never `>=0.6.12`. That is deliberate — a floor two years old says a test passed on
  something nobody has run. Upgrading is `uv lock --upgrade` in the folder, then raise the
  floors to whatever it resolved, then run the suite.
- **`write_todos` IS NOT IN DEEPAGENTS' DEFAULT HARNESS, AND THAT IS A PROFILE DECISION**
  (0.7.13, measured 2026-09-04). The default suite is `ls`, `read_file`, `write_file`,
  `edit_file`, `glob`, `grep`, `delete`, `execute`, `task`. Two shipped harness profiles —
  `_openai_codex` and `_nvidia_nemotron_3_ultra` — add `TodoListMiddleware`; the three
  Anthropic ones and the default do not, and a local gemma matches no profile. So
  `tests/4_deepagents/02_todos.py` adds the middleware itself. Without it the model writes
  its plan to a FILE: request satisfied, planner never touched, green row proving nothing.
- **`mcp` IS 1.x IN `4_deepagents` BECAUSE THE ADAPTER CAPS IT.** `langchain-mcp-adapters`
  0.3.2, the newest, declares `mcp>=1.24.0,<2.0.0` — upstream has not adopted mcp 2 yet.
  **The wire itself is version-agnostic**: an mcp 1.29.1 client discovered and called an mcp
  2.1.1 server across two venvs (measured 2026-09-04). `mcp_server.py` exists in two
  dialects only so each folder stays copyable on its own.
- **CODEX CANNOT CALL MCP TOOLS ON EITHER GATEWAY, AND IT IS AN OPEN UPSTREAM BUG**
  (measured 2026-09-04). openai/codex#19871 — MCP tool invocation regressed for custom
  providers on the Responses API from 0.117.0; last good runtime 0.116.0. We PROVED both
  sides with the same server, prompt and `unsloth-4b`: **0.116.0 calls the tool, 0.147.0
  does not.** `tests/6_codex_sdk/04_mcp.py` therefore asserts the WIRING — Codex spawns the
  server, handshakes and reads `tools/list` — and PRINTS the bug link every run. A second
  open bug, openai/codex#24135, means MCP calls cannot be approved non-interactively at all;
  a frontier model called the tool correctly and Codex answered "rejected due to unacceptable
  risk". **Re-check both issues when folder 6 comes up.** Pinning 0.116.0 is not an option:
  its app-server protocol predates the Python SDK and Envoy 400s its payload
  (envoyproxy/ai-gateway#2586).
- **OPENCODE CAN DO WHAT CODEX CANNOT: `tools={"bash": false, …}` PER PROMPT.** Switching the
  built-in tools off for one prompt leaves an MCP tool as the only way to answer, and a 4B
  model then calls it every time (measured 2026-09-04, `tests/7_opencode_sdk/04_mcp.py`
  green on both gateways). Codex has no equivalent lever, which is the practical difference
  between the two folders' MCP scenarios. **OpenCode's structured output is in
  `info.structured`, NOT in the text parts** — reading the text and calling `json.loads`
  fails even when everything worked.
- **`~/.codex/config.toml` LEAKS INTO EVERY CODEX RUN.** With this machine's plugins the
  model was handed **~80 tools** — a full Playwright API and Codex Apps. `mcp_servers={}`
  plus `plugins={}` in `config_overrides` cuts it to 17 and is the Codex equivalent of
  `setting_sources=[]`. Without it a run depends on who is at the keyboard.
- **BOTH GATEWAYS STREAM CORRECTLY** with the byte-identical `1_http_client` script.
  `main.py` still guards against an SSE frame carrying an `error` instead of a `delta` and
  reports SKIPPED — the deleted MLflow gateway failed exactly that way
  (`KeyError: 'finish_reason'`). Keep the guard; it costs two lines.
- **THE GATEWAY ITSELF COSTS 10-20 ms, MEASURED, AND THE TWO ARE WITHIN 10 ms OF EACH
  OTHER** (`benchmark/`, 10 rounds, 2026-09-04). The overhead is FLAT — the same on a 2-token
  reply as on a 264-token one, and the same on a 4 KB prompt as on a tiny one. **Never quote a
  test folder's wall clock as a gateway speed**: it is dominated by venv builds, imports, CLI
  spawns and the engine's warm/cold state, and the SAME script on the SAME gateway measured
  5.8 s to 46.7 s over eight runs. Choose a gateway on features; the proxy is not what you
  wait for.
- **`max_tokens` MUST BE SENT EXPLICITLY IN ANY COMPARISON.** LiteLLM stores a route default
  and Envoy stores none, so a body without a ceiling asks LiteLLM to do LESS WORK. That one
  control is the difference between a benchmark and a number.
- **Ports 24000 / 26000 are deliberate.** The failure avoided is not a bind error but the
  silent one: a health probe against `localhost:4000` that another stack answers, going
  green. 25000 is now free — it was the deleted MLflow gateway's.
- **Health**: `curl -fsS http://localhost:24000/health/readiness` →
  `{"status":"healthy","db":"connected"}`. Use readiness, not liveliness — only readiness
  reports the database, and a proxy that booted without one still serves completions. First
  boot takes ~60 s for schema migrations. **Envoy: probe `26000/v1/models`, NOT
  `26064/health`** — the admin port answers before the data plane does.

Full facts → [`rules/01-project-config.md`](rules/01-project-config.md).

## Standing authorizations — do NOT ask before doing these

**Read-only, always safe:** `podman compose ps | config | logs` **from inside a gateway
folder**; `curl` against 24000 (`/health/readiness`, `/health`, `/model/info`, `/key/info`,
`/spend/logs`, completions) and 26000 (`/v1/models`, completions) / 26064 (`/health`,
`/metrics`); `cd litellm/tests && uv run run_all.py`, and the same in `envoy/tests`
(no `uv sync` — each of the seven folders builds its own venv on first `uv run`);
`lms ps --json`; `ollama ps | list`; `podman compose exec postgres psql -U postgres -c
"SELECT ..."` — **`SELECT` only**; `git status | diff | log`; reading any file here.
**`litellm/.env` and `envoy/.env` are denied to you — ask the user what is in them.**

> **`compose config` PRINTS SECRETS.** Compose reads the shell first, and `~/Projects/.envrc`
> exports the real provider keys — so a bare `compose config` dumps `UNSLOTH_API_KEY` and the
> rest in plaintext into the transcript. Filter it (`| grep -v API_KEY`) or use
> `compose config --services`. This happened on 2026-09-03 and cost a key rotation.

Calling a **free** alias to check something is always fine. A **paid** one
(`openrouter-*`, `openai-*`) costs money, so keep it to one short call.

**Pre-approved mutations:** editing `litellm/`, `envoy/`, `benchmark/`, `README.md`,
`LICENSE`, `.claude/`; `up -d`, `restart`, and `down` **without `-v`** in either project;
re-running `discover`; bringing a gateway up on another engine for a test — **then putting it
back the way you found it**; minting a virtual key that carries **both** `max_budget` ≤ 2.00
and `duration` ≤ `7d`.

## Requires confirmation — always ask first

- **Changing `name:` in `litellm/compose.yml`.** It silently detaches the postgres volume
  holding every virtual key, spend log and budget ceiling. See point 2 above.
- **`down -v`**, or anything else removing a `postgres_data` volume. On the LiteLLM project
  it destroys every virtual key, all spend history and every budget ceiling, unrecoverably —
  the keys other projects hold stop working at that moment.
- **Removing or weakening the provider pin** (`order: ["google-ai-studio"]`,
  `allow_fallbacks: false`) in `litellm/config/openrouter.yaml`. It looks like dead
  configuration and is the only thing preventing raw-text tool calls that make agents
  silently do nothing.
- **Selecting a paid engine** — `GATEWAY_ENGINE=openrouter` or `openai` — in a project the
  user did not ask to make billable. Bringing one UP without calling it spends nothing and is
  how `envoy/config/openrouter.yaml` and `openai.yaml` were checked; a COMPLETION through one
  is what costs money.
- **Changing `LITELLM_MASTER_KEY`**, or minting a key with no `max_budget` or no
  `duration`. Both hand out spend against real provider accounts.
- **`lms load` / `lms unload`** on the host. It can evict a model another session is
  mid-request against, and several sessions run here at once.
- **Changing the published ports**, or publishing a `postgres`. Both re-enter the collision
  the 2xxxx band exists to avoid.
- **Removing the `ai-gateway-mlflow_postgres_data` and `ai-gateway-mlflow_mlflow_artifacts`
  volumes.** The `mlflow/` folder went on 2026-09-04 and these two outlived it, holding that
  gateway's endpoints and traces. Nothing reads them, and nothing will — but deleting a volume
  is unrecoverable, so ask.
- Setting `lms-26b`'s `*_cost_per_token` to `0`. It silently disables every budget ceiling
  for local traffic.
- **Re-coupling the projects** — a shared module, a shared `.env`, a root `compose.yml`, or
  anything in one folder that reads a file in another. The separation was asked for
  explicitly; its costs are known and documented.
- `git push`, force-push, branch deletes. **Never commit unless the user explicitly asks.**
- Anything touching secrets, TLS material or credential files →
  [`12-security.md`](rules/12-security.md).

When in doubt, ask. **Every project on this laptop calls this gateway** — a bad edit here
does not break one repo, it takes LLM access away from all of them at once.
