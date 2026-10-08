"""The benchmark task through OpenCode: its own agent, its own `read` tool, one session.

    uv run run_benchmark.py                                   every default alias
    uv run run_benchmark.py --aliases lms-gemma4-26b          one alias
    uv run run_benchmark.py --aliases lms-gemma4-26b --no-write

ONE `opencode serve` AND ONE SESSION PER ALIAS, started exactly as every scenario here
starts it (`common.opencode_server`), in a temporary working directory holding a real
`order.json`. The three turns are three prompts to that session, so turns 2 and 3
resend the whole conversation and the engine can reuse its prefix. OpenCode reads the
file with its own `read` tool; nothing here answers it. The task, the table and
RESULTS.md come from the shared part at the
bottom of this file.

WHAT IS MEASURED, AND HOW. OpenCode decides how many model requests a turn takes and
sends them itself. Its event stream, `GET /event`, reports each one as a STEP, live:

    session.status  busy    OpenCode is about to send a request: the clock starts
    message.part.delta      a streamed chunk of text or thinking: first and last are marked
    message.part.updated    a `tool` part going pending, then running: a streamed tool call
                   step-finish  the request's `tokens`, and the end of its clock

`step-start` is no use as the start: it arrives WITH the first chunk. The last `busy`
before it came 5-17 ms before the request reached a stub provider (2026-09-30).

THE COUNTS ARE OPENCODE'S, SPLIT ITS WAY: `input` leaves out the cached tokens and
`output` leaves out the thinking. So the prompt is input + cache.read + cache.write
and the output is output + reasoning — the gateway's `prompt_tokens` and
`completion_tokens`, checked against a stub provider that sent both (2026-09-30).

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS. Everything specific is in settings.py.
Its shared part — the task, the record, the table — is the same in every folder.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from common import ask, new_session, opencode_server, text_of
from settings import API_KEY, BASE_URL, NAME, OPENCODE_ENVIRONMENT, PROVIDER_ID, REASONING_EFFORT

HERE = Path(__file__).resolve().parent

# How long the last events of a turn may trail the reply that ended it.
IDLE_WAIT_SECONDS = 30.0


class StepRecorder:
    """One `Record` per model request, built from OpenCode's events as they arrive.

    Live rather than afterwards because `Clock` marks the moment it is called, and
    an event is handled the moment it is read off the stream.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.session_id = ""
        self.turn = 0
        self.sent_at = time.perf_counter()
        self.clock: Clock | None = None
        self.connected = asyncio.Event()
        self.idle = asyncio.Event()

    def on_event(self, event: dict) -> None:
        kind = event["type"]
        properties = event.get("properties") or {}
        if kind == "server.connected":
            self.connected.set()
        elif properties.get("sessionID") != self.session_id:
            return
        elif kind == "session.status" and properties["status"]["type"] == "busy" and self.clock is None:
            self.sent_at = time.perf_counter()
        elif kind == "session.idle":
            self.idle.set()
        elif kind == "message.part.delta" and self.clock:
            self.clock.token()
        elif kind == "message.part.updated":
            self.on_part(properties["part"])

    def on_part(self, part: dict) -> None:
        if part["type"] == "step-start":
            self.clock = Clock()
            self.clock.start = self.sent_at
        elif part["type"] == "tool" and self.clock and part["state"]["status"] in ("pending", "running"):
            self.clock.token()
        elif part["type"] == "step-finish" and self.clock:
            self.session.records.append(self.record(part["tokens"], self.clock))
            self.clock = None

    def record(self, tokens: dict, clock: Clock) -> Record:
        cache = tokens["cache"]
        output_tokens = tokens["output"] + tokens["reasoning"]
        return Record(
            turn=self.turn,
            ttft_s=clock.ttft(),
            seconds=clock.elapsed(),
            decode_tok_s=decode_rate(output_tokens, clock.first, clock.last),
            prompt_tokens=tokens["input"] + cache["read"] + cache["write"],
            # ZERO, NOT ABSENT, when the reply had no cache field: OpenCode writes
            # `cache.read: 0` for it (stub provider, 2026-09-30).
            cached_tokens=cache["read"],
            output_tokens=output_tokens,
            reasoning_tokens=tokens["reasoning"],
        )


async def listen(client: httpx.AsyncClient, recorder: StepRecorder) -> None:
    """Hand every event on the server's stream to the recorder, until cancelled."""
    async with client.stream("GET", "/event", timeout=None) as response:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                recorder.on_event(json.loads(line.removeprefix("data:")))


async def converse(alias: str, session: Session) -> None:
    recorder = StepRecorder(session)
    with tempfile.TemporaryDirectory() as root:
        write_order_file(Path(root))
        async with opencode_server(alias, directory=Path(root)) as client:
            listener = asyncio.create_task(listen(client, recorder))
            try:
                await asyncio.wait_for(recorder.connected.wait(), IDLE_WAIT_SECONDS)
                recorder.session_id = await new_session(client, "benchmark")
                for turn, question in enumerate(turns(), 1):
                    recorder.turn = turn
                    recorder.idle.clear()
                    recorder.sent_at = time.perf_counter()
                    requests_before = len(session.records)
                    answer = await ask(client, recorder.session_id, question)
                    # A BROKEN MEASUREMENT MUST FAIL THE RUN, not shorten the row: a
                    # listener that raised is only seen when asked for its result.
                    if listener.done():
                        listener.result()
                    await asyncio.wait_for(recorder.idle.wait(), IDLE_WAIT_SECONDS)
                    error = (answer.get("info") or {}).get("error")
                    if error:
                        raise RuntimeError(json.dumps(error)[:200])
                    if len(session.records) == requests_before:
                        raise RuntimeError(f"turn {turn} answered, but no `step-finish` event was seen")
                    problem = check_answer(turn, text_of(answer))
                    if problem:
                        session.problem = problem
                        return
            finally:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)


def one_session(alias: str, session: Session) -> None:
    asyncio.run(converse(alias, session))


def level_extras() -> dict:
    """What OpenCode adds to every body besides its own `max_tokens`, for the warm-up."""
    return {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}


def opencode_version() -> str:
    return subprocess.run(["opencode", "--version"], capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    args = parse_args(__doc__)
    started = time.perf_counter()
    aliases = [a for a in args.aliases.split(",") if a]
    sessions = run_all(aliases, one_session, lambda a: warm_up(BASE_URL, API_KEY, a, level_extras()))
    print(f"\n{len(sessions)} sessions in {time.perf_counter() - started:.0f} s")
    if not args.no_write:
        setup = {
            "Client": f"OpenCode {opencode_version()}, `opencode serve` driven over its HTTP API with `httpx` "
                      "— OpenCode has no Python SDK",
            "Gateway": f"{NAME}, `{BASE_URL}/chat/completions`, as the custom provider `{PROVIDER_ID}` on "
                       "`@ai-sdk/openai-compatible`, handed in through `OPENCODE_CONFIG_CONTENT`",
            "Thinking level": f"the model option `reasoningEffort: {REASONING_EFFORT}`, which the provider sends "
                              "as `reasoning_effort` in every body" if REASONING_EFFORT else "none sent",
            "Ceiling": "none set here — OpenCode sends `max_tokens: 32000` on every request, its default for a "
                       "model it has no catalogue entry for",
            "Agent": "OpenCode's built-in `build` agent and its own system prompt, which names the working "
                     "directory and today's date",
            "Tools": "OpenCode's built-ins less `bash`, `edit` and `write`, which `permission` denies outright "
                     "— on 1.18.30 `glob`, `grep`, `question`, `read`, `skill`, `task`, `todowrite`, `webfetch`; "
                     "the file is read with `read`; `external_directory` is denied too, so a path outside "
                     "the working directory fails instead of waiting for an approval nobody gives",
            "Isolation": ", ".join(f"`{key}={value}`" for key, value in OPENCODE_ENVIRONMENT.items())
                         + ", so ~/.claude/CLAUDE.md and ~/.claude/skills stay out of the prompt; a provider id "
                           "no other OpenCode config declares, so ~/.config/opencode adds nothing to the model",
            "Conversation": "one session per alias, created with a title so `small_model` is never asked for one; "
                            "turns 2 and 3 resend the whole history, earlier thinking included as `reasoning_content`",
            "Working directory": "a fresh temporary directory per session, holding a real `order.json`",
            "Streaming": "always — OpenCode sends `stream: true` with `stream_options.include_usage`; the timings "
                         "come from its event stream, `GET /event`",
        }
        notes = (
            "**Requests** are OpenCode's steps, one model request each, read off `step-finish` on its event "
            "stream and filed under the turn that caused them. **Request time** runs to `step-finish`, which "
            "follows the tool the step ran — a `read` takes milliseconds.",
            "**First token** is measured from the `session.status: busy` OpenCode emits just before it sends a "
            "request to the first streamed chunk of text, thinking or a tool call.",
            "**Cached** is 0, never `not reported`, when the reply carries no cache field: OpenCode writes "
            "`cache.read: 0`. On LMStudio's chat completions route 0 therefore means NOT REPORTED "
            "(lmstudio-ai/lmstudio-bug-tracker#778); the first-token times show whether the engine reused "
            "the prefix. **Thinking** is 0 in the same way when the gateway reports no split.",
            "**The working directory is in the system prompt**, after OpenCode's own instructions, so the "
            "first request of a session can reuse the previous session's harness only up to that line.",
        )
        print(f"wrote {write_results(HERE, 'OpenCode', NAME, setup, sessions, notes)}")


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
