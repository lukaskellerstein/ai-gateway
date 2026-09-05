# Step 3: Implement

- **Do not commit unless the user explicitly asks.**
- Write clean code from the start; refactor as you go rather than "later".
- Delete dead code. No commented-out blocks kept "just in case", no TODOs.
- Use `mermaid` for diagrams.

This repo is almost all configuration, so what those rules mean here: **a config change is
still a change, and the comments are the reasoning.** Keep them accurate rather than tidy —
every number carries a comment saying where it came from.

## Which file to edit

| Change | Goes in |
|:--|:--|
| an alias | `litellm/config/<engine>.yaml` **and** `envoy/config/<engine>.yaml` — two files |
| a LiteLLM settings block (`router_settings`, `general_settings`, …) | `litellm/config/settings.yaml` — once; every engine file includes it |
| how an engine is chosen | the `--config` path in `litellm/compose.yml`, and `AIGW_CONFIG` in `envoy/compose.yml` |
| what auto-discovery finds, or how it renders | `litellm/discover/gateway_discovery.py` — one copy now. `envoy/` has no discovery |
| an Envoy route, backend, timeout or buffer limit | `envoy/config/<engine>.yaml` — Kubernetes custom resources, self-contained per engine |
| services, ports, healthchecks, env | that project's `compose.yml` — never several in one edit unless the change is genuinely several |
| anything a caller reads | the README of the gateway it concerns, or `README.md` if it is shared |

**An alias is never one edit.** Each project owns its own list and neither reads the other's.
Add it on one side only and the name answers on that port and 404s on the other, with nothing
in any log to say why — and **no test catches it**, because the shared suite that used to went
with the split. Call it on **both** ports afterwards — [`06-testing.md`](06-testing.md).

**Adding an alias is a five-part edit**, and skipping any part is a bug that hides:

1. the `model_list` entry in `litellm/config/<engine>.yaml`
2. its price — an unpriced route logs `$0`, which makes a budget ceiling a no-op
3. its `max_input_tokens` — what `enable_pre_call_checks` uses to catch an over-long prompt
4. the matching `AIGatewayRoute` rule in `envoy/config/<engine>.yaml` — an exact
   `x-ai-eg-model` match, a `modelNameOverride`, and a `request` timeout
5. the alias table in `README.md` — a route nobody documents is a route nobody calls

**The alias name must carry its engine.** `lms-*`, `unsloth-*`, `ollama-*`,
`openrouter-*`, `openai-*`. No engine-neutral name, no capability name.

## The two projects must stay independent

They were split on 2026-09-03 at the user's explicit request, and 2026-09-04 tested the design
both ways: `envoy/` was **added** without touching either existing folder, and `mlflow/` was
**deleted** without breaking anything left. **Do not re-couple them.** No shared module, no
shared `.env`, no root `compose.yml`, and nothing in one folder that reads a file in another.
The costs are known and written down; they are not a defect to fix.

Duplication between the folders is the price of that, and it is the right price. When
`mlflow/` existed, `discover/gateway_discovery.py` sat in two copies for exactly this reason —
and when the folder went, its copy went with it and nothing had to be untangled.

## The `compose.yml` files

- **`name:` IS THE MOST DANGEROUS LINE IN THIS REPO.** `litellm/compose.yml` carries
  `name: ai-gateway`, and the volume resolves to `<project>_postgres_data`. Change that word
  and compose attaches a NEW EMPTY volume: LiteLLM migrates a fresh schema and every virtual
  key, spend log and budget ceiling is gone, with no error anywhere. `envoy/compose.yml`
  uses `ai-gateway-envoy`, which is what lets both run at once.
- **`./config` mounts at `/app/config`, not `/app/litellm`.** The image already ships
  `/app/litellm` — the proxy's own Python package — and mounting over it breaks the
  container. The whole directory is mounted because each engine config includes
  `settings.yaml` by relative path.
- **`config/` is a subdirectory, not the folder itself.** The folder holds `.env` now, and
  mounting it would put a secrets file inside the container.
- **There are no `profiles:` any more.** The directory is the gateway switch. Do not
  reintroduce them.
- **`envoy/compose.yml` mounts at `/etc/aigw`, never `/app`.** `/app` IS the binary in that
  image. And `AIGW_DEBUG` must default to `false`, never to empty: aigw parses it as a bool
  and crash-loops on an empty string before reading any config.
- **`DATABASE_URL` is required, not optional.** Without it the proxy boots in no-DB mode:
  completions keep working while `/key/generate` fails with `{"error":"No connected db."}`.
  That is the worst failure for a budget guardrail — callers proceed uncapped and nothing
  looks broken.
- **`start_period: 60s`** covers first-boot schema migrations. Shorten it and a cold
  `up -d` reports unhealthy while working correctly.
- **No credential values.** `LITELLM_MASTER_KEY` is `${LITELLM_MASTER_KEY:-sk-litellm-master}`
  and the provider keys are `${..:-}`; the real values arrive from the shell.

## `litellm/` — gateway 1

`config/settings.yaml` holds the three settings blocks and the facts true of every alias
(timeouts, shadow pricing, reasoning). `config/<engine>.yaml` holds `model_list` and nothing
else. **Envoy has no place for prices, `max_tokens` or context windows, so those live here
and only here.**

- **Do not remove the provider pin** on `openrouter-free`. `order: ["google-ai-studio"]`
  plus `allow_fallbacks: false` exists because OpenRouter load-balances its free tier and
  one provider returns tool calls as raw text with `tool_calls` absent. Nothing errors: the
  agent sees a message with no tool calls, executes nothing, and stops.
- **`success_callback` is empty on purpose.** A trace store is a *project's* system of
  record; two projects sharing one experiment namespace makes "did this get better"
  ambiguous.

**A LiteLLM feature the other gateway has no equivalent for is documented, not faked.** A
shim that half-implements one is worse than the gap, because it reads as working. That rule
outlived the gateway it was written for.

## Settings that exist for one client

Most of what breaks here breaks for **one combination**, not for the gateway: a provider, a
route, and a client. `use_chat_completions_url_for_anthropic_messages` exists for exactly
`openai/` + `/v1/messages` + the Claude Agent SDK, and is invisible to the other six test
folders. The danger is not the setting. It is that the next person makes a **different**
client pass, removes it, and nothing goes red — so the same investigation happens twice.

Three rules, and the third is the one that costs money to learn.

**1. Every non-obvious setting carries this four-field header, above the line it explains.**

```yaml
# WHY:            what breaks without it, with the measurement
# SCOPE:          provider=<prefix>  route=<endpoint>  client=<test folder>
# GLOBAL BECAUSE: the file:line proving no per-alias override exists — or delete this
#                 field, because a setting that CAN be scoped must be
# PROVEN:         date, version, alias, the numbers
# GUARDED BY:     the test that goes red if this line is deleted
```

**`GUARDED BY` is not optional, and it is the point of the whole convention.** If no test
fails when the setting is removed, the setting is already lost — write the test first. Add
a `TRIED AND REJECTED` line too, naming the dead ends and their numbers: those are what get
re-tried at midnight.

**2. Prefer a per-alias route over a global flag, always.** LiteLLM's global knobs live in
`litellm_settings` and apply to every alias at once. Where a client needs different
treatment, the honest shape is a second alias — `model_info.supported_endpoints:
["/v1/messages"]` is per-deployment and does exactly this. **That is the same shape Envoy
already uses** with its `<alias>-anthropic` pass-through aliases, which is a good sign it
is the right one. A global flag has to justify itself in `GLOBAL BECAUSE` or it does not
belong.

**3. NEVER REVERT A FIX TO MAKE ANOTHER CLIENT PASS.** If a second client needs the
opposite of the first, that is a genuine contradiction in a global setting and flipping the
line back and forth is how the knowledge gets destroyed. Measure both directions, write
both into `litellm/README.md` § Provider × route, and keep **both** assertions in the
suite — so the conflict shows up as a red row that names itself, not as a silent
preference for whoever tested last. It is the repo's existing rule, *prove a gap, never
shim it*, applied to configuration.

**The matrix in `litellm/README.md` § Provider × route is the memory.** It records what was
tried and FAILED as well as what worked, per provider and route. Read it before
investigating anything that smells like a routing or reasoning bug, and add a row the day
you measure one — including the negative result.

## `envoy/` — gateway 2, and the only one you could deploy

`config/<engine>.yaml` is the same Kubernetes custom-resource API a cluster would read, so
what is proven here is what would ship. Five files, one per engine, each self-contained.

- **The alias mechanism is an `AIGatewayRoute` rule**: an exact `x-ai-eg-model` header match
  plus `modelNameOverride`. An alias with no rule gets 404.
- **Three numbers differ from upstream's example and must not be lowered.** `request: 60m`
  on BOTH the route and the backend (the smaller wins, and upstream's default is 3m);
  `bufferLimit: 50Mi` on the `ClientTrafficPolicy` (Envoy's 32 KiB default fails on a base64
  image); `logging.level: error` (at `debug` Envoy dumps request headers).
- **It has no discovery and no database.** Adding discovery needs another renderer and a
  second image, because the aigw image is distroless. That gap is documented, not hidden.
- **It cannot do budgets.** `QuotaPolicy` and token rate limiting need Redis plus an Envoy
  Gateway install — the Kubernetes path. Do not add a shim that pretends otherwise.

## The two `tests/`

**One folder per WAY OF CALLING the gateway, one script per KIND of call** — never per alias;
`--model` already covers "the same test on a different alias". **Each suite drives its own
gateway only**; there is no `--gateway` flag, because the folder is the answer.

```text
tests/
├── gateway.py              base URL · key · alias — ONCE per project, stdlib only
├── pyproject.toml          empty deps; exists so `uv run run_all.py` works here
├── run_all.py              runs every folder listed in FOLDERS
├── 1_http_client/          urllib. pyproject lists NO dependencies, deliberately
├── 2_openai_client/        openai — 01..04 plus its own run_all.py
├── 3_langchain_langgraph/  langchain + langgraph
├── 4_deepagents/           deepagents. SEVEN scenarios + its own run_all.py.
│                        query, todos, filesystem, tools, MCP, subagent, skill
├── 5_claude_agent_sdk/     claude-agent-sdk. SEVEN scenarios + its own run_all.py.
│                        query, session, in-process MCP, stdio MCP, subagent,
│                        skill, thinking. Needs the `claude` CLI from npm
├── 6_codex_sdk/            openai-codex. FOUR scenarios + its own run_all.py.
│                        query, session, structured output, MCP wiring.
│                        Ships its own runtime; no npm
└── 7_opencode_sdk/         httpx. FIVE scenarios + its own run_all.py.
                         query, session, agent, MCP, structured output.
                         Needs the `opencode` binary
```

- **`gateway.py` IS THE ONLY PLACE THE GATEWAY IS NAMED.** Base URL, Anthropic base URL,
  Responses base URL, key, alias map, `MAX_TOKENS`, `BODY_EXTRAS`. Seven folders import it, so
  changing an engine default is one edit. **It must import with NO dependencies installed** —
  `1_http_client`'s venv is empty — which is why it parses `../.env` by hand instead of using
  `python-dotenv`. Do not add an import to it.
- **A new folder is two edits**: write it, and add its name to `FOLDERS` in `run_all.py`. Give
  it a `main.py`; every folder except `1_http_client` and `3_langchain_langgraph` now carries
  its own `run_all.py`, and the
  runner picks whichever exists.
- **EACH FOLDER IS ITS OWN uv PROJECT.** The dependency sets have nothing in common, and a
  folder has to be readable and copyable on its own. Never merge them into one manifest.
- **`main.py` in folders 1, 3, 4, 6 and 7 is BYTE-IDENTICAL across both projects.** They name
  no port and no gateway — everything specific comes from `gateway.py`. Keep it that way; a
  demo that branches on `NAME` has stopped being portable. **Folder 5 keeps the same rule with
  a `common.py`**: its six
  numbered scenarios, `run_all.py` and `mcp_server.py` are byte-identical between `litellm/`
  and `envoy/`, and the one difference — Envoy resolves an `<alias>-anthropic` pass-through
  alias, LiteLLM calls the alias as given — lives in that file alone.
- **A folder that CANNOT work gets a script that proves it, not an empty folder.** Nothing
  needs one today — all seven run on both gateways. The rule was written for `mlflow/`, whose
  folders 5 and 6 probed for a missing route and PASSED while it was still missing, and it
  stands if the case comes up again. **Do not shim a route.**
- **A gateway that fails HALFWAY gets a SKIP, not a FAIL** — and NOTHING SKIPS ANYTHING NOW.
  `1_http_client` still guards an SSE frame carrying an `error` instead of a `delta` and would
  report SKIPPED; that guard was earned by MLflow's stream and costs two lines, so keep it.
  `5_claude_agent_sdk` used to skip two things and no longer skips either: a missing
  `<alias>-anthropic` route is a hard exit naming the file to edit, because every local engine
  can serve one, and the intermittent `400 messages.N.content.str` went away with the
  pass-through alias. **A skip is for what the gateway cannot do, never for what is merely
  flaky** — fix the flake instead.
- **The differences go in `Gateway`, as data — never in a scenario.** The vocabulary is
  shared between the projects; the calling contract is not. Four things differ (the API key,
  the model listing, what `response.model` echoes, and whether a route stores a
  `max_tokens`), and all four are declared once on that project's
  `2_openai_client/common.Gateway`. A scenario applies the contract by spreading
  `**gateway.body_extras` into its request and reads nothing else.
- **`01`–`03` are byte-identical across both projects on purpose.** They never name a
  gateway, so a scenario written for one can be copied to the other unchanged. Keep it that
  way — a scenario that reads `gateway.name` has stopped being portable.
- **The two contracts are genuinely different, and only ONE of the four lines matches.** Envoy
  lists its models like LiteLLM, and then checks no caller key and echoes the upstream model
  id rather than the alias. Anything written as "LiteLLM or not-LiteLLM" is wrong about it.
- **`04_gateway_contract.py` is the ONE script that is about its gateway**, and even it does
  not branch on the name: it checks the DECLARED table against observed behaviour, so a
  failure reads "the table says X and the gateway did Y". Add a difference to a table and
  add its check there, in the same commit.
- **`02_tools_call.py` checks `finish_reason` and the `tool_calls` structure**, not the
  words in the reply. A model emitting raw-text tool syntax returns a perfectly
  good-looking message — that is the failure the file exists to catch.
- **Its tools return fixed numbers.** A test calling a real API cannot tell "the gateway is
  broken" from "the market is closed".
- `2_openai_client/run_all.py` globs `NN_*.py`, so a new script there needs no edit. The
  suite-level `run_all.py` one level up uses an explicit `FOLDERS` tuple instead, because
  the order is the teaching order and a glob would not preserve it.

## The four `README.md`

**`README.md` at the root is the front door**, written for a stranger: what the repo is,
which gateway to pick, the shared alias table, the host-engine facts, the design decisions,
and § What was removed. Each gateway's own `README.md` carries everything specific to it — its
endpoints, its configuration table, its discovery, its troubleshooting, its layout.
`benchmark/README.md` is the fourth.

Keep all four slim: a new fact replaces a vaguer one rather than being appended. Deep
per-alias measurement belongs in the comments of `litellm/config/<engine>.yaml`. No absolute
home paths.

They carry **verified-on dates** against specific claims. Re-verify one and move the date;
change what it describes without re-testing and delete the claim, rather than leaving a
date vouching for something untested.

## Repository structure

```text
ai-gateway/
├── README.md               the front door, the shared vocabulary, the BENCHMARK RESULTS
├── benchmark/              what the gateway itself costs. Calls both ports;
│                            reads no project's files. No dependencies
├── litellm/                compose project `ai-gateway`         PORT 24000
│   ├── compose.yml             postgres · discover · litellm. name: DO NOT RENAME
│   ├── .env.example            tracked; the key lines are blank BY DESIGN
│   ├── config/                 settings.yaml + <engine>.yaml, mounted read-only
│   ├── discover/               probes + the YAML renderer; stdlib only. THE ONLY COPY
│   ├── tests/                  SEVEN uv projects, one per way of calling the gateway
│   └── README.md
├── envoy/                  compose project `ai-gateway-envoy`   PORT 26000/26064
│   ├── compose.yml             ONE service, no database
│   ├── .env.example
│   ├── config/                 <engine>.yaml — Kubernetes custom resources
│   ├── tests/                  the same SEVEN, all working. NO discover/ — see envoy/README.md
│   └── README.md
└── .claude/                this contract
```
