---
description: "Step 4: Testing — define DoD, test, fix and repeat until passing"
---

# Step 4: Testing

**Every change must be tested before reporting completion. No exceptions.**

## 4a. Define your Definition of Done

Before testing, **write out your DoD checklist in the conversation** so the user
can see what you intend to verify. Example:

> **Definition of Done for this task:**
>
> - [ ] `podman compose up -d` brings both services to healthy
> - [ ] `/health/liveliness` answers `I'm alive!`
> - [ ] A completion through the changed alias returns content
> - [ ] The request appears in the admin UI's Logs tab with the expected model

## 4b. Test

Verification is: does the stack come up, and does the specific alias you touched
actually answer? Never substitute "the YAML looks right" for that.

`tests/` runs the three call kinds against **both** gateways and is the fastest
way to answer the second half of that question:

```bash
cd tests && uv sync && uv run run_all.py            # 6 rows: 3 scripts x 2 gateways
uv run run_all.py --model <the alias you touched>   # the alias that matters
uv run 02_tools_call.py --gateway litellm           # one script, one gateway
```

It exits `1` on any failure and prints the failed run's output. **It is not the
whole job**: it drives ONE alias per run, so it cannot tell you the stack came
up, and it says nothing about `/v1/messages`, embeddings, budgets or fallbacks.
The steps below still apply.

**Service / config changes** — bring it up and drive it:

```bash
podman compose config >/dev/null          # compose file parses and interpolates
podman compose up -d
podman compose ps -a                      # postgres, litellm, mlflow -> healthy
                                          # mlflow-seed -> Exited (0), which is DONE
curl -fsS http://localhost:24000/health/liveliness      # -> "I'm alive!"
curl -fsS http://localhost:25000/health                 # -> OK
podman compose logs mlflow-seed           # which endpoints it built, and what it skipped
```

`/health/liveliness` is the only unauthenticated route; `/health` needs the
master key. On a cold start give it the full 60 s `start_period` — LiteLLM is
running its schema migrations, and "unhealthy" during that window is expected.

**Then exercise the alias you actually changed**, not just any alias:

```bash
curl -sX POST http://localhost:24000/v1/chat/completions \
  -H "Authorization: Bearer ${AI_GATEWAY_KEY:-sk-litellm-master}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}]}'
```

> [!warning]
> **A 200 does not prove the request went where you think.** `local` falls back
> to OpenRouter when LMStudio is down, so a "local" test can pass entirely on a
> hosted model. Confirm the actual provider in the Logs tab at
> <http://localhost:24000/ui>, or check `lms ps --json` first.

**If you touched `litellm/config.yaml`, prove the SAME alias on both gateways.**
`mlflow-seed` copies that file, so a change there is a change to two services:

```bash
curl -sX POST http://localhost:25000/gateway/mlflow/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}]}'
```

No key on this one — the MLflow gateway has none. An alias that answers on 24000
and 404s on 25000 means `mlflow-seed` has not run since the edit, or it skipped
that route and said why in its log.

**If the change touches tool calling or `/v1/messages`** — a plain completion is
not enough. Send a request carrying a tool schema and confirm the response comes
back with `stop_reason: "tool_use"` and a structured `tool_use` block, not
raw-text tool syntax. That distinction is the entire reason the provider pin
exists, and a completion test cannot see it.

**If the change touches keys, budgets or spend** — mint a capped key and confirm
the ceiling is real:

```bash
curl -sX POST http://localhost:24000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"models":["local"],"max_budget":0.01,"duration":"1h"}'
```

A `{"error":"No connected db."}` here means the proxy booted without
`DATABASE_URL` — completions will still be working, which is why this has to be
tested explicitly rather than assumed.

**Every change** — repo-wide lint / format / type check:

```bash
nvim-tools --json --all
```

Your change must not add findings, measured against the baseline you took in the
Understand step. Expect nearly everything to report **`gated-off`**: this repo
carries no marker files, and nothing on this machine formats YAML at all. That
is the configured state, not a broken tool — how to read the output is in
[`machine-tools.md`](machine-tools.md), and the fix route, if one is ever wanted,
is `/lint-format-lsp` in mac-setup.

**Documentation-only changes** (`README.md`, `NOTES.md`): state explicitly why no
runtime test is needed. But if you changed a **command or a claim** in either
file, run it — a wrong `curl` in the README is the failure this repo's docs exist
to prevent.

## 4c. Fix and repeat

If a test fails: fix the issue, then retest. Repeat until all DoD items pass. If
you hit a problem you repeatedly cannot resolve, ask the user for help rather
than reporting partial success. `README.md` and `NOTES.md` both carry
troubleshooting tables — check them before inventing a diagnosis.

Leave the stack in the state you found it. If it was down before you started,
`podman compose down` when you are finished.

## 4d. Never report completion without testing

If you change config and stop without verifying the gateway still answers, you
have failed. Testing is YOUR responsibility — the user should never need to ask
you to test.
