"""The benchmark task through LangGraph: demo 2's loop, timed request by request.

    uv run run_benchmark.py                                   every default alias
    uv run run_benchmark.py --aliases lms-gemma4-26b          one alias
    uv run run_benchmark.py --aliases lms-gemma4-26b --no-write

The graph is the one run.py builds by hand — a model node, a `ToolNode` and
`tools_condition` between them — plus an in-memory checkpointer, so the three turns
are one thread and each `invoke` adds one user message to it. The model is
`ChatOpenAI(streaming=True, stream_usage=True)`, bound to one LangChain tool that
carries the task's `read_file` schema byte for byte. The task, the table and
RESULTS.md come from the shared part at the
bottom of this file.

WHAT IS MEASURED, AND HOW. A callback handler on the model sees every request the
graph makes: `on_chat_model_start` starts the clock, each streamed chunk marks a
token, and `on_llm_end` reads `usage_metadata` off the finished message — prompt
tokens, `input_token_details.cache_read`, output tokens and
`output_token_details.reasoning`. One record per request, not per turn.

TWO THINGS LANGCHAIN HIDES, both measured on LMStudio through both gateways
(2026-09-30):

- THE THINKING TEXT. ChatOpenAI drops `reasoning_content`, so a thinking token
  reaches the callback as a chunk with no text. The clock therefore counts every
  chunk except the three that close a stream (finish, usage, and LangChain's own
  `chunk_position="last"`). Both gateways' first frame already carries a token, so
  the first chunk IS the first token, thinking included. The thinking COUNT survives,
  in `usage_metadata`.
- NOTHING ABOUT THE CACHE IS INVENTED. With no cache field in the reply,
  `input_token_details` comes back `{}` — `cache_read` absent, not 0 — so a row
  saying `not reported` means what it means in every other folder.

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS. Everything specific is in settings.py.
Its shared part — the task, the record, the table — is the same in every folder.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, LLMResult
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from settings import API_KEY, BASE_URL, MAX_TOKENS, NAME, REASONING_EFFORT, REQUEST_TIMEOUT_SECONDS, STREAM_USAGE

HERE = Path(__file__).resolve().parent
MAX_REQUESTS_PER_TURN = 4

# The task's function tool as a LangChain tool. The JSON schema is passed as-is rather
# than inferred from a signature, so `bind_tools` sends exactly READ_FILE_TOOL — the
# tool folder 1 sends by hand (checked with `convert_to_openai_tool`, 2026-09-30).
def read_file_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=read_file,
        name=READ_FILE_TOOL["function"]["name"],
        description=READ_FILE_TOOL["function"]["description"],
        args_schema=READ_FILE_TOOL["function"]["parameters"],
    )


def carries_token(chunk: ChatGenerationChunk) -> bool:
    """Whether a streamed chunk is a token, thinking included — see the note at the top.

    A chunk with no text is still a token unless it is one of the three that close
    the stream: the finish frame, the usage frame, and LangChain's `last` marker.
    """
    message = chunk.message
    if chunk.text or message.tool_call_chunks:
        return True
    closing = (
        (chunk.generation_info or {}).get("finish_reason")
        or message.usage_metadata
        or message.chunk_position == "last"
    )
    return not closing


class Meter(BaseCallbackHandler):
    """One Record per model request, from the callbacks LangChain fires around it."""

    # A handler's exception is otherwise logged and swallowed, and the session would
    # pass with records missing.
    raise_error = True

    def __init__(self, session: Session) -> None:
        self.session = session
        self.turn = 0
        self.clocks: dict[UUID, Clock] = {}

    def on_chat_model_start(self, serialized: dict, messages: list[list[BaseMessage]], *, run_id: UUID, **kwargs: Any) -> None:
        self.clocks[run_id] = Clock()

    def on_llm_new_token(self, token: str, *, chunk: ChatGenerationChunk | None = None, run_id: UUID, **kwargs: Any) -> None:
        if chunk is not None and carries_token(chunk):
            self.clocks[run_id].token()

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        clock = self.clocks.pop(run_id)
        usage = response.generations[0][0].message.usage_metadata or {}
        output_tokens = usage.get("output_tokens")
        self.session.records.append(Record(
            turn=self.turn,
            ttft_s=clock.ttft(),
            seconds=clock.elapsed(),
            decode_tok_s=decode_rate(output_tokens, clock.first, clock.last),
            prompt_tokens=usage.get("input_tokens"),
            # ABSENT, not zero, when the reply has no cache field — see the note at the top.
            cached_tokens=usage.get("input_token_details", {}).get("cache_read"),
            output_tokens=output_tokens,
            reasoning_tokens=usage.get("output_token_details", {}).get("reasoning"),
        ))


def build_graph(alias: str, meter: Meter) -> CompiledStateGraph:
    """run.py's demo 2, streaming, metered, and with a memory of the conversation."""
    tool = read_file_tool()
    model = ChatOpenAI(
        model=alias,
        base_url=BASE_URL,
        api_key=API_KEY,
        max_tokens=MAX_TOKENS,
        reasoning_effort=REASONING_EFFORT,
        # Streaming is what lets the first and the last token be timed; without
        # `stream_usage` the streamed reply would carry no token counts.
        streaming=True,
        stream_usage=STREAM_USAGE,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
        callbacks=[meter],
    ).bind_tools([tool])

    def call_model(state: MessagesState) -> dict:
        return {"messages": [model.invoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode([tool]))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")
    return builder.compile(checkpointer=InMemorySaver())


def one_session(alias: str, session: Session) -> None:
    meter = Meter(session)
    graph = build_graph(alias, meter)
    # The thread id is what makes three `invoke` calls one conversation: the
    # checkpointer hands each one the messages so far. Each request is a model step
    # plus a tool step, so this limit stops a turn at MAX_REQUESTS_PER_TURN requests.
    config = {"configurable": {"thread_id": alias}, "recursion_limit": 2 * MAX_REQUESTS_PER_TURN}
    for turn, question in enumerate(turns(), 1):
        meter.turn = turn
        state = graph.invoke({"messages": [{"role": "user", "content": question}]}, config)
        problem = check_answer(turn, state["messages"][-1].text)
        if problem:
            session.problem = problem
            return


def warm(alias: str) -> float:
    """One tiny request carrying what ChatOpenAI puts in every body: the level, and
    the ceiling under the name ChatOpenAI gives it, `max_completion_tokens`.
    """
    extras: dict = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}
    if MAX_TOKENS:
        extras["max_completion_tokens"] = MAX_TOKENS
    return warm_up(BASE_URL, API_KEY, alias, extras)


def main() -> None:
    args = parse_args(__doc__)
    started = time.perf_counter()
    aliases = [a for a in args.aliases.split(",") if a]
    sessions = run_all(aliases, one_session, warm)
    print(f"\n{len(sessions)} sessions in {time.perf_counter() - started:.0f} s")
    if not args.no_write:
        setup = {
            "Client": "`ChatOpenAI` from `langchain-openai`, inside a LangGraph `StateGraph` — model node, "
                      "`ToolNode`, `tools_condition` — with an `InMemorySaver` holding the conversation",
            "Gateway": f"{NAME}, `{BASE_URL}/chat/completions`",
            "Thinking level": f"`reasoning_effort=\"{REASONING_EFFORT}\"` on ChatOpenAI, in every body"
                              if REASONING_EFFORT else "none sent",
            "Ceiling": f"`max_tokens={MAX_TOKENS}` on ChatOpenAI, sent as `max_completion_tokens`"
                       if MAX_TOKENS else "none sent — the gateway's route stores one",
            "Streaming": f"`streaming=True`, `stream_usage={STREAM_USAGE}` — ChatOpenAI turns streamed usage "
                         "off by itself once `base_url` is set",
            "Retries and sampling": "`max_retries=0`; no temperature sent, so the engine's default",
            "Tool": "one `StructuredTool`, `read_file`, carrying the task's JSON schema; `ToolNode` runs it",
            "Measured": "per model request, by a callback handler: `on_chat_model_start` to the first and last "
                        "streamed chunk, then `usage_metadata` in `on_llm_end`",
        }
        notes = (
            "ChatOpenAI drops `reasoning_content`, so a thinking token arrives as an empty chunk. The first-token "
            "clock counts every chunk but the finish, usage and `last` frames; thinking counts come from "
            "`usage_metadata.output_token_details.reasoning`.",
            "`cache_read` is absent from `usage_metadata` when the reply carries no cache field — LangChain does "
            "not turn it into 0 — so `not reported` means the same as in every other folder.",
        )
        print(f"wrote {write_results(HERE, 'LangChain + LangGraph', NAME, setup, sessions, notes)}")


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
