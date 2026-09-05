# TESTING.md — where the testing stands, and what is left

**Started 2026-09-04. Last measured 2026-09-05.** This file is a handover. It says exactly
what was tested, with which model, and what happened — so the next person does not repeat
work or trust a claim that was never measured.

Where a result is missing, it says **not tested** rather than guessing.

- **§2** is **the exact versions** everything was measured on. Read it first.
- **§5** is **every bug we are facing and have NOT fixed.**
- **§6** is **every bug we fixed, and how.**

## If you are picking this up cold

You do not need the conversation that produced this file. Everything is here. Work like this:

1. **Read §2 and compare it with what is running now.** Most entries below are version-bound.
   A bug measured on LiteLLM 1.99.1 or an aigw image from 2026-08-28 may simply be gone.

   ```bash
   podman exec ai-gateway-litellm-1 sh -lc 'ls -d /app/.venv/lib/python3.13/site-packages/litellm-*.dist-info'
   podman exec ai-gateway-envoy-envoy-1 /app version
   podman image inspect docker.io/envoyproxy/ai-gateway-cli:latest --format 'created={{.Created}} digest={{.Digest}}'
   ```

2. **Every §5 entry ends with "WHAT A FUTURE AGENT SHOULD DO".** Start there. Each one names
   the upstream issues to re-check, the one-command reproduction, and the workaround if there
   is one.

3. **Re-check the upstream issue states before trusting any of them.** They were checked on
   the date each entry names, and **a closed issue does not mean the bug is fixed for us** —
   §6.1 is the worked example: two issues had closed before the bug was even measured, and
   neither fixed it. `gh issue view <n> --repo <owner>/<repo> --json state,title,closedAt`.

4. **When you find something new, add it here** in the same shape: symptom, a reproduction
   someone can paste, cause, the upstream issues with their state and the date you checked,
   what you tried that did NOT work, and what the next person should do. **Record the
   versions.** An entry without a version cannot be retired by anyone.

5. **Do not delete an entry when it is fixed — move it from §5 to §6** and say how it was
   fixed. The failed attempts are worth as much as the fix; they are what stops the next
   person spending an evening on a dead end.

---

## 1. What the suite is

Two standalone gateways, each with its own `tests/` directory of **seven folders**, one per
way of calling the gateway:

| Folder | Scenarios | Drives the gateway with |
|:--|--:|:--|
| `1_http_client` | 1 (`main.py`) | `urllib` — no dependencies at all |
| `2_openai_client` | 4 | the `openai` client |
| `3_langchain_langgraph` | 1 (`main.py`) | `ChatOpenAI(base_url=…)`, then the same loop by hand |
| `4_deepagents` | **7** | a DeepAgents deep agent |
| `5_claude_agent_sdk` | **7** | the Anthropic Messages API |
| `6_codex_sdk` | **4** | the OpenAI Responses API |
| `7_opencode_sdk` | **5** | OpenCode's HTTP server API |
| **total** | **29 per gateway · 58 across both** | |

```
4_deepagents        01_query 02_todos 03_filesystem 04_tools 05_mcp 06_subagent 07_skill
5_claude_agent_sdk  01_query 02_session 03_sdk_mcp 04_stdio_mcp 05_subagent 06_skill 07_thinking
6_codex_sdk         01_query 02_session 03_structured 04_mcp
7_opencode_sdk      01_query 02_session 03_agent 04_mcp 05_structured
```

In every rebuilt folder the numbered scenarios, `run_all.py` and `mcp_server.py` are
**byte-identical between `litellm/` and `envoy/`**. Only `common.py`, `gateway.py` and
`04_gateway_contract.py` differ, and those three are the files allowed to know which gateway
they are talking to.

---

## 2. Versions, and which model each alias is

### The exact versions everything below was measured on

**Record these with every bug. A future reader's first question is "is this still true on a
newer build", and none of it can be answered without them.**

| Component | Identifier | Notes |
|:--|:--|:--|
| **LiteLLM** | **1.99.1** | image `ghcr.io/berriai/litellm:main-stable`, built **2026-09-02**, digest `sha256:2d0f1079…`. Upgraded from 1.95.0 (built 2026-08-02) on 2026-09-05 |
| **Envoy AI Gateway** | **`dev`** — see below | image `docker.io/envoyproxy/ai-gateway-cli:latest`, built **2026-08-28**, digest `sha256:f5702fe9dc7ce75ba79cfc2de64d61943e0994d7d071e4e33ca00dff48952c86` |
| Nearest aigw release | **v1.1.0**, 2026-08-21 | the last tagged release before that image was built |
| `claude` CLI | whatever npm has | `npm install -g @anthropic-ai/claude-code` |
| `openai-codex` | **0.147.0** | PyPI has only 5 releases; **no 0.116.x** — see §5.1 |

> **`aigw version` PRINTS `dev`, NOT A SEMVER.** The `:latest` tag is built from `main`, so
> the binary cannot tell you which release you have. **The image digest and build date above
> are the only stable handle** — quote those, not "latest". To find what you are actually on,
> compare the build date against
> <https://aigateway.envoyproxy.io/release-notes/>.
>
> ```bash
> podman exec ai-gateway-envoy-envoy-1 /app version          # -> "Envoy AI Gateway CLI: dev"
> podman image inspect docker.io/envoyproxy/ai-gateway-cli:latest \
>   --format 'digest={{.Digest}} created={{.Created}}'
> ```
>
> `/app` **is** the binary, not a directory — `/app/aigw` does not exist, and there is no
> shell in the image.

The LiteLLM upgrade took a `pg_dump` first; Prisma reported **"No pending migrations to
apply"**, so there was no schema change, and **4 virtual keys and 3048 spend rows survived
unchanged**.

| Alias | Model | Provider prefix | Engine |
|:--|:--|:--|:--|
| `lms-4b` | `google/gemma-4-e4b` | `lm_studio/` | LM Studio, host :1234 |
| `lms-26b` | `google/gemma-4-26b-a4b-qat` | `lm_studio/` | LM Studio |
| `lms-embed` | `text-embedding-nomic-embed-text-v1.5` | `lm_studio/` | LM Studio |
| `unsloth-4b` | `unsloth/gemma-4-E4B-it-qat-GGUF` | `openai/` | Unsloth Studio, host :8888 |
| `unsloth-26b` | `unsloth/gemma-4-26B-A4B-it-qat-GGUF` | `openai/` | Unsloth Studio |
| `unsloth-embed` | `second-state/Nomic-embed-text-v1.5-Embedding-GGUF` | `openai/` | Unsloth Studio |
| `ollama-4b` | `gemma4:e4b` | `openai/` | Ollama, host :11434 |
| `ollama-26b` | `gemma4:26b` | `openai/` | Ollama |
| `ollama-embed` | `nomic-embed-text` | `openai/` | Ollama |
| `openrouter-26b` | `google/gemma-4-26b-a4b-it` | `openrouter/` | OpenRouter — **paid** |
| `openai-mini` | `gpt-5.4-mini` | `openai/` | OpenAI — **paid**, **HAS VISION** |
| `openai-embed` | `text-embedding-3-small` | `openai/` | OpenAI — **paid** |

**THE PROVIDER PREFIX COLUMN IS NOT DECORATION.** LiteLLM routes on it, and `/v1/messages`
behaves differently for `openai/` than for the others — §6.1.

**`<alias>-anthropic` variants exist on Envoy only** (`lms-*`, `unsloth-*`, `ollama-*`).
`5_claude_agent_sdk` requires one and refuses to run without it.

---

## 3. Coverage matrix — what has actually been run

`✅` = every folder in scope passed. `❌` = **not tested**.

| Engine | LiteLLM 24000 | Envoy 26000 | Alias | Scope | Measured |
|:--|:--|:--|:--|:--|:--|
| **lms** | ✅ **7/7** | ✅ **7/7** | `lms-4b` | all seven folders | 2026-09-05 00:06 |
| **ollama** | ✅ **7/7** | ✅ **7/7** | `ollama-4b` | all seven folders | 2026-09-05 00:11 |
| **unsloth** | ✅ **7/7** | ✅ **7/7** | `unsloth-4b` | all seven folders | 2026-09-05 00:21 |
| **openrouter** | ✅ **7/7** | ✅ **7/7** | `openrouter-26b` | all seven folders | 2026-09-05 02:05 |
| **openai** | ✅ **7/7** | **5/7** — §5.2 and §5.3 | `openai-mini` | all seven folders | 2026-09-05 02:10 |

**THE LOCAL MATRIX IS COMPLETE AND GREEN — six cells, 7/7 each, 42 folder-runs**, in one
uninterrupted pass on LiteLLM 1.99.1, 00:06 to 00:27, with nothing else touching the machine.

**ALL SEVEN FOLDERS RUN ON BOTH PAID ENGINES. LiteLLM IS 7/7 ON BOTH, AND SO IS ENVOY ON
OPENROUTER.** Only two cells are red, both on Envoy + OpenAI, and both are upstream:

| Cell | Why |
|:--|:--|
| `openai` + Envoy, folder 5 | **§5.2** — Envoy forwards Anthropic's `thinking` to OpenAI, which rejects it. `MAX_THINKING_TOKENS=0` gives 6/7; not wired in, so the gap stays visible |
| `openai` + Envoy, folder 7 | **§5.3** — OpenCode sends `max_tokens`, which GPT-5.x rejects, and Envoy does not rewrite it. An OPEN OpenCode bug |

**`3_langchain_langgraph` was the last gap and is now closed** — it had never been run on
either paid engine. PASS on all four combinations, 2026-09-05.

Both paid engines were also verified with **`GATEWAY_DISCOVERY=true`** left on, which is the
case §6.6 fixed.

**What the paid runs cost:** OpenRouter **$0.051635** for the whole session
(2.337468 → 2.389103), agent loops included. OpenAI has no equivalent cheap endpoint; the runs
were a few hundred small `gpt-5.4-mini` requests. **Neither engine cost more than a few
cents**, which is worth knowing before anyone avoids testing them again.

### Why the 2026-09-04 cells could not be trusted — discard them

A `matrix.sh` left running by the previous session kept `sed`-ing both `.env` files and
restarting both gateways **mid-run**, so suites died with "gateway is not answering", and one
folder called `lms-4b` against a gateway just switched to `ollama`. Its parent Claude session
was still alive and **relaunched the script twice after it was killed**. The whole session
tree had to be killed before a trustworthy matrix was possible. See the first house rule
in §10.

---

## 4. Spot checks worth not repeating

| Check | Result |
|:--|:--|
| `OPENAI_API_KEY` | **works** — `GET https://api.openai.com/v1/models` → 200, 170 models |
| `OPENROUTER_API_KEY` | **works** — paid tier, **$2.337691** used at 2026-09-05 01:10, no limit |
| Both keys' source | already exported into the shell by `~/Projects/.envrc`; nothing to decrypt |
| `response_format: json_schema` on the OpenAI route | honoured by **both** gateways with `unsloth-4b`, 3/3 each |
| Envoy `/v1/responses` | works with Codex 0.147 (folder 6 passes) |
| `openrouter-26b` through Envoy + Codex | called an MCP tool correctly on the first try |
| LiteLLM upgrade 1.95.0 → 1.99.1 | no pending migrations, no data loss, **did not fix §6.1 on its own** |

---

## 5. OPEN — bugs we are facing and have NOT fixed

### 5.1 Codex cannot call MCP tools — BOTH UPSTREAM ISSUES STILL OPEN

Re-checked with `gh` on 2026-09-05:

| Issue | State |
|:--|:--|
| [openai/codex#19871](https://github.com/openai/codex/issues/19871) — MCP invocation regressed for custom providers since 0.117.0 | **OPEN** |
| [openai/codex#24135](https://github.com/openai/codex/issues/24135) — no way to approve MCP calls non-interactively | **OPEN** |
| [envoyproxy/ai-gateway#2586](https://github.com/envoyproxy/ai-gateway/issues/2586) — Envoy 400s Codex 0.116's payload | **CLOSED 2026-08-26** |

**Proven here**: codex-cli 0.116.0 calls the tool; 0.147.0 does not. `04_mcp.py` therefore
asserts the **wiring** — Codex spawns the server, handshakes, reads `tools/list` — and prints
the bug link every run. When the two open issues close, turn it into an assertion.

**#2586 closing removes one blocker to pinning 0.116.0; the other still stands.** The aigw
image in use already contains that fix, so Envoy would now accept the payload — but **PyPI
has no 0.116.x**. `openai-codex` has five releases in total: `0.1.0b1`, `0.1.0b2`, `0.1.0b3`,
`0.144.4`, `0.147.0`. The Python SDK cannot drive that runtime, so the pin is still not an
option.

### 5.2 Envoy sends Anthropic's `thinking` straight to OpenAI, which rejects it

**Affects:** Envoy 26000 + any `openai-*` alias + any Anthropic-protocol client
(`tests/5_claude_agent_sdk`, and Claude Code itself).
**Does NOT affect:** LiteLLM, which is **7/7** on the same folder and alias. Nor Envoy with
`openrouter-*` or the three local engines — those reach a backend that speaks Anthropic
natively, so nothing is translated. See §6.9.

**Symptom.** Every scenario in folder 5 fails in about a second:

```
API Error: 400 Unknown parameter: 'thinking'.
```

**Reproduce it in one call** (Envoy on `GATEWAY_ENGINE=openai`):

```bash
curl -sX POST http://localhost:26000/anthropic/v1/messages \
  -H 'Content-Type: application/json' -H 'anthropic-version: 2023-06-01' \
  -d '{"model":"openai-mini-anthropic","max_tokens":2048,
       "thinking":{"type":"disabled"},
       "messages":[{"role":"user","content":"What is 17*23?"}]}'
```

**All three forms fail, `disabled` included** — measured 2026-09-05:
`{"type":"enabled","budget_tokens":1024}`, `{"type":"adaptive"}`, `{"type":"disabled"}`.
That is what makes it a translator gap rather than a bad parameter value.

**Cause, and it is a deliberate upstream design decision, not an oversight.** Envoy's
Anthropic→OpenAI translator **passes the `thinking` field through verbatim**. From the merged
PR that added it, [envoyproxy/ai-gateway#2099](https://github.com/envoyproxy/ai-gateway/pull/2099)
(merged **2026-06-02**, shipped in **v0.7.0**), describing the request direction
`/v1/messages` → `/v1/chat/completions`:

> "Pass through thinking config (enabled/disabled/adaptive) to the backend"

That is correct for a vLLM- or SGLang-style backend that understands such a field. **It is
wrong for api.openai.com**, whose Chat Completions API has no `thinking` parameter at all —
its equivalent is `reasoning_effort` — so the request is rejected outright.

**Upstream issue status, checked 2026-09-05:**

| Issue | State | Relevance |
|:--|:--|:--|
| [#2098](https://github.com/envoyproxy/ai-gateway/issues/2098) — Translator: reasoning and image support for `/v1/messages` → `/v1/chat/completions` | **CLOSED** 2026-05-03, fixed by #2099 | this is what INTRODUCED the pass-through behaviour |
| [#2099](https://github.com/envoyproxy/ai-gateway/pull/2099) | **MERGED** 2026-06-02 | the PR whose description states the pass-through decision |
| [#2277](https://github.com/envoyproxy/ai-gateway/issues/2277) — translate reasoning config (`thinking`/`reasoning_effort`) to vLLM / OpenAI-compatible backends | **OPEN** since 2026-06-23, no assignee, no PR, no milestone | **closest match, but not the same case** — it is about the OpenAI→OpenAI passthrough translator and self-hosted vLLM, not Anthropic→api.openai.com |

**NO UPSTREAM ISSUE DESCRIBES OUR EXACT SYMPTOM.** Searched 2026-09-05 across all states for
`Unknown parameter`, `api.openai.com anthropic messages`, `thinking field backend openai
reject`, `anthropic thinking request translation openai` — **zero results**. So this is very
likely **unreported**, and filing it is a reasonable next step. If you file it, the one-call
repro above plus the #2099 quote is the whole report.

**Measured workaround.** `MAX_THINKING_TOKENS=0` stops the Claude CLI sending the field, and
the repo already documents that variable for Claude Code in
[`litellm/README.md`](litellm/README.md) § Use it from Claude Code:

```bash
cd envoy/tests && MAX_THINKING_TOKENS=0 uv run run_all.py --only 5_claude_agent_sdk --model openai-mini
```

**0/7 → 6/7.** The one that still fails is `05_subagent` — "the subagent ran but its answer
did not survive the join into the parent conversation" — which looks like `gpt-5.4-mini`
behaviour rather than a gateway fault and has **not** been investigated.
`07_thinking` PASSES under the workaround, and honestly: it reports that the route produces
no reasoning to carry (§6.8).

**The workaround is NOT wired in.** Folder 5 is left failing on Envoy + `openai-mini` so the
gap stays visible, per this repo's rule — *prove a gap, never shim it*. Wiring it in is a
one-line change to `envoy/tests/5_claude_agent_sdk/common.py` if you decide the green row is
worth more than the visible gap.

**WHAT A FUTURE AGENT SHOULD DO, in order:**

1. **Check the versions** in §2 against what is running now. If the aigw image is newer,
   re-run the one-call repro above before reading any further — it may simply be fixed.
2. **Re-check #2277's state**, and search again for our symptom; someone may have filed it.
3. If still broken and still unreported, **file it** with the repro above.
4. Re-read the [release notes](https://aigateway.envoyproxy.io/release-notes/) for any
   mention of `thinking`, `reasoning_effort` or Anthropic→OpenAI translation.

### 5.3 Envoy + `openai-*` breaks any client that sends `max_tokens` — OpenCode does

**Affects:** Envoy 26000 + any `openai-*` alias + a client that sends `max_tokens` on
`/v1/chat/completions`. Today that is `tests/7_opencode_sdk`.
**Does NOT affect:** LiteLLM — the same folder is **green** there on the same alias.

**Symptom.** All five scenarios in folder 7 fail:

```
400 Unsupported parameter: 'max_tokens' is not supported with this model.
    Use 'max_completion_tokens' instead.
```

**Cause.** OpenAI's reasoning-model family (GPT-5.x, o1, o3, o4) **renamed the parameter**.
Two independent halves:

1. **OpenCode sends the old name.** Its bundled `@ai-sdk/openai-compatible` provider emits
   `max_tokens` for an OpenAI-compatible endpoint, and OpenCode cannot tell that the endpoint
   is really api.openai.com behind a proxy.
2. **Envoy does not rewrite it.** It is a pass-through: OpenAI schema in, OpenAI schema out,
   no translation, so the body reaches OpenAI unchanged. **LiteLLM rewrites it and you never
   see the problem** — which is exactly why this only shows up on one of the two gateways.

**Upstream issue status, checked 2026-09-05 — it is OPEN and it is OpenCode's:**

| Issue | State | Note |
|:--|:--|:--|
| [anomalyco/opencode#40885](https://github.com/anomalyco/opencode/issues/40885) — "OpenAI-compatible GPT-5.x models still send `max_tokens` on AI SDK fallback path" | **OPEN** since 2026-08-06 | **the live one**, and "still" says earlier fixes missed this path |
| [anomalyco/opencode#25096](https://github.com/anomalyco/opencode/issues/25096) — openai-compatible adapter sends `max_tokens` to GPT-5/o-series | CLOSED 2026-04-30 | did not cover the fallback path |
| [anomalyco/opencode#5421](https://github.com/anomalyco/opencode/issues/5421) — `@ai-sdk/openai-compatible` max_tokens error for GPT 5.x | CLOSED 2025-12-12 | the original |
| [vercel/ai#11828](https://github.com/vercel/ai/issues/11828) | see issue | same class, AI SDK side |

Fixes proposed upstream: detect reasoning models by id prefix (`gpt-5*`, `o1*`, `o3*`, `o4*`)
and switch the parameter, or expose a per-provider `max_tokens_param` config knob. **Neither
has landed**, so there is nothing to configure in `7_opencode_sdk/common.py` today.

**Not worked around, deliberately.** Our own scripts WERE adapted — §6.5 made
`envoy/tests/gateway.py` send `max_completion_tokens` for `openai-*`, which is why folders 1
and 2 pass. **OpenCode is a third-party client and there is nothing on our side to change**,
and adapting the test would hide a limitation that a real user hits the moment they point an
agent at Envoy with a hosted OpenAI model. *Prove a gap, never shim it.*

**WHAT A FUTURE AGENT SHOULD DO:**

1. **Re-check #40885.** If it closed, upgrade OpenCode and re-run
   `cd envoy/tests && uv run run_all.py --only 7_opencode_sdk --model openai-mini`.
2. **Check whether OpenCode gained a per-provider parameter knob** — if it did, set it in
   `envoy/tests/7_opencode_sdk/common.py` § `config_for`, which is where the provider block
   is built.
3. **Or check whether Envoy gained request body mutation** —
   [envoyproxy/ai-gateway#1985](https://github.com/envoyproxy/ai-gateway/issues/1985) ("Support
   JSON merging request body mutation … and dynamic value mutation", **OPEN** since
   2026-03-25) is the feature that would let the gateway rename the field itself. That would
   fix it for every client at once.

### 5.4 Unsloth returns a 500 on some vision calls — engine side, do not chase

`The model produced output that does not match the expected peg-gemma4 format`, from
`2_openai_client/03_multimodal.py`. Passed 3/3 on retry when it appeared on 2026-09-04, and
**did not reappear anywhere in the 2026-09-05 runs.** Re-run first; only investigate if it
repeats.

---

## 6. FIXED — what was wrong, and how

### 6.1 LiteLLM dropped reasoning on `/v1/messages` — and NOT because of the issues that closed

**The fix is one line** in `litellm/config/settings.yaml`, carrying the full four-field
header:

```yaml
use_chat_completions_url_for_anthropic_messages: true
```

**Cause.** `/v1/messages` picks its upstream path by **provider**, from one frozen set in
`llms/anthropic/experimental_pass_through/messages/handler.py`:

```python
_RESPONSES_API_PROVIDERS: Final = frozenset({"openai"})
```

A provider in that set is bridged through the **Responses API**, and that bridge does not
carry `reasoning_content`. Our aliases split exactly on that line — `lms-*` is `lm_studio/`
and was never affected; `ollama-*`, `unsloth-*` and `openai-*` are `openai/` and were. That
is why it looked engine-specific for a month.

**Measurements**, LiteLLM 1.99.1, `unsloth-4b`:

| Path | Before | After |
|:--|:--|:--|
| `/v1/chat/completions` | 5/5 carried `reasoning_content`, 985–1701 chars | unchanged |
| `/v1/messages`, non-streaming | **0/5** | **4/5** |
| `/v1/messages`, streaming — what the SDK uses | **0/5** | **6/6** |
| `07_thinking.py` through the real SDK | failed | **3/3 PASS** |

**THE TWO CLOSED ISSUES ARE NOT THE CURE.**
[#29518](https://github.com/BerriAI/litellm/issues/29518) closed 2026-07-29 and
[#27946](https://github.com/BerriAI/litellm/issues/27946) closed 2026-08-24 — both **before**
this was measured. #29518's fix already shipped in 1.95.0, where the bug still reproduced
0/5. The adapter's `reasoning_content` fallback was proven **correct in isolation** first,
which is how the search narrowed from translation to routing.

**Tried and rejected:** the image upgrade on its own (0/5), and
`model_info.supports_reasoning: true` (0/3).

**Guard.** `5_claude_agent_sdk/common.py` now declares a flat `THINKING_REACHES_CLIENT = True`
on both gateways — the per-engine table is gone, it was a symptom. Delete the config line and
the `ollama` and `unsloth` rows go red on the next run.

### 6.2 `6_codex_sdk/03_structured` was flaky

The local engines do not enforce `text.format` on `/v1/responses`, so the model's decoration
varies run to run: a bare object, a ```` ```json ```` fence, or a sentence first. A
fence-only strip was **intermittent** — it passed 6 runs out of 6 by hand and still failed
inside the matrix.

**Fix.** `03_structured.py` now **searches the reply for its first JSON object** instead of
requiring the reply to be one. Nine reply shapes were unit-tested, including the two that
must still fail: prose-only and empty. A gateway that drops `output_schema` returns a
sentence with no object, and that still fails — so the scenario still proves what it exists
to prove.

### 6.3 "gpt-5.4-mini has no vision" was FALSE, and it made the openai engine untestable

`tests/gateway.py` mapped `"openai": None` on that belief. The `None` made the module raise
**at import time**, so every folder died in 0.0 s and the engine could not be tested at all.

**`gpt-5.4-mini` has vision.** `03_multimodal.py` passes against it 4/4 — and that scenario
sends a real base64 PNG of a red circle and requires both `"red"` and a round-shape word
back, so a model ignoring the image cannot pass it.

**Fix.** `"openai": "openai-mini"` in both `gateway.py` files, and the now-dead `is None`
branch deleted.

### 6.4 `--model` was ignored on any engine whose default alias was `None`

The error message told you to "pass `--model openai-mini` explicitly" — but `gateway.py`
resolves the alias at **import** time, before any scenario's argparse runs, so the `--model`
it recommended had already been ignored. The message contradicted itself.

**Fix, two parts.** `tests/run_all.py` now exports `AI_GATEWAY_TEST_MODEL` into the child
environment whenever `--model` is given — that is the one hook `gateway.py` reads first, so
`--model` now works exactly as documented. And the error message names both forms honestly,
including the env var needed when running a single scenario directly.

### 6.5 Envoy + `openai-mini` returned 400 on every call — parameter naming

```
400 Unsupported parameter: 'max_tokens' is not supported with this model.
    Use 'max_completion_tokens' instead.
```

OpenAI's newer models reject `max_tokens`. **LiteLLM renames it upstream and you never see
this; Envoy is a pass-through and does not** — so the caller must send what the upstream
actually accepts. That is a real difference in the calling contract, not a bug in either
gateway.

**Fix.** `envoy/tests/gateway.py` builds `BODY_EXTRAS` from the alias —
`max_completion_tokens` for `openai-*`, `max_tokens` otherwise — and
`04_gateway_contract.py` gains a `ceiling()` helper that reads the key out of
`gateway.body_extras` rather than hardcoding a name. **No scenario branches on the gateway's
name**; the difference stays in the declared contract, as the repo's rules require.
Regression-checked on `unsloth-4b`: 4/4 on both gateways afterwards.

### 6.6 `GATEWAY_DISCOVERY` set + a PAID engine crash-looped LiteLLM

**Symptom.** With `GATEWAY_DISCOVERY=true` — the value in this repo's `.env` — and
`GATEWAY_ENGINE=openrouter` or `openai`, LiteLLM never came up. Every suite then failed in
0.0 s with "the gateway is not answering", which reads as a dead proxy rather than a config
problem.

```
ai-gateway-discover-1   Exited (2)
litellm-1  | Exception: Config file not found: /app/config/discovered-openrouter.yaml
```

**Cause.** Discovery refuses paid engines by name — money is never discovered, and that part
was right. But it refused by **exiting 2**, so the file was never written, while `compose.yml`
had already built `--config .../discovered-<engine>.yaml` from
`${GATEWAY_DISCOVERY:+discovered-}`, which only reacts to the variable being non-empty. The
proxy was pointed at a file that was deliberately not created.

**Fix.** `discover/gateway_discovery.py` gains a `PAID_ENGINES` tuple and a
`render_passthrough()`. A paid engine is now a **no-op, not an error**: nothing is
enumerated, and a pass-through `discovered-<engine>.yaml` is written that includes
`settings.yaml` and the hand-written `<engine>.yaml` and adds no models. Discovery decides
WHAT is served, never WHETHER the gateway runs.

**Verified 2026-09-05, with `GATEWAY_DISCOVERY=true` throughout:**

| Check | Result |
|:--|:--|
| `openrouter` — `discover` exit code | **0** (was 2) |
| `openrouter` — aliases served | `openrouter-26b`, `openrouter-free` |
| `openrouter` — real call, `1_http_client` | **PASS** |
| `openai` — `discover` exit code | **0** |
| `openai` — aliases served | `openai-mini`, `openai-embed` |
| `openai` — real call, `1_http_client` | **PASS** |
| `unsloth` — regression, discovery still ADDS | 24 discovered aliases, all 3 hand-written kept |

The master key still resolves on the pass-through, which proves `settings.yaml` is loaded —
the failure mode the repo warns about when an included file carries its own `include:`.

### 6.7 Codex could not use `openrouter-26b` on LiteLLM — our own pin, not OpenRouter

**Symptom.** All four `6_codex_sdk` scenarios failed in about a second with
`429 Too Many Requests`, on LiteLLM only. Envoy was green with the same alias.

**THE SYMPTOM LIES.** The 429 came from LiteLLM's own router, not OpenRouter:
`No deployments available for selected model ... cooldown_list=[...]`. The FIRST call had
failed with a 404, which put the deployment into cooldown, and every call for the next few
seconds then reported a rate limit that did not exist. **Read the first failure, never the
repeat.**

**The real error**, from `https://openrouter.ai/api/v1/responses`:

```
404 No endpoints found that can handle the requested parameters
    routing_funnel: Initial Endpoints 9 -> Filter by Tool Compatibility 7
    failed_routing_step: "Filter by Parameters"
```

**Cause, isolated by calling OpenRouter directly** (2026-09-05, `google/gemma-4-26b-a4b-it`):

| Request | Result |
|:--|:--|
| plain | 200 |
| `tools` | 200 |
| `tools` + `provider.require_parameters` | 200 |
| `tools` + `parallel_tool_calls` | 200 |
| `tools` + `parallel_tool_calls` + `require_parameters` | **404** |

Codex sends `parallel_tool_calls` on every call; **no** OpenRouter provider for these weights
supports it; and **our own** `require_parameters: true` turns "cannot honour it" into a hard
refusal instead of dropping it. Envoy was unaffected because it has no `extra_body`, so it
never sends the pin — the one time that documented gap helped.

**Fix.** `additional_drop_params: ["parallel_tool_calls"]` on the `openrouter-26b` deployment
in `config/openrouter.yaml`, carrying the four-field header. It is **per-alias, not global**,
and it **keeps the pin** — the pin is what stops a provider returning tool calls as raw text,
and dropping one unsupported parameter is much the smaller price. `6_codex_sdk` went 0/4 → 4/4.

### 6.8 `07_thinking` called "the model does not reason" a gateway bug

`THINKING_REACHES_CLIENT` was a flat declaration, so the scenario could not tell a gateway
that **lost** the reasoning from a model that **never produced any**. `openrouter-26b` is the
second — 0 characters of `reasoning_content` on `/v1/chat/completions` too — and the row went
red as though the gateway had dropped something.

**Fix.** `07_thinking.py` now measures its own baseline first: it asks the OpenAI route what
that route produces, and only then asserts. If the baseline is 0 there is nothing to carry
and nothing to assert; if it is non-zero, the assertion runs and its failure message names
the config flag from §6.1. **No table, no per-engine list** — the test calibrates itself, so
a new alias needs no declaration. The file stays byte-identical across both projects.

Verified 2026-09-05: `openrouter-26b` PASS with "this route produces no reasoning at all",
`unsloth-4b` still PASS with the assertion live, folder 5 green on both.

### 6.9 Envoy served no `-anthropic` alias for either paid engine

**Symptom.** `tests/5_claude_agent_sdk` exited immediately on Envoy for both paid engines:
`'openrouter-26b-anthropic' is not among the aliases this gateway serves.` The folder
resolves `<alias>-anthropic` at runtime and refuses to run without one — by design, because
on the three local engines a missing route means an unfinished config file.

**Cause.** The `-anthropic` pass-through aliases had only ever been written for the three
LOCAL engines. Nobody had checked whether the paid ones could have them.

**They can, and the two needed OPPOSITE shapes** — which is the part worth remembering:

| Alias | Backend schema | Why |
|:--|:--|:--|
| `openrouter-26b-anthropic` | **`Anthropic`** — a second `AIServiceBackend`, `prefix: /api/v1` | **OpenRouter serves the Anthropic Messages API natively** at `POST /api/v1/messages`, which it calls the "Anthropic skin". Nothing is translated, exactly like the local engines |
| `openai-mini-anthropic` | **`OpenAI`** — the existing backend, no new one | **api.openai.com serves no Anthropic route at all**, so translation is the only option. The route takes Anthropic in (the input schema comes from the PATH) and Envoy translates onto the OpenAI schema |

**Proof the OpenRouter one really is a pass-through**: the reply carries OpenRouter's own
Anthropic response shape, which Envoy could not have assembled —
`{"id":"gen-1788565552-…","usage":{"output_tokens_details":{"thinking_tokens":0}}}`.

**A trap that cost a 401 in testing.** OpenRouter's `BackendSecurityPolicy` targets
`AIServiceBackend` by name, so the NEW backend had to be added to `targetRefs`. Miss it and
the `-anthropic` alias gets 401 while the plain alias beside it works — which reads as a
broken alias, not a missing target. There is now a comment in the file saying so.

**Result.** **Envoy + OpenRouter went from 6/7 to 7/7.** Envoy + OpenAI resolves the alias
and then hits §5.2, which is a different, upstream problem.

**Sources for the two facts that made this possible** (found by web search 2026-09-05, after
a month of assuming paid engines simply could not have these aliases):

- OpenRouter's Anthropic endpoint —
  <https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-messages>
- Envoy's Anthropic→OpenAI translation, shipped in v0.7.0 —
  <https://aigateway.envoyproxy.io/release-notes/>

---

## 7. How config fixes are kept straight

Added 2026-09-05, after a global flag was set for one client with no record of who it was
for. Three parts; the rule is in
[`.claude/rules/05-implement.md`](.claude/rules/05-implement.md) § Settings that exist for
one client.

1. **Every non-obvious setting carries a four-field header** — `WHY`, `SCOPE`,
   `GLOBAL BECAUSE`, `PROVEN` / **`GUARDED BY`**. `GUARDED BY` names the test that goes red
   if the line is deleted, and it is not optional.
2. **[`litellm/README.md`](litellm/README.md) § Provider × route is the memory** — one small
   table, provider against route, plus a *tried and rejected* list.
3. **Never revert a fix to make another client pass.** Measure both directions, record both,
   keep both assertions. If a client genuinely needs the opposite, give it its own alias with
   `model_info.supported_endpoints: ["/v1/messages"]` — that lever *is* per-alias, and it is
   the same shape as Envoy's `<alias>-anthropic` aliases.

The caller-facing answer stays in one place: the alias table in [`README.md`](README.md)
§ The aliases carries **Provider** and **Gateways** columns, so "what do I call, where, and
on whose bill" is one table.

---

## 8. What is left to do

1. **`openai-embed` and the embedding routes** are untested everywhere. No folder covers
   embeddings.
2. **Re-check the two Codex issues** whenever folder 6 comes up.
3. **Decide whether §5.2 and §5.3 matter to you.** Both are Envoy + hosted OpenAI, both are
   upstream, and both have a clear next action written into their entries. If Envoy plus a
   hosted OpenAI model is a real use case for you, §5.2 is worth filing upstream — it looks
   unreported.
4. **File §5.2 upstream** if it is still unreported. The one-call reproduction and the #2099
   quote are the whole bug report.

---

## 9. How to run things

```bash
cd <gateway>/tests && uv run run_all.py          # all seven folders
uv run run_all.py --only 5_claude_agent_sdk      # one folder
uv run run_all.py --model openai-mini            # every folder, one alias — now works
cd <gateway>/tests/<folder> && uv run run_all.py # the folder's own scenarios
AI_GATEWAY_TEST_MODEL=openai-mini uv run 01_simple_call.py   # ONE scenario, non-default alias
```

- **Podman, not Docker.** Each runtime keeps its own volumes and containers. Docker's daemon
  was not even running on 2026-09-05.
- **No `uv sync` step.** `uv run --directory` builds whichever venv is missing.
- Health: LiteLLM `24000/health/readiness`, Envoy **`26000/v1/models`** — never
  `26064/health`, which goes green before the data plane accepts a connection.

---

## 10. House rules the next agent should keep

- **NEVER RUN TWO ENGINE-SWITCHING JOBS AT ONCE, and check for leftovers before starting
  one.** Both projects share one pair of `.env` files and one pair of containers. Two matrix
  runs overlapping produced a page of convincing nonsense — `Invalid model name passed in
  model=lms-4b` while the gateway was on ollama, `No matching route found`,
  `ollama-4b-anthropic may not exist`. **None of it was real.** Run
  `pgrep -fl 'matrix|run_all'` first. A background job survives the session that started it,
  and a still-live session will relaunch it.
- **`podman compose up -d` does NOT reload `config/settings.yaml`.** It is a bind mount, so
  an unchanged compose spec leaves the old process running with the old config. A config fix
  measured 0/5 against a container that had never restarted and was nearly written off.
  **Use `podman compose restart litellm` after a config edit**, and check the container's
  uptime before believing a result.
- **A failure in 0.0 s is an import error, not a test result.** Read the captured output
  before drawing any conclusion from a red row — §6.3 and §6.4 both hid behind one.
- **Assert that the feature was USED, not that the answer is right.** A 26B model answered
  `SN-4417-QX` correctly having read it out of the MCP server's own source with a shell
  command. The marker files caught it; an answer check would have passed.
- **Do not add a SKIP for something flaky. Fix the flake** — §6.2 is the worked example.
- **Assert on values, never on wording.** `Transcript.says()` strips commas and Markdown bold.
- **Isolate from ambient config.** `setting_sources=[]` for the Claude SDK; `mcp_servers={}`
  plus `plugins={}` for Codex — without the latter, `~/.codex/config.toml` handed the model
  **~80 tools**.
- **Every dependency floor is the version that was proven**, not a historical minimum.
- **`podman compose restart` does NOT clear a container's log.** Use `--since`.

---

## 11. State to restore when you finish

Both projects on **`GATEWAY_ENGINE=unsloth`**, both gateways healthy — **this is the state as
of 2026-09-05 01:15**, restored and verified. Also:

- `litellm/.env` carries **`GATEWAY_DISCOVERY=true`**, as found. It no longer needs blanking
  for a paid engine — §6.6.
- `envoy/.env` must keep **`AIGW_DEBUG=false`**. `true` dumps every prompt and reply.
- A pre-upgrade database dump sits in this session's scratchpad as
  `litellm-before-upgrade.sql` (170 MB). Only needed if the 1.99.1 upgrade has to be rolled
  back, and that upgrade applied no migrations.
- **Nothing has been committed.** `git status` shows the whole rebuild as uncommitted work.
