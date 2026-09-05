"""Measure what the GATEWAY costs, with everything else held still.

THE QUESTION THIS ANSWERS: both gateways serve the same alias from the same
engine, so does the choice of gateway change what a caller waits for?

WHY IT NEEDED A SCRIPT OF ITS OWN. Timing a whole test folder answers a different
question, and answers it badly: a folder's wall clock is dominated by building a
venv, importing langchain, spawning a CLI, and whether the engine had the model
warm. Measured that way on 2026-09-04 the SAME script on the SAME gateway ranged
from 5.8 s to 46.7 s — a spread wider than any difference between the gateways.
So this file times ONE HTTP REQUEST and nothing else.

WHAT IS HELD CONSTANT, and each of these is a way the comparison could have lied:

    the engine      both proxy to ONE Unsloth on :8888, which holds one model
    the model       one alias, and the upstream id is READ BACK and compared
    the body        byte-identical messages, temperature 0
    max_tokens      SENT EXPLICITLY to both. This one is not optional: LiteLLM
                    stores a route default and Envoy stores none, so a body with
                    no ceiling asks LiteLLM to do LESS WORK than the other
    the order       round-robin, so no gateway gets the cold first call
    the warm-up     one discarded round per scenario, per gateway

WHAT IS MEASURED, per scenario, over N rounds: min, median, p90, max, and the
completion tokens the reply carried — because a gateway that answered faster by
generating less has not answered faster.

THE DIRECT ROW IS THE POINT OF COMPARISON. When UNSLOTH_API_KEY is in the shell
this also calls the engine on :8888 with no gateway at all, so every gateway row
can be read as "the engine, plus this much".

    uv run main.py
    uv run main.py --rounds 10
    uv run main.py --model unsloth-26b
    uv run main.py --json results.json

THIS SCRIPT IS THE ONE THING IN THE REPO THAT TOUCHES BOTH PORTS. It reads no file
belonging to any project — only the URLs, which are fixed and documented — so the
compose projects stay as independent as they were. Delete a gateway's folder and
its row here reports `not answering`. That is how `mlflow` on 25000 left this file
on 2026-09-04: one line removed, and nothing else here changed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# What is being compared
# ---------------------------------------------------------------------------

# The ports are the documented ones and are not read from any project's files —
# see the note at the top. `key` is a placeholder on Envoy, which checks none, and
# that difference is itself worth seeing in the table.
GATEWAYS = [
    ("litellm", "http://localhost:24000/v1", os.environ.get("AI_GATEWAY_KEY") or "sk-litellm-master"),
    ("envoy", "http://localhost:26000/v1", "no-key-needed"),
]

# The engine itself, with no gateway in front. Only added when the shell carries a
# key, because Unsloth 401s every route without one.
DIRECT_NAME = "direct (no gateway)"
DIRECT_URL = "http://localhost:8888/v1"

# NOT OPTIONAL, and the single most important control here. LiteLLM stores
# `max_tokens` on the route and the other two store none, so a request that omits
# it is a DIFFERENT REQUEST on each gateway. Sending it makes the work identical.
MAX_TOKENS = 512

TIMEOUT_SECONDS = 600.0


def scenarios(alias: str) -> dict[str, dict]:
    """One body per kind of call. Every field is identical across gateways.

    `temperature: 0` because a reply whose length varies run to run makes the
    timings noise. It does not make generation deterministic on a local engine,
    which is why the table also reports the completion tokens.
    """
    return {
        # Almost no generation, so this is the FIXED OVERHEAD of a round trip:
        # the proxy, plus the engine's turnaround. It is the row where a slow
        # gateway would show up most clearly.
        "tiny": {
            "model": alias,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        },
        # A realistic short answer — one or two sentences of generation.
        "chat": {
            "model": alias,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is the capital of France? Answer in one short sentence."},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        },
        # A tool schema in, a structured tool_calls reply out. This is the row
        # where a gateway that REWRITES the request could differ from one that
        # forwards it, because tool definitions are the most translated part of
        # the OpenAI body.
        "tools": {
            "model": alias,
            "messages": [{"role": "user", "content": "What is the current stock price for MSFT?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_stock_price",
                        "description": "Get the current price of a stock.",
                        "parameters": {
                            "type": "object",
                            "properties": {"ticker": {"type": "string"}},
                            "required": ["ticker"],
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        },
        # A ~4 KB prompt. Envoy's ClientTrafficPolicy raises a 32 KiB buffer limit
        # to 50Mi for exactly this reason, so a body big enough to matter belongs
        # in the comparison.
        "long-prompt": {
            "model": alias,
            "messages": [
                {"role": "user", "content": "Summarise this in one sentence:\n\n" + ("lorem ipsum dolor sit amet. " * 150)}
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        },
    }


# ---------------------------------------------------------------------------
# One request, timed
# ---------------------------------------------------------------------------


def post(base_url: str, key: str, body: dict, stream: bool = False):
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({**body, **({"stream": True} if stream else {})}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)


def timed_call(base_url: str, key: str, body: dict) -> tuple[float, int, str]:
    """Seconds, completion tokens, and the model id the reply claimed.

    The token count is returned because a gateway that answered faster by
    generating less has not answered faster, and the model id because the whole
    comparison rests on every row having asked the same engine.
    """
    started = time.perf_counter()
    with post(base_url, key, body) as response:
        payload = json.loads(response.read())
    seconds = time.perf_counter() - started
    usage = payload.get("usage") or {}
    return seconds, int(usage.get("completion_tokens") or 0), str(payload.get("model") or "?")


def timed_stream(base_url: str, key: str, body: dict) -> tuple[float, float]:
    """Time to FIRST token, and time to last.

    TTFT is the number a streaming caller actually feels, and it is the one a
    buffering proxy would ruin — a gateway that collects the whole reply before
    forwarding it has a TTFT equal to its total.
    """
    started = time.perf_counter()
    first: float | None = None
    with post(base_url, key, body, stream=True) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            frame = json.loads(data)
            if "error" in frame:
                raise RuntimeError(json.dumps(frame["error"]))
            choices = frame.get("choices") or []
            if choices and (choices[0].get("delta") or {}).get("content") and first is None:
                first = time.perf_counter() - started
    return (first if first is not None else float("nan")), time.perf_counter() - started


# ---------------------------------------------------------------------------
# Running the comparison
# ---------------------------------------------------------------------------


def summarise(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1)))))
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p90": ordered[index],
        "max": ordered[-1],
    }


def targets(alias: str, include_direct: bool) -> list[tuple[str, str, str, str]]:
    """(label, base_url, key, alias) for every row of the table.

    The direct row calls the engine with ITS OWN model id, not the alias — an
    alias is a gateway's invention and the engine has never heard of it. That id
    is discovered from a gateway that echoes it back rather than hardcoded.
    """
    rows = [(name, url, key, alias) for name, url, key in GATEWAYS]
    if not include_direct:
        return rows

    engine_key = os.environ.get("UNSLOTH_API_KEY")
    if not engine_key:
        print("  (no UNSLOTH_API_KEY in the shell — skipping the direct-engine row)\n")
        return rows

    upstream = upstream_model_id(alias)
    if upstream is None:
        print("  (could not discover the upstream model id — skipping the direct-engine row)\n")
        return rows
    return rows + [(DIRECT_NAME, DIRECT_URL, engine_key, upstream)]


def upstream_model_id(alias: str) -> str | None:
    """The engine's OWN model id, read back from a gateway that echoes it.

    Envoy returns the upstream id in `response.model`; LiteLLM returns the alias.
    So one short call to Envoy names the model the direct row must ask for — and,
    incidentally, proves the alias resolves to a real model rather than to a name
    only the gateway knows. With Envoy down, the direct row is skipped.
    """
    for name, url, key in GATEWAYS:
        if name == "litellm":
            continue
        try:
            _, _, model = timed_call(url, key, {
                "model": alias,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8,
                "temperature": 0,
            })
            if model and model != alias:
                return model
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return None


def check_same_engine(alias: str, rows: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """Ask every gateway once and report what answered.

    THIS IS THE CONTROL THE WHOLE COMPARISON RESTS ON. If two gateways are serving
    different engines — each project has its own `.env`, and nothing keeps them in
    step — the table below is meaningless and this is where you see it.
    """
    seen: dict[str, str] = {}
    print("Which model answered, per gateway:")
    for label, url, key, model_name in rows:
        try:
            _, _, model = timed_call(url, key, {
                "model": model_name,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8,
                "temperature": 0,
            })
        except (urllib.error.URLError, OSError, ValueError) as error:
            model = f"not answering ({type(error).__name__})"
        seen[label] = model
        print(f"  {label:20s} sent {model_name!r:34s} -> reply says {model!r}")

    upstream = {value for label, value in seen.items() if label != "litellm" and not value.startswith("not answering")}
    if len(upstream) > 1:
        print(f"\n  WARNING: the gateways are NOT on the same engine — {sorted(upstream)}")
        print("  Each project reads its own .env. The table below compares different work.\n")
    else:
        print("  (LiteLLM echoes the alias by design, so its upstream id is not visible here.)\n")
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="unsloth-4b", help="the alias to call on every gateway")
    parser.add_argument("--rounds", type=int, default=5, help="measured rounds per scenario (default: 5)")
    parser.add_argument("--no-direct", action="store_true", help="skip the no-gateway baseline row")
    parser.add_argument("--json", metavar="PATH", help="also write the raw per-call timings here")
    args = parser.parse_args()

    print(f"\n{'=' * 78}\nGateway comparison — same engine, same model, same body, same max_tokens")
    print(f"alias={args.model}  max_tokens={MAX_TOKENS}  temperature=0  rounds={args.rounds}")
    print(f"{'=' * 78}\n")

    rows = targets(args.model, include_direct=not args.no_direct)
    answered = check_same_engine(args.model, rows)
    live = [row for row in rows if not answered[row[0]].startswith("not answering")]
    if not live:
        print("No gateway answered. Start at least one and try again.", file=sys.stderr)
        return 1

    raw: dict = {"alias": args.model, "max_tokens": MAX_TOKENS, "rounds": args.rounds,
                 "answered": answered, "scenarios": {}}

    for scenario_name, template in scenarios(args.model).items():
        print(f"\n### {scenario_name}")
        samples: dict[str, list[float]] = {label: [] for label, *_ in live}
        tokens: dict[str, list[int]] = {label: [] for label, *_ in live}
        errors: dict[str, str] = {}

        # ONE DISCARDED ROUND FIRST. The first call after an idle stretch pays for
        # the engine's cache, and whichever gateway happened to go first would
        # otherwise carry that cost for the whole table.
        for label, url, key, model_name in live:
            try:
                timed_call(url, key, {**template, "model": model_name})
            except Exception:  # noqa: BLE001 — a warm-up failure shows up below anyway
                pass

        # ROUND-ROBIN, not gateway-by-gateway: the engine drifts over minutes, and
        # interleaving spreads that drift evenly instead of giving it to one row.
        #
        # EVERY ROUND IS ATTEMPTED, even after one fails. An earlier version gave
        # up on a gateway at its first error and reported the row as unsupported —
        # so one transient 503 was indistinguishable from a route that does not
        # exist. A failure is counted here, not treated as a verdict.
        failures: dict[str, int] = {label: 0 for label, *_ in live}
        for _ in range(args.rounds):
            for label, url, key, model_name in live:
                try:
                    seconds, completion, _ = timed_call(url, key, {**template, "model": model_name})
                    samples[label].append(seconds)
                    tokens[label].append(completion)
                except Exception as error:  # noqa: BLE001 — one row failing is a result
                    failures[label] += 1
                    errors.setdefault(label, f"{type(error).__name__}: {str(error)[:60]}")

        print(f"\n| Gateway | min | median | p90 | max | completion tokens |")
        print("|:--|--:|--:|--:|--:|--:|")
        for label, *_ in live:
            if not samples[label]:
                print(f"| `{label}` | — | — | — | — | **all {args.rounds} failed** — {errors[label]} |")
                continue
            stats = summarise(samples[label])
            token_note = f"{statistics.median(tokens[label]):.0f}" if tokens[label] else "?"
            if failures[label]:
                token_note += f" ({failures[label]}/{args.rounds} calls failed: {errors[label]})"
            print(f"| `{label}` | {stats['min']:.2f} s | **{stats['median']:.2f} s** | "
                  f"{stats['p90']:.2f} s | {stats['max']:.2f} s | {token_note} |")
        raw["scenarios"][scenario_name] = {"seconds": samples, "completion_tokens": tokens, "errors": errors}

    # Streaming is its own table: the number that matters is TIME TO FIRST TOKEN,
    # which is what a buffering proxy would destroy.
    print("\n### streaming — time to first token")
    stream_body = {**scenarios(args.model)["chat"]}
    ttft: dict[str, list[float]] = {label: [] for label, *_ in live}
    total: dict[str, list[float]] = {label: [] for label, *_ in live}
    stream_errors: dict[str, str] = {}
    stream_failures: dict[str, int] = {label: 0 for label, *_ in live}
    # Same rule as above: every round is attempted. "Unsupported" is a claim that
    # EVERY round failed, not that one did. A gateway whose streaming is broken
    # fails all of them, and that is a real finding; a lone 503 is not.
    for _ in range(args.rounds):
        for label, url, key, model_name in live:
            try:
                first, whole = timed_stream(url, key, {**stream_body, "model": model_name})
                ttft[label].append(first)
                total[label].append(whole)
            except Exception as error:  # noqa: BLE001 — a row failing every round is the finding
                stream_failures[label] += 1
                stream_errors.setdefault(label, f"{type(error).__name__}: {str(error)[:70]}")

    print("\n| Gateway | first token, median | whole reply, median | failed |")
    print("|:--|--:|--:|:--|")
    for label, *_ in live:
        if not ttft[label]:
            print(f"| `{label}` | **unsupported** | — | all {args.rounds} — {stream_errors[label]} |")
            continue
        note = "—" if not stream_failures[label] else f"{stream_failures[label]}/{args.rounds} — {stream_errors[label]}"
        print(f"| `{label}` | **{statistics.median(ttft[label]):.2f} s** | "
              f"{statistics.median(total[label]):.2f} s | {note} |")
    raw["scenarios"]["streaming"] = {"ttft": ttft, "total": total, "errors": stream_errors}

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=2)
        print(f"\nraw timings written to {args.json}")

    print("\nRead the medians, not the maxima: a local engine's tail is the engine, not the proxy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
