"""Turn the JSON lines `tests/run_cache.py` wrote into Markdown tables.

    uv run cache_report.py ../litellm/tests/cache-results/*.jsonl ../envoy/tests/cache-results/*.jsonl

WHAT IT READS: only the files you name. Like main.py it reads no file belonging to a
project — the result files are output, handed over on the command line — so the
two compose projects stay as independent as before.

TWO CACHE NUMBERS, AND THEY ANSWER DIFFERENT QUESTIONS:

    engine reused    what LMStudio REALLY took from its cache, from its own log
                     (`Prompt cache restore`). LMStudio only — Unsloth and
                     OpenRouter keep no log run_cache.py can read.
    reported         what the gateway TOLD the client was cached. LMStudio's
                     /v1/chat/completions reports nothing even on a hit, so a 0
                     here next to a high "engine reused" is the engine staying
                     quiet, not a miss.

"Engine reused" skips the session's first request, whose hit depends on what ran
before it. "Reported" cannot skip it: Envoy keeps only a per-session sum, so both
gateways are read over every request, to stay comparable.

"Engine reused" is diluted by side calls: Claude sends a request with its own short
prompt beside the conversation, which never shares a prefix and is not a bug. So two
more columns, both from the engine's log:

    last turn    how much of the LAST request's prompt was reused. Every scenario
                 ends by continuing its conversation, so this is the cleanest single
                 "does the cache hold" figure — 22% for Claude as shipped against
                 85-93% with the two settings, Gemma 4 26B, measured 2026-09-30.
    misses       later requests of at least MISS_MIN_PROMPT tokens that reused less
                 than half their prompt. The floor keeps the side calls out.

A LATER FILE WINS a grid cell when two files hold the same gateway, alias and agent,
so name a re-run last — a shell glob may sort it first. The session table lists both.

The last section quotes the engine's own prompt text where a prompt stopped matching
the one before it (`parts_at` in the files), so each miss names its cause.

COST IS PRICED HERE, from PRICES below, for both gateways alike — Envoy records no
cost at all. The local rows are SHADOW prices: nothing is billed, the number is
what the same tokens would cost at the route's cloud twin.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# USD per 1M tokens: (input, cached input, output). Copied BY HAND from each route's
# price in litellm/config/<engine>.yaml on 2026-09-30, because this folder reads no
# project's files. A cached token is priced as a full input token wherever the route
# names no cache price. LiteLLM's own /spend/logs does NOT: with no cache-read price
# it logs a cached local token at almost nothing (litellm/README.md), so its spend
# for a warm agent loop is lower than the column here.
PRICES = {
    "lms-gemma4-26b": (0.12, 0.12, 0.35),  # shadow
    "unsloth-gemma4-26b": (0.12, 0.12, 0.35),  # shadow
    "lms-qwen38-27b": (0.15, 0.15, 1.875),  # shadow
    "unsloth-qwen38-27b": (0.15, 0.15, 1.875),  # shadow
    "openrouter-gemma4-26b": (0.07, 0.07, 0.34),  # billed; live figure 2026-08-31
    "openrouter-qwen38-27b": (0.45, 0.45, 4.40),  # billed; the dearest provider 2026-09-29
}
BILLED_ENGINES = ("openrouter-", "openai-", "cerebras-")

MISS_MIN_PROMPT = 1024

AGENT_ORDER = ("http", "openai", "langchain", "deepagents", "claude", "claude-tuned", "codex", "opencode")


def read(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    headers, sessions = [], []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                (headers if row.get("kind") == "header" else sessions).append(row)
    return headers, sessions


def percent(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


def median(values: list[float], digits: int) -> str:
    values = [value for value in values if value is not None]
    return f"{statistics.median(values):.{digits}f}" if values else "—"


def engine_cache(session: dict) -> tuple[str, str, str]:
    """(engine reused %, last turn %, misses) over requests 2+, or dashes with no engine log."""
    later = [request for request in (session.get("engine_requests") or [])[1:] if request.get("cached") is not None]
    if not later:
        return "—", "—", "—"
    cached = sum(request["cached"] for request in later)
    prompt = cached + sum(request["uncached"] for request in later)
    last = later[-1]
    misses = sum(
        1
        for request in later
        if request["cached"] + request["uncached"] >= MISS_MIN_PROMPT
        and request["cached"] < (request["cached"] + request["uncached"]) / 2
    )
    return percent(cached, prompt), percent(last["cached"], last["cached"] + last["uncached"]), str(misses)


def reported_cache(session: dict) -> str:
    totals = session.get("gateway_totals")
    if totals is not None:  # Envoy: per-session sums from /metrics
        return percent(totals.get("cached_input", 0), totals.get("input", 0))
    requests = session["gateway_requests"]
    return percent(
        sum(r.get("cached_reported") or 0 for r in requests), sum(r.get("prompt_tokens") or 0 for r in requests)
    )


def efforts(session: dict) -> str:
    seen = sorted({request.get("effort_in_prompt") for request in session.get("engine_requests") or []} - {None})
    return ", ".join(seen) if seen else "—"


def ttft(session: dict) -> str:
    engine = [request.get("ttft_s") for request in session.get("engine_requests") or []]
    return median(engine or [request.get("ttft_s") for request in session["gateway_requests"]], 2)


def decode_speed(session: dict) -> str:
    """Median tokens/s: the engine's own figure, else after the first token, else end to end (~)."""
    engine = [request.get("decode_tok_s") for request in session.get("engine_requests") or []]
    if any(engine):
        return median(engine, 0)
    streamed = [
        r["completion_tokens"] / (r["seconds"] - r["ttft_s"])
        for r in session["gateway_requests"]
        if r.get("ttft_s") is not None and r.get("completion_tokens") and r["seconds"] > r["ttft_s"]
    ]
    if streamed:
        return median(streamed, 0)
    whole = [r["completion_tokens"] / r["seconds"] for r in session["gateway_requests"] if r.get("completion_tokens") and r.get("seconds")]
    return f"~{median(whole, 0)}" if whole else "—"


def cost(session: dict) -> str:
    price = PRICES.get(session["alias"])
    if not price:
        return "?"
    requests = session["gateway_requests"]
    prompt = sum(r.get("prompt_tokens") or 0 for r in requests)
    output = sum(r.get("completion_tokens") or 0 for r in requests)
    totals = session.get("gateway_totals")
    cached = totals.get("cached_input", 0) if totals is not None else sum(r.get("cached_reported") or 0 for r in requests)
    dollars = ((prompt - cached) * price[0] + cached * price[1] + output * price[2]) / 1_000_000
    shadow = "" if session["alias"].startswith(BILLED_ENGINES) else " s"
    return f"{dollars:.4f}{shadow}"


def session_key(session: dict) -> tuple:
    agent = session["agent"]
    return (session["gateway"], session["alias"], AGENT_ORDER.index(agent) if agent in AGENT_ORDER else 99)


def sessions_table(sessions: list[dict]) -> str:
    lines = [
        "| Gateway | Alias | Agent | Result | Seconds | Requests | Engine reused | Last turn | Misses "
        "| Reported cached | Effort in prompt | TTFT s | tok/s | Cost $ |",
        "|:--|:--|:--|:--|--:|--:|--:|--:|--:|--:|:--|--:|--:|--:|",
    ]
    for session in sorted(sessions, key=session_key):
        reused, last, misses = engine_cache(session)
        lines.append(
            f"| {session['gateway']} | `{session['alias']}` | {session['agent']} | {session['outcome']} "
            f"| {session['seconds']:.0f} | {len(session['gateway_requests'])} | {reused} | {last} | {misses} "
            f"| {reported_cache(session)} | {efforts(session)} | {ttft(session)} | {decode_speed(session)} "
            f"| {cost(session)} |"
        )
    return "\n".join(lines)


def cache_grid(sessions: list[dict]) -> str:
    """Agent × (gateway, alias): last turn reused / reported — the one-screen answer."""
    columns = sorted({(s["gateway"], s["alias"]) for s in sessions})
    cells = {}
    for session in sessions:
        _, last, _ = engine_cache(session)
        mark = "" if session["outcome"] == "pass" else f" ({session['outcome']})"
        cells[(session["agent"], session["gateway"], session["alias"])] = f"{last} / {reported_cache(session)}{mark}"
    agents = sorted({s["agent"] for s in sessions}, key=lambda a: AGENT_ORDER.index(a) if a in AGENT_ORDER else 99)
    lines = [
        "| Agent | " + " | ".join(f"{gateway} `{alias}`" for gateway, alias in columns) + " |",
        "|:--|" + "--:|" * len(columns),
    ]
    for agent in agents:
        row = [cells.get((agent, gateway, alias), "") for gateway, alias in columns]
        lines.append(f"| {agent} | " + " | ".join(row) + " |")
    return "\n".join(lines)


def rewrites(sessions: list[dict]) -> str:
    """Every request whose prompt did not contain the whole earlier one — and where it parted.

    LMStudio only: its log carries the prompt as the model saw it, template applied.
    """
    lines = []
    for session in sorted(sessions, key=session_key):
        for number, request in enumerate(session.get("engine_requests") or [], start=1):
            if request.get("parts_at"):
                where = request["parts_at"].replace("\n", "⏎").replace("`", "'")
                lines.append(
                    f"- {session['gateway']} `{session['alias']}` {session['agent']}, request {number}: "
                    f"kept {request['shared_chars']} of {request['earlier_chars']} characters — `{where}`"
                )
    return "\n".join(lines) or "None: every prompt contained the whole earlier one."


def machine(headers: list[dict]) -> str:
    lines = []
    for header in headers:
        lmstudio = ", ".join(
            f"{m['identifier']} ctx {m['contextLength']} ×{m.get('parallel')}" for m in header.get("lmstudio") or []
        )
        unsloth = header.get("unsloth") or {}
        lines.append(
            f"- {header['gateway']} {header['at'][:16]}Z — effort `{header.get('effort')}`; "
            f"Claude SDK's CLI {header.get('claude_sdk_cli')}; opencode {header.get('opencode')}; "
            f"openai-codex {header.get('openai_codex')}; "
            f"LMStudio: {lmstudio or 'nothing loaded'}; "
            f"Unsloth: {unsloth.get('active_model') or 'nothing loaded'} {unsloth.get('gguf_variant') or ''} "
            f"ctx {unsloth.get('context_length')} ×{unsloth.get('parallel_slots')}"
        )
    return "\n".join(dict.fromkeys(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path, help="JSONL files from tests/run_cache.py")
    args = parser.parse_args()
    headers, sessions = read(args.files)
    if not sessions:
        print("no sessions in those files", file=sys.stderr)
        return 1
    print("## Cache per agent — last turn reused by the engine / reported to the client, whole session\n")
    print("A two-request session whose second request hit perfectly reports 50%.\n")
    print(cache_grid(sessions))
    print("\n## Every session\n")
    print(sessions_table(sessions))
    print("\n`s` = shadow price, nothing billed. `~` = tokens/s end to end, first token included.")
    print("\n## Where a prompt was rewritten — the cause of each miss\n")
    print(rewrites(sessions))
    print("\n## The machine\n")
    print(machine(headers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
