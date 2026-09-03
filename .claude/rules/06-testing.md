# Step 4: Testing

**Every change is tested before you report it. No exceptions.** Verification is your job —
the user should never have to ask.

## Write the Definition of Done first

State in the conversation what you intend to verify, so the user can see it. For example:

> - [ ] `up -d` brings every service its profile names to healthy
> - [ ] `/health/readiness` reports `db: connected`
> - [ ] a completion through the changed alias returns content, on **both** gateways
> - [ ] the request appears in the Logs tab with the expected model

## Bring it up and drive it

Never substitute "the YAML looks right" for a real answer.

```bash
podman compose config >/dev/null        # parses and interpolates
podman compose config --services        # WHICH services COMPOSE_PROFILES starts
podman compose up -d
podman compose ps -a                    # mlflow-seed -> Exited (0) is DONE
curl -fsS http://localhost:24000/health/readiness    # -> {"status":"healthy","db":"connected"}
curl -fsS http://localhost:25000/health             # -> OK
podman compose logs mlflow-seed         # which endpoints it built, and what it skipped
```

On a cold start give it the full 60 s `start_period`; "unhealthy" inside that window is
expected.

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
that matters most: the two lists are separate and neither reads the other, so an edit to
one side alone is a silent drift only a call to 25000 catches.

```bash
curl -sX POST http://localhost:25000/gateway/mlflow/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<the alias you touched>","messages":[{"role":"user","content":"hi"}]}'
```

No key on that one. An alias that answers on 24000 and 404s on 25000 means the seed has
not run since the edit, or it skipped that route and said why in its log — **except
`openrouter-free`, which is absent there by design.**

## The suite

```bash
cd tests && uv sync && uv run run_all.py            # 8 rows: 4 scripts x 2 gateways
uv run run_all.py --model <the alias you touched>
uv run 02_tools_call.py --gateway litellm           # one script, one gateway
```

It exits 1 on any failure and prints the failed run's output. **It is not the whole job**:
it drives one alias per run, so it cannot tell you the stack came up, and it says nothing
about `/v1/messages`, embeddings, budgets or keys.

## Extra checks, when they apply

- **You touched what selects a config** (`compose.yml`, `seed.py`) — prove more than one
  combination. At minimum one single-gateway run: `COMPOSE_PROFILES=mlflow` → 25000
  serves, 24000 refuses, `compose ps` shows no `litellm` container. **Then put the stack
  back with the two words it had when you started.**
- **Tool calling or `/v1/messages`** — a plain completion is not enough. Send a request
  carrying a tool schema and confirm a structured `tool_calls` reply, not raw-text tool
  syntax. That distinction is the entire reason the provider pin exists.
- **Keys, budgets or spend** — mint a capped key and confirm the ceiling is real.
  `{"error":"No connected db."}` means the proxy booted without `DATABASE_URL`;
  completions still work, which is why this must be tested rather than assumed.
- **Documentation-only** — say explicitly why no runtime test was needed. But if you
  changed a **command or a claim**, run it. A wrong `curl` in the README is the failure
  the docs exist to prevent.
- **Every change** — `nvim-tools --json --all`. It must add no findings against your
  baseline. Expect everything `gated-off`: this repo carries no marker files, and nothing
  here formats YAML at all. That is configured, not broken.

## Fix, repeat, restore

If a test fails, fix it and retest until every DoD item passes. If you repeatedly cannot
resolve something, ask rather than reporting partial success — `README.md` has a
troubleshooting table.

**Leave the stack as you found it.** If it was down before you started, bring it down.
