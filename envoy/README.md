# envoy — the second gateway, on port 26000

A standalone compose project. Run it from **this** directory; nothing above it is read, and
nothing here reads `../litellm`.

```bash
cp .env.example .env      # edit GATEWAY_ENGINE if you do not run LMStudio
podman compose up -d

curl -fsS http://localhost:26000/v1/models        # the alias list
```

`podman compose` works identically — the two are drop-in replacements here.

This is [Envoy AI Gateway](https://aigateway.envoyproxy.io/docs) in **standalone mode**
(`aigw run`): a real Envoy data plane driven by a config file, with **no Kubernetes and no
Envoy Gateway install**. One stock image, one service, no database, no build step — the image
ships the Envoy binary already downloaded.

**The same alias names as `../litellm`.** The table of what they point at is
in [`../README.md`](../README.md).

## Why this one is here

It is the only gateway here that is a **production proxy you could actually deploy**. The
config below is the same Kubernetes custom-resource API the Envoy AI Gateway controller reads
in a cluster — what is proven on this laptop is what would ship.

| It has | `../litellm` does not |
|:--|:--|
| **`/mcp`** — an MCP gateway that aggregates several MCP servers behind one endpoint, prefixes tool names by server, and can filter which tools are exposed | nothing like it |
| **`/anthropic/v1/messages`** translated onto *any* OpenAI-compatible backend | it has `/v1/messages`, which is the same job done natively |
| **`:26064/metrics`** — Prometheus | no |
| **OpenTelemetry tracing** with OpenInference spans, into Arize Phoenix with one variable | no |

**What it does not have, and cannot in standalone mode: virtual keys, budgets and spend
logs.** `QuotaPolicy` and token rate limiting need Redis plus an Envoy Gateway install
configured for it — the Kubernetes path. `aigw run` writes an Envoy Gateway config with no
rate-limit block at all. `../litellm` remains the only gateway here with spend controls.

**And it authenticates no caller.** Anything that can reach 26000 can call it, which is why it
binds localhost only. The keys in `config/` are what the gateway sends *upstream*.

## Call it

Any OpenAI-compatible client works. Point `base_url` at `http://localhost:26000/v1`, and
**always send `max_tokens`** — see below.

```bash
curl -sX POST http://localhost:26000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"lms-4b","messages":[{"role":"user","content":"hi"}],"max_tokens":2048}'
```

The OpenAI client needs *some* `api_key` string, and this gateway never reads it.

| Port | Path | What |
|:--|:--|:--|
| 26000 | `/v1/chat/completions` | the OpenAI route |
| 26000 | `/v1/embeddings` | the running engine's `*-embed` alias |
| 26000 | `/v1/models` | the alias list, built from the AIGatewayRoute rules |
| 26000 | `/v1/completions` | the legacy completions route |
| 26000 | `/anthropic/v1/messages` | the Anthropic API, translated onto the same backend |
| 26000 | `/mcp` | the MCP gateway — **needs `--mcp-config`; not wired up here** |
| 26064 | `/health` | `OK`. **See the race below** |
| 26064 | `/metrics` | Prometheus |

> **`/health` on 26064 goes green BEFORE 26000 accepts a connection.** The admin server starts
> with aigw; the Envoy listener takes a few more seconds. Measured 2026-09-04: probing 26064
> and then calling immediately gets a connection reset. **Probe `26000/v1/models` instead** —
> it needs no key and only answers once the data plane is really up. `tests/run_all.py` does
> exactly that.

### Always send `max_tokens`

An `AIGatewayRoute` rule carries a request **timeout** but no token ceiling, so a request that
sends none is unbounded. Measured 2026-09-04 with `lms-4b` and one "count to 3000" prompt
carrying no `max_tokens`:

| Gateway | finish_reason | completion tokens |
|:--|:--|--:|
| LiteLLM 24000 | `length` | 4095 — the route's stored `max_tokens: 4096` |
| **Envoy 26000** | `stop` | **13946** — nothing bounded it |

Get it wrong downwards and it is worse than slow: a reasoning model spends the whole allowance
thinking and returns **empty content** with `finish_reason: "length"` and no error at all.
Keep the ceiling generous.

## Its config is Kubernetes custom resources

`config/<engine>.yaml` is one self-contained document per engine, and it is the same API a
cluster would read. Seven resource kinds, every one load-bearing:

| Resource | Does |
|:--|:--|
| `GatewayClass` + `Gateway` | the listener on 1975 (published as 26000) |
| `EnvoyProxy` | log level, and the JSON access-log format |
| **`AIGatewayRoute`** | **the alias list** — one rule per alias |
| `Backend` | where the engine is: hostname and port |
| `AIServiceBackend` | what protocol it speaks, and the per-backend timeout |
| `ClientTrafficPolicy` | the 50 MiB buffer. **Without it large prompts fail** |
| `Secret` + `BackendSecurityPolicy` | the key sent upstream |

**The alias mechanism is `modelNameOverride`.** Each rule matches the alias exactly on the
`x-ai-eg-model` header — which the gateway fills in from the request body's `model` field —
and rewrites it on the way out:

```yaml
- matches:
    - headers:
        - type: Exact
          name: x-ai-eg-model
          value: lms-4b
  backendRefs:
    - name: lms
      modelNameOverride: google/gemma-4-e4b
  timeouts:
    request: 60m
```

An alias with no rule matches nothing and gets **404** (verified 2026-09-04), which is what
every other engine's names correctly do here.

Three numbers differ from upstream's own example, and each has a reason in the file:

- **`request: 60m`, not 120s**, on both the route and the backend. Prompt processing measures
  ~100 tok/s here, so an agent-scale prompt needs 5–15 minutes before its first token. Both
  ceilings must be raised — the smaller one wins.
- **`bufferLimit: 50Mi`.** Envoy's default is 32 KiB, and a base64 image or a long transcript
  exceeds it before the request reaches the model.
- **`logging.level: error`.** At `debug` Envoy dumps request headers.

## Configuration

One word in `.env` decides what this gateway serves. Compose interpolates from the **shell
environment first**, then `.env`.

```bash
GATEWAY_ENGINE=ollama
```

| Variable | Default | Used by |
|:--|:--|:--|
| `GATEWAY_ENGINE` | `lms` | **which engine this gateway serves** — one of `lms`, `unsloth`, `ollama`, `openrouter`, `openai`. Not a list. It is this project's alone: the other two have their own, and nothing checks that they agree |
| `AIGW_DEBUG` | `false` | per-request logging. **Never leave it empty** — aigw parses it as a bool and crash-loops on `""` before reading any config. See below |
| `UNSLOTH_API_KEY` | *(blank)* | **required** by every `unsloth-*` alias. Blank substitutes empty and every call 401s at request time |
| `OPENROUTER_API_KEY` | *(blank)* | every `openrouter-*` alias. **Real spend** |
| `OPENAI_API_KEY` | *(blank)* | every `openai-*` alias. **Real spend** |

**There is no `*_API_BASE` variable here**, unlike the other two projects. A `Backend` takes a
hostname and a port as separate fields — there is no URL to put in one variable. Change the
port in `config/<engine>.yaml`.

The provider keys stay blank in `.env` on purpose when your shell already exports them from an
encrypted store. See [`.env.example`](.env.example).

### Seeing what a request did

**With `AIGW_DEBUG=false` you see nothing per-request.** Envoy runs as a child of aigw, and its
stdout — where the JSON access log goes — lands in a file inside the container that no shell
can reach, because the image is distroless. `podman compose logs envoy` shows only the startup
lines, however much traffic you send. Verified 2026-09-04, both ways round.

Set it to `true` and you get one JSON line per request:

```json
{"gen_ai.request.model":"ollama-4b","gen_ai.response.model":"gemma4:e4b",
 "gen_ai.usage.input_tokens":17,"gen_ai.usage.output_tokens":64,
 "response_code":200,"duration":708,"upstream_host":"192.168.127.254:11434"}
```

…**and** aigw's own debug dump, which carries the **full prompt and response** with only the
Authorization header redacted. That is this gateway's equivalent of LiteLLM's Logs tab, and it
is also the reason not to leave it on.

## Auto-discovery

**This project does not have it**, and that is a gap rather than a decision. `../litellm`
carries a prober that asks the engine what it holds and adds one alias per model. Adding it
here needs two things that one did not:

1. **Another renderer.** LiteLLM's copy emits YAML `model_list` entries. This gateway needs
   `AIGatewayRoute` rules — a different shape entirely.
2. **Somewhere to run it.** The aigw image is distroless: no shell, no Python. A discovery
   one-shot here means a fourth image in the stack purely to run a script.

Until then, `config/<engine>.yaml` is the whole vocabulary, and it is the worked example of
configuring this gateway by hand.

## Tests

```bash
cd tests
uv run run_all.py                       # 7 rows against 26000
uv run run_all.py --only 6_codex_sdk    # one folder
uv run run_all.py --model lms-26b       # any alias, everywhere
```

`tests/` is **seven folders, one per way of calling this gateway**, ordered by distance from
the wire. Each is its own uv project; `uv run --directory` builds whichever venv is missing,
so a fresh clone needs no `uv sync`.

| Folder | Reaches this gateway through |
|:--|:--|
| `1_http_client` | `urllib` — no dependencies at all |
| `2_openai_client` | `openai` — 4 call kinds plus the contract test |
| `3_langchain_langgraph` | `ChatOpenAI(base_url=…)`, then the same loop built by hand |
| `4_deepagents` | a deep agent. Seven scenarios: query, todos, filesystem, tools, MCP, subagent, skill |
| `5_claude_agent_sdk` | `ANTHROPIC_BASE_URL` → **`/anthropic/v1/messages`**, on `<alias>-anthropic`. Seven scenarios: query, session, in-process MCP, stdio MCP, subagent, skill, thinking |
| `6_codex_sdk` | a `model_providers` override → **`/v1/responses`** |
| `7_opencode_sdk` | an `@ai-sdk/openai-compatible` provider |

**All seven run here**, and all seven run on `../litellm` too.

**The Claude Agent SDK folder needs the `-anthropic` pass-through alias, and refuses to run
without it.** Measured 2026-09-04, and the reason is the engine rather than this gateway: on a
plain alias `/anthropic/v1/messages` is TRANSLATED Anthropic → OpenAI, and the reply's own
`thinking` blocks — which Envoy builds out of the engine's `reasoning_content` — go straight
into the OpenAI body on the next turn. An OpenAI `content` part may only be `text` or
`image_url`, so the ENGINE answers `400 messages.N.content.str`. The identical error comes
back from Unsloth on port 8888 with no gateway in the path at all, and from LMStudio and
Ollama too. It was intermittent — about 1 run in 5 — because the engine emits
`reasoning_content` on some replies and not others.

`<alias>-anthropic` reaches an `Anthropic`-schema `AIServiceBackend`, so the body goes
upstream untranslated. **All three local engine configs now carry two of them**, because all
three engines serve `POST /v1/messages` natively (verified 2026-09-04, 200 from each).
`MAX_THINKING_TOKENS=0` used to be required here and no longer is. Full note:
`tests/5_claude_agent_sdk/README.md`.

It drives **this gateway only**. `2_openai_client/04_gateway_contract.py` asserts the four
claims `common.py` makes about how to call it, and **this gateway is not a copy of the other
one**: it lists its models like LiteLLM and checks no caller key at all.

| | LiteLLM | **Envoy** |
|:--|:--|:--|
| `checks_api_key` | True | **False** |
| `lists_models` | True | **True** |
| `echoes_alias` | True | **False** |
| `exposes_route_limits` | True | **False** |

What is deliberately not covered is in [`tests/README.md`](tests/README.md).

## Troubleshooting

| Symptom | Cause | Fix |
|:--|:--|:--|
| The container restarts in a loop, log says `--debug: bool value must be true, 1, yes, false, 0 or no but got ""` | `AIGW_DEBUG` is set to an empty string | set it to `false`, or remove the line |
| `Connection reset by peer` right after `up -d` | the data plane needs a few seconds after the admin port answers | probe `26000/v1/models`, not `26064/health` |
| The container restarts in a loop, log names a config file | `GATEWAY_ENGINE` is misspelled | `podman compose logs envoy` names the file it could not open |
| An alias 404s | no `AIGatewayRoute` rule matches it — you are calling another engine's name, or it is not in this engine's config | `curl localhost:26000/v1/models` for the names this engine serves |
| `openrouter-free` 404s | **by design** — this gateway has no `extra_body`, so it cannot carry the provider pin | use it on 24000 |
| Nothing in `podman compose logs envoy` after a request | `AIGW_DEBUG` is `false` | set it to `true` and repeat the request |
| Every call 401s on `unsloth-*` | `UNSLOTH_API_KEY` was blank when `up -d` ran, so `${UNSLOTH_API_KEY}` substituted empty | export it, run `up -d` again |
| A large prompt or a base64 image fails before reaching the model | the `ClientTrafficPolicy` buffer limit was removed or lowered | it must stay at `50Mi`; Envoy's default 32 KiB is too small |
| An unbounded reply that runs for minutes | you sent no `max_tokens` | [always send one](#always-send-max_tokens) |
| `compose exec` fails with "no such file" | the image is **distroless** — no shell, no `sh`, nothing to exec into | use `compose logs`; the generated Envoy config is inside the container at `~/.local/state/aigw/runs/0/` |
| A 400 on an `openai-*` route that works on 24000 | the gpt-5 family rejects `max_tokens`, and this gateway forwards parameters as sent | send `max_completion_tokens` |

## Layout

```text
envoy/
├── compose.yml             ONE service. name: ai-gateway-envoy
├── .env.example            tracked; the key lines are blank BY DESIGN
├── config/                 mounted at /etc/aigw, read-only
│   └── <engine>.yaml           lms · unsloth · ollama · openrouter · openai
│                                Kubernetes custom resources, ~230 lines each
└── tests/                  SEVEN folders, one per way of calling this gateway
    ├── gateway.py              base URL · key · alias, shared by all seven. stdlib only
    ├── run_all.py              runs every folder, one row each
    ├── 1_http_client/          urllib, NO dependencies
    ├── 2_openai_client/        openai — 4 call kinds + the contract test
    ├── 3_langchain_langgraph/  LangChain's agent, and the same loop by hand
    ├── 4_deepagents/           a deep agent. SEVEN scenarios + its own run_all.py
    ├── 5_claude_agent_sdk/     the ANTHROPIC surface, /anthropic/v1/messages.
    │                            SEVEN scenarios + its own run_all.py
    ├── 6_codex_sdk/            the RESPONSES surface, /v1/responses
    └── 7_opencode_sdk/         an openai-compatible provider over the HTTP server API
```

**The mount is `/etc/aigw` and not `/app`.** `/app` *is* the binary in this image — the
Dockerfile copies the CLI there and sets it as the entrypoint — so mounting a directory over it
replaces the program with a folder.

There is no `discover/` here; see [Auto-discovery](#auto-discovery) above.
