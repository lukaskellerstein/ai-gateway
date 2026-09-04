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
cd litellm                              # or mlflow, or envoy
podman compose config --services        # parses and interpolates. --services, NOT bare
podman compose up -d
podman compose ps -a                    # discover / mlflow-seed -> Exited (0) is DONE
curl -fsS http://localhost:24000/health/readiness    # -> {"status":"healthy","db":"connected"}
curl -fsS http://localhost:25000/health             # -> OK
curl -fsS http://localhost:26000/v1/models          # Envoy: the DATA plane, NOT 26064
podman compose logs mlflow-seed         # which endpoints it built, and what it skipped
```

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

**If you touched an alias list, prove the SAME alias on EVERY gateway.** This is the check
that matters most, and **nothing automated does it any more** — the shared suite that used
to went when the projects were split. The three lists are separate and none reads another,
so an edit to one side alone is a silent drift only a call to the other ports catches.

```bash
curl -sX POST http://localhost:25000/gateway/mlflow/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}],"max_tokens":2048}'
```

```bash
curl -sX POST http://localhost:26000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}],"max_tokens":2048}'
```

No key on either, and **always send `max_tokens`** — neither MLflow nor Envoy stores a route
default. An alias that answers on 24000 and 404s elsewhere means the edit was not made on
that side, or the seed has not run since, or the `.env` files name different engines —
**except `openrouter-free`, which is absent on 25000 and 26000 by design.**

## The suites

There are three, one per project, and each drives its own gateway.

```bash
cd litellm/tests && uv sync && uv run run_all.py    # 4 rows against 24000
cd mlflow/tests  && uv sync && uv run run_all.py    # 4 rows against 25000
cd envoy/tests   && uv sync && uv run run_all.py    # 4 rows against 26000

uv run run_all.py --model <the alias you touched>
uv run 02_tools_call.py                            # one script
```

Each exits 1 on any failure and prints the failed run's output. **None is the whole job**:
each drives one alias per run, cannot tell you the stack came up, says nothing about
`/v1/messages`, `/mcp`, embeddings, budgets or keys, and **none compares the gateways**.

## Extra checks, when they apply

- **You touched what selects a config** (any `compose.yml`, `seed.py`, a `discover/`) —
  prove more than one combination. At minimum bring another project up too and confirm both
  answer at once, then check that stopping one leaves the other serving. **Then put them all
  back the way you found them**, including each project's `GATEWAY_ENGINE`.
- **You touched a `discover/` module** — fix BOTH copies, and prove both. LiteLLM's writes
  `config/discovered-<engine>.yaml`; MLflow's is a library, so drive it through
  `compose run --rm mlflow-seed python -c "..."` or with `GATEWAY_DISCOVERY=on`.
- **You touched `litellm/compose.yml`** — check `name: ai-gateway` is still there, then
  prove the volume is still attached:
  `podman compose exec -T postgres psql -U postgres -d litellm -c 'SELECT count(*) FROM "LiteLLM_VerificationToken";'`
  A count of 0 on a machine that had keys means the volume was detached.
- **You touched `envoy/`** — prove all three LOCAL engines with a real completion. The two
  PAID ones can only be brought up and checked for their aliases on `/v1/models`, because a
  completion through either bills a real account. Check `AIGW_DEBUG` still defaults to
  `false` and not to empty, or the container crash-loops on a bool parse.
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

**Leave all three projects as you found them.** They start and stop independently now, so
"as found" is two facts per project: whether it was up, and which engine it was on. Record
them before you touch anything.
