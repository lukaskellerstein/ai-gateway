"""The benchmark task through the Claude Agent SDK: the `claude` CLI holds the conversation.

    uv run run_benchmark.py                                   every default alias
    uv run run_benchmark.py --aliases lms-gemma4-26b          one alias
    uv run run_benchmark.py --aliases lms-gemma4-26b --no-write

ONE `ClaudeSDKClient` CONVERSATION PER ALIAS, three `query()` calls — the shape of
02_session.py. The CLI runs in a fresh temporary directory holding `order.json`, and
its own `Read` is the only tool it is offered, so turn 1 is answered by reading it.

WHAT IS MEASURED, AND HOW. `include_partial_messages=True` hands this process the raw
Anthropic stream of every model request the conversation makes. `message_start` …
`message_stop` is ONE request and one row:

    start        the CLI's own `requesting` status, sent as the request goes out.
                 Not `message_start`: LiteLLM sends that at once, LMStudio's own
                 /v1/messages only after it has read the prompt
    tokens       every `content_block_delta` of text, thinking or tool input
    counts       the stream's `usage` — `message_delta`'s over `message_start`'s

WHAT IS NOT A ROW. The CLI makes requests of its own outside the conversation — the
session title, once, beside the first request — and they are not in the stream.
Their tokens are what the CLI's `model_usage` holds beyond the rows, and the notes
carry them per session.

The task, the table and RESULTS.md come from the shared part at the
bottom of this file.

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
from pathlib import Path

import anyio
import claude_agent_sdk
from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, StreamEvent, SystemMessage, TextBlock
from claude_agent_sdk._cli_version import __cli_version__

from common import agent_options
from settings import (
    ANTHROPIC_BASE_URL,
    API_KEY,
    BASE_URL,
    CLI_ENVIRONMENT,
    NAME,
    REASONING_EFFORT,
    anthropic_alias,
    body_extras,
)

HERE = Path(__file__).resolve().parent

# A RUNAWAY STOP PER TURN, as in every folder: one read and one answer is two requests.
MAX_REQUESTS_PER_TURN = 4

# The deltas that are the model writing. `signature_delta` closes a thinking block and
# is not a token.
TOKEN_DELTAS = {"text_delta", "thinking_delta", "input_json_delta"}

# LMSTUDIO COUNTS THE CACHE INSIDE `input_tokens`. Anthropic's own API does not: there
# `input_tokens` is only the part NOT read from the cache, and the prompt is the sum of
# the three counts. LMStudio's /v1/messages — what Envoy's `-anthropic` alias reaches —
# reports the whole prompt as `input_tokens` and the reused part beside it: one
# 1164-token prompt sent twice came back as input_tokens 1164 both times,
# cache_read_input_tokens 2 and then 1024 (2026-09-30). Summing would count the cached
# part twice. LiteLLM's `lms-*` route reports no cache at all, so the rule changes
# nothing there.
CACHE_INSIDE_INPUT = ("lms-",)

# The side requests measured on 2026-09-30, from LiteLLM's spend log: one per session.
# settings.py says what it costs and what stops it.
SIDE_REQUESTS = "the session title (`generate_session_title`), sent beside the first request"

# One line per session for RESULTS.md: what was sent, and what the CLI spent outside it.
SESSION_NOTES: list[str] = []


def prompt_tokens(alias: str, usage: dict) -> int | None:
    if "input_tokens" not in usage:
        return None
    counted = usage["input_tokens"] + (usage.get("cache_creation_input_tokens") or 0)
    if alias.startswith(CACHE_INSIDE_INPUT):
        return counted
    return counted + (usage.get("cache_read_input_tokens") or 0)


def to_record(alias: str, turn: int, clock: Clock, usage: dict) -> Record:
    output_tokens = usage.get("output_tokens")
    return Record(
        turn=turn,
        ttft_s=clock.ttft(),
        seconds=clock.elapsed(),
        decode_tok_s=decode_rate(output_tokens, clock.first, clock.last),
        prompt_tokens=prompt_tokens(alias, usage),
        # ABSENT, not zero, when the reply has no cache field — see the shared part below.
        cached_tokens=usage.get("cache_read_input_tokens"),
        output_tokens=output_tokens,
        # Anthropic's usage counts thinking INSIDE output_tokens, and the CLI's
        # `thinking_tokens` messages are its own estimate, not a count.
        reasoning_tokens=None,
    )


async def one_turn(
    client: ClaudeSDKClient, alias: str, turn: int, session: Session, sent: dict
) -> tuple[str, ResultMessage | None]:
    """Stream one `query()` to its ResultMessage: a row per request, the answer's text.

    `sent` adds up the conversation's own tokens, for `outside_the_rows()`.
    """
    text: list[str] = []
    result = None
    clock: Clock | None = None
    usage: dict = {}
    async for message in client.receive_response():
        if isinstance(message, SystemMessage) and message.data.get("status") == "requesting":
            clock = Clock()
        elif isinstance(message, StreamEvent):
            event = message.event
            kind = event.get("type")
            if kind == "message_start":
                clock = clock or Clock()
                started = event.get("message", {}).get("usage") or {}
                # LITELLM'S `message_start` IS A PLACEHOLDER: every count 0, input_tokens
                # included, sent before the engine has read anything. Kept, its 0 would
                # read as "nothing cached" where no cache was reported at all.
                usage = dict(started) if started.get("input_tokens") else {}
            elif kind == "content_block_delta" and event.get("delta", {}).get("type") in TOKEN_DELTAS:
                clock.token()
            elif kind == "message_delta":
                usage.update(event.get("usage") or {})
            elif kind == "message_stop":
                session.records.append(to_record(alias, turn, clock, usage))
                sent["input"] += usage.get("input_tokens") or 0
                sent["output"] += usage.get("output_tokens") or 0
                clock, usage = None, {}
        elif isinstance(message, AssistantMessage):
            text += [block.text for block in message.content if isinstance(block, TextBlock)]
        elif isinstance(message, ResultMessage):
            result = message
    return "".join(text), result


def outside_the_rows(result: ResultMessage | None, sent: dict) -> tuple[int, int]:
    """Input and output tokens the CLI spent on requests the stream never showed.

    `model_usage` sums every request the CLI made in the session, its own included;
    the rows are the conversation. The difference is the side requests.
    """
    models = (result.model_usage if result else None) or {}
    spent_in = sum(model.get("inputTokens", 0) for model in models.values())
    spent_out = sum(model.get("outputTokens", 0) for model in models.values())
    return spent_in - sent["input"], spent_out - sent["output"]


async def conversation(alias: str, session: Session) -> None:
    model = anthropic_alias(alias)
    sent = {"input": 0, "output": 0}
    result = None
    with tempfile.TemporaryDirectory() as folder:
        write_order_file(Path(folder))
        options = agent_options(
            model,
            # NO SYSTEM PROMPT OF OUR OWN, as in every folder: the policy in turn 1 is
            # the long prefix. The CLI still sends its one identity line.
            system_prompt=None,
            tools=["Read"],
            allowed_tools=["Read"],
            cwd=folder,
            include_partial_messages=True,
            max_turns=MAX_REQUESTS_PER_TURN,
        )
        async with ClaudeSDKClient(options=options) as client:
            for turn, question in enumerate(turns(), 1):
                await client.query(question)
                answer, result = await one_turn(client, alias, turn, session, sent)
                if result is None or result.is_error:
                    session.problem = f"turn {turn}: the CLI reported {result.subtype if result else 'no result'}"
                    break
                problem = check_answer(turn, answer)
                if problem:
                    session.problem = problem
                    break

    side_in, side_out = outside_the_rows(result, sent)
    spent = (f"{side_in} input and {side_out} output tokens outside the conversation — {SIDE_REQUESTS}"
             if side_in or side_out else "nothing outside the conversation")
    line = f"`{alias}` was sent as `{model}`; the CLI spent {spent}."
    SESSION_NOTES.append(line)
    print(f"  {line}", flush=True)


def one_session(alias: str, session: Session) -> None:
    anyio.run(conversation, alias, session)


def main() -> None:
    args = parse_args(__doc__)
    started = time.perf_counter()
    aliases = [a for a in args.aliases.split(",") if a]
    sessions = run_all(aliases, one_session, lambda a: warm_up(BASE_URL, API_KEY, a, body_extras(a)))
    print(f"\n{len(sessions)} sessions in {time.perf_counter() - started:.0f} s")
    if not args.no_write:
        cli_settings = ", ".join(f"`{k}={v}`" for k, v in CLI_ENVIRONMENT.items() if not k.startswith("ANTHROPIC_"))
        setup = {
            "Client": f"Claude Agent SDK {claude_agent_sdk.__version__}, driving the Claude Code CLI it bundles "
                      f"({__cli_version__}) — one `ClaudeSDKClient` conversation, three `query()` calls",
            "Gateway": f"{NAME}, `{ANTHROPIC_BASE_URL}/v1/messages` — the Anthropic Messages API; the model "
                       "is the alias through `anthropic_alias()` in settings.py, named per session below",
            "Thinking level": f"`CLAUDE_CODE_EFFORT_LEVEL={REASONING_EFFORT}`, sent by the CLI as "
                              "`output_config.effort`" if REASONING_EFFORT else "none set — the CLI then sends `xhigh`",
            "CLI environment": f"{cli_settings} — the two cache settings stop the CLI rewriting the top of its "
                               "prompt (settings.py); `ANTHROPIC_API_KEY` is removed",
            "Isolation": "`setting_sources=[]` — nothing from ~/.claude or any CLAUDE.md",
            "System prompt": "none of our own (`system_prompt=None`)",
            "Tool": "the CLI's own `Read`, the only tool offered (`tools=[\"Read\"]`), in a temporary directory "
                    "holding `order.json`",
            "Streaming": "`include_partial_messages=True` — the raw Anthropic stream of every request",
        }
        notes = (
            "**One row per model request**: `message_start` … `message_stop` in the raw stream. Its clock starts "
            "at the CLI's `requesting` status, because LMStudio's own /v1/messages sends `message_start` only "
            "after it has read the prompt.",
            "**Prompt tokens** are `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, "
            "Anthropic's rule — except on `lms-*`, where LMStudio already counts the cached part inside "
            "`input_tokens` (measured 2026-09-30).",
            "**Cached** is `cache_read_input_tokens`. LiteLLM's `message_start` carries every count as 0 before "
            "the engine has answered; that 0 is not taken as a count, so a route that never reports its cache "
            "reads `not reported`.",
            "**Thinking tokens** are not reported: Anthropic's usage counts thinking inside `output_tokens`.",
            "**Session** includes starting the `claude` CLI, about 0.6 s.",
            *SESSION_NOTES,
        )
        print(f"wrote {write_results(HERE, 'Claude Agent SDK', NAME, setup, sessions, notes)}")


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
