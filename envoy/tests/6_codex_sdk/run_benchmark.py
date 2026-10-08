"""The benchmark task through Codex: one thread, its own shell, a real file.

    uv run run_benchmark.py                                   every default alias
    uv run run_benchmark.py --aliases lms-gemma4-26b          one alias
    uv run run_benchmark.py --aliases lms-gemma4-26b --no-write

ONE CODEX THREAD PER SESSION holds the three turns, as in `02_session.py`, and it is
started by `common.start_thread` like every scenario here: a read-only sandbox,
`deny_all` approvals, the empty CODEX_HOME. Its working directory is a temporary one
holding `order.json`, and Codex reads it with ITS OWN SHELL — `cat order.json`,
sometimes after an `ls` (2026-09-30). The file is real and nothing answers for it. It
is not an MCP tool: whether Codex can call one on a local engine is openai/codex#19871
(see 04_mcp.py), and its shell works on both gateways. The task, the table and
RESULTS.md come from the shared part at the
bottom of this file.

WHAT IS MEASURED, AND HOW. Codex decides how many model requests a turn takes and
sends them itself. The SDK sees the runtime's notifications, and one of them closes
every request:

    thread/tokenUsage/updated   `last` is THAT request's usage — input, cached,
                                output, reasoning. Exactly one per request
    item/agentMessage/delta     a streamed piece of the answer
    item/reasoning/textDelta    a streamed piece of the thinking
                                (`summaryTextDelta` when it is a summary)

The clock starts with the turn and restarts at each usage event, which Codex sends
after running the command a request asked for and just before the next request leaves
— within 10 ms of it through a logging proxy, 2026-09-30. So a request's time includes
its command: milliseconds for a `cat`.

NO DELTA, NO FIRST TOKEN. Through LiteLLM Codex surfaces no delta at all: LiteLLM's
Responses stream opens the reasoning item without its `summary` field and never opens
the message item, while Envoy passes LMStudio's own stream through and both kinds
arrive (`lms-gemma4-26b`, 2026-09-30). First token and decode speed are then `—`, and
RESULTS.md says why.

RUN IT OUTSIDE ANY OTHER macOS SANDBOX. Codex's read-only sandbox is `sandbox-exec`,
which cannot nest: inside one, every command exits 71 with `sandbox_apply: Operation
not permitted` and the model keeps trying other commands (2026-09-30, inside Claude
Code's sandbox). MAX_REQUESTS_PER_TURN stops such a turn.

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS. Everything specific is in settings.py.
Its shared part — the task, the record, the table — is the same in every folder.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from openai_codex import Thread
from openai_codex.models import (
    AgentMessageDeltaNotification,
    ItemCompletedNotification,
    ReasoningSummaryTextDeltaNotification,
    ReasoningTextDeltaNotification,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotification,
)

from common import Codex, codex_config, start_thread
from settings import (
    API_KEY,
    BASE_URL,
    CONTEXT_WINDOW,
    NAME,
    REASONING_EFFORT,
    REQUEST_TIMEOUT_SECONDS,
    RESPONSES_BASE_URL,
    body_extras,
)

HERE = Path(__file__).resolve().parent

# A turn here takes one to three requests: `ls`, `cat`, the answer. A model that cannot
# read the file keeps trying other commands, and on a paid alias every try is billed.
MAX_REQUESTS_PER_TURN = 8

STREAMED = (AgentMessageDeltaNotification, ReasoningTextDeltaNotification, ReasoningSummaryTextDeltaNotification)


def record(turn: int, clock: Clock, usage_event: ThreadTokenUsageUpdatedNotification) -> Record:
    """One model request, closed by its usage event."""
    usage = usage_event.token_usage.last
    return Record(
        turn=turn,
        ttft_s=clock.ttft(),
        seconds=clock.elapsed(),
        decode_tok_s=decode_rate(usage.output_tokens, clock.first, clock.last),
        prompt_tokens=usage.input_tokens,
        # A REQUIRED INTEGER in Codex's usage, so a gateway that sends no count reads
        # as 0 here — see notes().
        cached_tokens=usage.cached_input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_output_tokens,
    )


def run_turn(thread: Thread, question: str, turn: int, records: list[Record]) -> str:
    """One user turn, however many requests Codex makes of it. Returns its last message."""
    clock = Clock()
    handle = thread.turn(question)
    answer, requests = "", 0
    for event in handle.stream():
        payload = event.payload
        if isinstance(payload, STREAMED):
            clock.token()
        elif isinstance(payload, ThreadTokenUsageUpdatedNotification):
            records.append(record(turn, clock, payload))
            clock = Clock()
            requests += 1
            if requests == MAX_REQUESTS_PER_TURN:
                handle.interrupt()
        elif isinstance(payload, ItemCompletedNotification) and payload.item.root.type == "agentMessage":
            answer = payload.item.root.text
        elif isinstance(payload, TurnCompletedNotification):
            status = payload.turn.status.value
            if status == "interrupted":
                raise RuntimeError(f"turn {turn} was stopped after {MAX_REQUESTS_PER_TURN} requests")
            if status == "failed":
                raise RuntimeError(payload.turn.error.message if payload.turn.error else "the turn failed")
    return answer


def one_session(alias: str, session: Session) -> None:
    with tempfile.TemporaryDirectory(prefix="codex-benchmark-") as work, Codex(config=codex_config(alias)) as codex:
        write_order_file(Path(work))
        thread = start_thread(codex, alias, cwd=work)
        for turn, question in enumerate(turns(), 1):
            answer = run_turn(thread, question, turn, session.records)
            problem = check_answer(turn, answer)
            if problem:
                session.problem = problem
                return


def notes(sessions: list[Session]) -> tuple[str, ...]:
    found = [
        "**Cached** is Codex's `cachedInputTokens`, a required integer: a gateway that sends "
        "no cache count reads as **0**, so a 0 here can mean *not reported*. LiteLLM's "
        "`/v1/responses` sends none for LMStudio; Envoy passes LMStudio's own count through "
        "(2026-09-30).",
        "**One row per model request**, from Codex's `thread/tokenUsage/updated`. Its time "
        "runs to that event, which follows the shell command the request asked for — "
        "milliseconds for a `cat`.",
    ]
    if any(r.ttft_s is None for s in sessions for r in s.records):
        found.append(
            "**First token** and **Decode tok/s** are `—` for a request that reached Codex with "
            "no streamed delta. Through LiteLLM that is every request: its Responses stream "
            "opens the reasoning item without a `summary` field and never opens the message "
            "item, and Codex surfaces neither (2026-09-30)."
        )
    return tuple(found)


def main() -> None:
    args = parse_args(__doc__)
    started = time.perf_counter()
    aliases = [a for a in args.aliases.split(",") if a]
    sessions = run_all(aliases, one_session, lambda a: warm_up(BASE_URL, API_KEY, a, body_extras(a)))
    print(f"\n{len(sessions)} sessions in {time.perf_counter() - started:.0f} s")
    if not args.no_write:
        level = f"`model_reasoning_effort=\"{REASONING_EFFORT}\"`, on the wire as `reasoning: {{effort: {REASONING_EFFORT}, summary: auto}}` in every request"
        setup = {
            "Client": f"`openai-codex` {version('openai-codex')}, the Python SDK over the `codex app-server` runtime it ships",
            "Gateway": f"{NAME}, `{RESPONSES_BASE_URL}/responses` — Codex speaks the Responses API and nothing else",
            "Thinking level": level if REASONING_EFFORT else "none sent",
            "Conversation": "one Codex thread for the three turns. Every request resends the whole "
                            "conversation (`store: false`, no `previous_response_id`) and carries the "
                            "thread id as `prompt_cache_key`",
            "Isolation": "an empty temporary `CODEX_HOME` and `features.plugins=false`: 9 tools in every "
                         "request (2026-09-30), where this machine's `~/.codex` handed the model ~108",
            "Tool": "Codex's own shell (`exec_command`) in the read-only sandbox with `deny_all` "
                    "approvals, in a temporary directory holding `order.json`",
            "Compaction": f"`model_context_window={CONTEXT_WINDOW}`",
            "Timeout and retries": f"`stream_idle_timeout_ms={int(REQUEST_TIMEOUT_SECONDS * 1000)}`, "
                                   "`request_max_retries=0`, `stream_max_retries=0`",
            "Streaming": "always, in Codex; first token and decode speed come from its delta events",
        }
        print(f"wrote {write_results(HERE, 'Codex SDK', NAME, setup, sessions, notes(sessions))}")


# =========================================================================================
# THE SHARED PART — the task, the record and the table. From here to the END banner this
# block is BYTE-IDENTICAL in all fourteen run_benchmark.py files, seven per project; only
# the client code above it differs. That is what makes the fourteen RESULTS.md files
# comparable: the same three questions, the same columns. Change it in one file, copy it
# to the other thirteen. Standard library only.
#
# THE TASK. Three user turns in one conversation:
#
#     1. a ~1500-token support policy, then "read order.json and give the status"
#        — the client must use a tool (a function tool, or its own file reader)
#     2. a follow-up the model can answer only from the conversation so far
#     3. a short customer message — the longest answer, so decode speed shows
#
# Turns 2 and 3 resend everything before them, so from the second request on the
# engine can reuse its cache. The policy is there to make that prefix long enough to
# measure: a 300-token prompt hides a cache hit inside one 256-token block.
#
# WHAT A ROW MEANS. `cached_tokens` is what the CLIENT WAS TOLD. `None` means the
# reply carried no cache field at all — LMStudio's chat completions route never does
# (lmstudio-ai/lmstudio-bug-tracker#778) — and that is not a miss. The first-token
# time of the later requests shows whether the engine really reused the prefix.
# =========================================================================================

# ---------------------------------------------------------------------------
# The task — the same in every folder
# ---------------------------------------------------------------------------

# Six models on three engines, plus Ollama's Gemma. OpenRouter is PAID — about half a
# cent for both of its rows in one folder, measured 2026-09-30.
DEFAULT_ALIASES = (
    "lms-gemma4-26b",
    "lms-qwen38-27b",
    "unsloth-gemma4-26b",
    "unsloth-qwen38-27b",
    "ollama-gemma4-26b",
    "openrouter-gemma4-26b",
    "openrouter-qwen38-27b",
)

ORDER_FILE_NAME = "order.json"
ORDER = {
    "order_id": "A-1042",
    "status": "shipped",
    "items": 3,
    "total_eur": 184.50,
    "carrier": "DHL",
    "eta": "2026-10-03",
    "customer": "Jana Novak",
}
ORDER_JSON = json.dumps(ORDER, indent=2)

_POLICY_TOPICS = (
    "returns", "refunds", "exchanges", "address changes", "cancellations", "invoices",
    "gift wrapping", "loyalty points", "price matching", "bulk orders",
)


def _policy() -> str:
    """Forty numbered clauses, about 1500 tokens, and deterministic.

    None of them names a status, a carrier or an amount, so an answer that does
    proves the file was read.
    """
    clauses = [
        f"{number}. On {_POLICY_TOPICS[number % len(_POLICY_TOPICS)]}: reply within "
        f"{4 + number % 20} working hours, quote the order id back to the customer, "
        f"confirm every detail from the order record before you state it, and never "
        f"promise anything the record does not already say."
        for number in range(1, 41)
    ]
    return "Our customer support policy:\n\n" + "\n".join(clauses)


POLICY = _policy()


def turns() -> tuple[str, str, str]:
    """The three user messages of ONE session, the first opening with a fresh id.

    WITHOUT THE ID A SESSION STARTS WARM. The engine keeps the last session's prefix,
    so the policy was already cached and the first request looked like a hit
    (0.38 s on 2 000 tokens, 2026-09-30). The id makes the policy new each time; what
    a client puts BEFORE it — its own system prompt and tools — may still be reused,
    and that reuse is real: it is what the next session of the same agent gets.
    """
    return (
        f"Session {uuid.uuid4()}.\n\n{POLICY}\n\nRead the file {ORDER_FILE_NAME} and tell "
        "me the status of order A-1042 in one sentence.",
        "How many items are in that order, and what is the total in euros? Answer in one sentence.",
        "Write a short, friendly message of two sentences to the customer about the "
        "delivery date and the carrier.",
    )


def check_answer(turn: int, answer: str) -> str | None:
    """None when the answer shows the model used the file; else what is missing."""
    text = answer.lower()
    if turn == 1 and "shipped" not in text:
        return "turn 1 does not say `shipped` — the file was not read"
    if turn == 2 and not ("3" in text and ("184.5" in text or "184,5" in text)):
        return "turn 2 does not give 3 items and 184.50"
    if turn == 3 and "dhl" not in text:
        return "turn 3 does not name DHL"
    return None


# THE FUNCTION TOOL, for the three folders that bring no file reader of their own.
READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a text file from the current working directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "The file name, e.g. notes.txt"}},
            "required": ["path"],
        },
    },
}


def read_file(path: str) -> str:
    """The one file the task knows; anything else is an honest miss."""
    return ORDER_JSON if Path(path).name == ORDER_FILE_NAME else f"error: no such file: {path}"


def write_order_file(directory: Path) -> Path:
    """For the agents that read files themselves: the same content, on disk."""
    target = directory / ORDER_FILE_NAME
    target.write_text(ORDER_JSON + "\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# What is recorded
# ---------------------------------------------------------------------------


@dataclass
class Record:
    """One model request, as the client saw it. `None` means the client could not tell."""

    turn: int
    ttft_s: float | None = None
    seconds: float | None = None
    decode_tok_s: float | None = None
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


def decode_rate(output_tokens: int | None, first: float | None, last: float | None) -> float | None:
    """Tokens per second between the first and the last streamed token.

    It leaves out the time to the first token, which is prompt reading, not writing.
    """
    if not output_tokens or first is None or last is None or last <= first:
        return None
    return (output_tokens - 1) / (last - first)


@dataclass
class Session:
    alias: str
    records: list[Record] = field(default_factory=list)
    seconds: float = 0.0
    warm_up_s: float | None = None
    problem: str | None = None


class Clock:
    """Marks the first and the last streamed token of one request."""

    def __init__(self) -> None:
        self.start = time.perf_counter()
        self.first: float | None = None
        self.last: float | None = None

    def token(self) -> None:
        now = time.perf_counter()
        self.first = self.first or now
        self.last = now

    def ttft(self) -> float | None:
        return None if self.first is None else self.first - self.start

    def elapsed(self) -> float:
        return time.perf_counter() - self.start


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--aliases", default=",".join(DEFAULT_ALIASES),
                        help="comma-separated aliases, run in this order")
    parser.add_argument("--no-write", action="store_true", help="print the table, leave RESULTS.md alone")
    return parser.parse_args()


def warm_up(base_url: str, api_key: str, alias: str, extras: dict) -> float:
    """One tiny chat completion, so loading the model is not counted as the first token.

    Every client here reaches the same engine, so the OpenAI route of the same gateway
    loads the model for all of them — the Anthropic and Responses routes included.
    """
    body = {"model": alias, "messages": [{"role": "user", "content": "Say OK."}], **extras}
    body["max_tokens" if "max_completion_tokens" not in body else "max_completion_tokens"] = 16
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=3600) as response:
        response.read()
    return time.perf_counter() - started


def run_all(aliases: list[str], one_session, warm) -> list[Session]:
    """One session per alias, one after another — parallel runs would share the GPU.

    `warm(alias)` loads the model first; its time is reported apart from the session.
    """
    sessions = []
    for alias in aliases:
        session = Session(alias)
        try:
            session.warm_up_s = warm(alias)
        except Exception as error:  # noqa: BLE001 — an alias that cannot answer is a row
            session.problem = f"warm-up failed: {type(error).__name__}: {str(error)[:140]}"
            sessions.append(session)
            print(summary_row(session), flush=True)
            continue
        started = time.perf_counter()
        try:
            one_session(alias, session)
        except Exception as error:  # noqa: BLE001 — a failing alias is a row, not a crash
            session.problem = f"{type(error).__name__}: {str(error)[:160]}"
        session.seconds = time.perf_counter() - started
        sessions.append(session)
        print(summary_row(session), flush=True)
    return sessions


# ---------------------------------------------------------------------------
# How it is written down
# ---------------------------------------------------------------------------

ENGINES = {"lms": "LMStudio", "unsloth": "Unsloth", "ollama": "Ollama",
           "openrouter": "OpenRouter", "openai": "OpenAI", "cerebras": "Cerebras"}

HEADER = ("| Alias | Engine | Result | Warm-up | Session | Requests | First token, first → last request "
          "| Decode tok/s | Prompt tokens, first → last | Cached on the last request | Thinking tokens |")
DIVIDER = "|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|"


def _seconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} s"


def _cached(record: Record) -> str:
    if record.cached_tokens is None:
        return "not reported"
    if record.prompt_tokens:
        return f"{record.cached_tokens} ({100 * record.cached_tokens // record.prompt_tokens}%)"
    return str(record.cached_tokens)


def summary_row(session: Session) -> str:
    records = session.records
    engine = ENGINES.get(session.alias.split("-")[0], "?")
    result = "ok" if session.problem is None else session.problem.replace("|", "/")
    cells = [f"`{session.alias}`", engine, result, _seconds(session.warm_up_s),
             f"{session.seconds:.1f} s", str(len(records))]
    if not records:
        return "| " + " | ".join(cells + ["—"] * 5) + " |"
    first, last = records[0], records[-1]
    rates = [r.decode_tok_s for r in records if r.decode_tok_s]
    thinking = [r.reasoning_tokens for r in records if r.reasoning_tokens is not None]
    cells += [
        f"{_seconds(first.ttft_s)} → {_seconds(last.ttft_s)}",
        f"{statistics.median(rates):.0f}" if rates else "—",
        f"{first.prompt_tokens or '—'} → {last.prompt_tokens or '—'}",
        _cached(last),
        str(sum(thinking)) if thinking else "—",
    ]
    return "| " + " | ".join(cells) + " |"


def detail_table(session: Session) -> str:
    lines = [
        f"**`{session.alias}`**",
        "",
        "| Request | Turn | First token | Request time | Decode tok/s | Prompt | Cached | Output | Thinking |",
        "|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for number, r in enumerate(session.records, 1):
        lines.append(
            f"| {number} | {r.turn} | {_seconds(r.ttft_s)} | {_seconds(r.seconds)} "
            f"| {'—' if r.decode_tok_s is None else f'{r.decode_tok_s:.0f}'} "
            f"| {r.prompt_tokens if r.prompt_tokens is not None else '—'} | {_cached(r)} "
            f"| {r.output_tokens if r.output_tokens is not None else '—'} "
            f"| {r.reasoning_tokens if r.reasoning_tokens is not None else '—'} |"
        )
    return "\n".join(lines)


def write_results(folder: Path, client: str, gateway: str, setup: dict[str, str],
                  sessions: list[Session], notes: tuple[str, ...] = ()) -> Path:
    """RESULTS.md beside the script: what was run, how, and what came back."""
    measured = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    setup_lines = "\n".join(f"- **{key}**: {value}" for key, value in setup.items())
    note_lines = "\n".join(f"- {note}" for note in notes)
    text = f"""# {client} on {gateway}

Measured {measured} by `uv run run_benchmark.py`. The task is the same in every folder:
a ~1500-token support policy, then three turns in one conversation — read
`{ORDER_FILE_NAME}` with a tool, answer a follow-up from the conversation, and write a
two-sentence customer message. One session per model, one after another.

## How the client was set up

{setup_lines}

## The numbers

{HEADER}
{DIVIDER}
{chr(10).join(summary_row(s) for s in sessions)}

- **Warm-up** is one tiny request sent first, so loading the model is not counted as a
  first token. A long warm-up means the engine had to load it.
- **First token** is the wait before the first streamed token of a request. On the
  later requests the conversation so far is a prefix the engine can reuse, so a cache
  hit shows as a short wait there even when no count is reported.
- **Cached** is what the client was told. `not reported` means the reply carried no
  cache field — LMStudio's chat completions route never does
  (lmstudio-ai/lmstudio-bug-tracker#778) — not that the cache missed.
- **Decode tok/s** is the median over the requests, from the first streamed token to
  the last, thinking included.
{note_lines}

## Every request

{chr(10).join(detail_table(s) + chr(10) for s in sessions)}"""
    target = folder / "RESULTS.md"
    target.write_text(text, encoding="utf-8")
    return target


# ============================== END OF THE SHARED PART ==============================


if __name__ == "__main__":
    main()
