"""The machinery every deep-agent scenario shares, and `run_benchmark.py` with them.

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS, like the seven numbered scripts beside
it. Everything specific to a gateway — URL, key, alias, level, ceiling, health probe
— is in settings.py, so porting these scenarios to a third gateway is a copy plus
one new `settings.py`.

WHAT A DEEP AGENT IS, in one paragraph. DeepAgents is LangGraph with a harness
bolted on: your tools PLUS a suite the agent gets for free. In 0.7.13 that suite
is, exactly — `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`,
`delete`, `execute` and `task`. Your tools are ADDED to it, never a replacement,
so this is the folder where the model must CHOOSE among a dozen schemas rather
than one or two, and a 4B model that sails through folder 3 can lose the plot.

`write_todos` IS NOT IN THAT LIST, AND THAT IS A PROFILE DECISION RATHER THAN A
VERSION ONE. deepagents ships harness profiles, and two of them —
`_openai_codex` and `_nvidia_nemotron_3_ultra` — add `TodoListMiddleware`, while
the three Anthropic profiles and the default do not. A local gemma matches no
profile, so it gets the default and there is no planner. `02_todos.py` adds the
middleware explicitly, which is exactly what those profiles do. Without it the
model writes its plan to a FILE — request satisfied, planner never touched,
green row proving nothing (measured 2026-09-04 on deepagents 0.7.13, which is
the newest release).

REACHING THE GATEWAY IS ONE LINE, exactly as in folder 3: `create_deep_agent`
takes any LangChain chat model, so `ChatOpenAI(base_url=BASE_URL, ...)` is the
whole integration. This folder speaks the ORDINARY OpenAI protocol — no Anthropic
route, no pass-through alias, nothing special about either gateway.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from settings import (
    API_KEY,
    BASE_URL,
    MAX_TOKENS,
    MCP_SERVER_PORT,
    MODEL,
    NAME,
    REASONING_EFFORT,
    REQUEST_TIMEOUT_SECONDS,
)

HERE = Path(__file__).resolve().parent

# Scenario 05 spawns this file as a SEPARATE PROCESS and talks to it over stdio.
# Scenario 08 runs the SAME file over HTTP, behind the gateway — `gateway_mcp_server`.
STDIO_SERVER = HERE / "mcp_server.py"

# Scenario 07 reads its skill from here, THROUGH THE BACKEND rather than off the
# disk directly — `skills=["/skills/"]` is a path inside the agent's filesystem,
# and `FilesystemBackend(root_dir=HERE)` is what makes that mean this folder.
SKILLS_ROOT = "/skills/"

# A CEILING ON EVERY RUN. deepagents raises LangGraph's recursion limit to 9999
# because a deep agent legitimately takes many steps; with a small local model
# that turns a confused run into a very long one. 50 is generous for these
# scenarios and fails fast when the model has lost the plot.
RECURSION_LIMIT = 50


def build_model(alias: str, **options: Any) -> ChatOpenAI:
    """The one place settings.py becomes a chat model. Identical to folder 3's.

    `temperature=0` because an agent that writes a different plan on Tuesday is a
    bug, and `max_retries=0` because a test that silently retries hides the
    failure it exists to find. `options` are further ChatOpenAI fields:
    `run_benchmark.py` adds streaming, usage in the stream and the callback that
    times each request.
    """
    return ChatOpenAI(
        model=alias,
        base_url=BASE_URL,
        api_key=API_KEY,
        max_tokens=MAX_TOKENS,  # None sends nothing — see settings.py
        reasoning_effort=REASONING_EFFORT,  # likewise
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
        temperature=0,
        **options,
    )


@dataclass
class Transcript:
    """What one agent run produced: the tools it called, the words, the files."""

    text: str = ""
    tools: list[str] = field(default_factory=list)
    subagents: list[str] = field(default_factory=list)
    files: dict[str, Any] = field(default_factory=dict)
    todos: list[Any] = field(default_factory=list)

    def used(self, name: str) -> bool:
        """Was a tool whose name CONTAINS `name` called?

        A substring rather than an exact match: an MCP tool can arrive prefixed,
        and asserting the exact string would fail on a rename that changed
        nothing.
        """
        return any(name in tool for tool in self.tools)

    def says(self, value: str) -> bool:
        """Is `value` in the final answer, ignoring case, bold and digit commas?

        THE COMMA MATTERS. A model told 1204 writes "1,204", which is the same
        answer formatted for a human.
        """
        return value.lower() in self.text.lower().replace("*", "").replace(",", "")

    def file(self, path: str) -> str:
        """The text of one file in the VIRTUAL filesystem.

        An entry is a dict — `content` plus timestamps — not a bare string, so a
        `str(entry)` check would pass on the metadata and never read the file.
        """
        entry = self.files.get(path)
        if entry is None:
            return ""
        return str(entry.get("content", "") if isinstance(entry, dict) else entry)


def _absorb(transcript: Transcript, state: dict[str, Any]) -> None:
    for message in state.get("messages", []) or []:
        for call in getattr(message, "tool_calls", None) or []:
            transcript.tools.append(call["name"])
            if call["name"] == "task":
                # THE SUBAGENT'S NAME IS AN ARGUMENT, not a tool name. Every
                # delegation looks like `task(...)`, so without this a run that
                # called the wrong subagent would look identical to a right one.
                transcript.subagents.append(str(call["args"].get("subagent_type")))
            print(f"  tool call    {call['name']}({json.dumps(call['args'])[:150]})")
        if isinstance(message, ToolMessage):
            print(f"  tool result  {str(message.content)[:150]}")
        elif getattr(message, "content", None):
            transcript.text = str(message.content)
    if state.get("files"):
        transcript.files.update(state["files"])
    if state.get("todos"):
        transcript.todos = state["todos"]


def drive(agent: Any, prompt: str) -> Transcript:
    """Run one deep agent to completion, printing each step as it happens.

    `stream_mode="updates"` yields one dict per node that ran, which is the view
    that makes a deep agent legible: you watch it write todos, call a tool, then
    write a file, instead of waiting minutes for one block of text.
    """
    transcript = Transcript()
    for step in agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        stream_mode="updates",
        config={"recursion_limit": RECURSION_LIMIT},
    ):
        for node_output in step.values():
            _absorb(transcript, node_output or {})
    return transcript


async def adrive(agent: Any, prompt: str) -> Transcript:
    """`drive`, for the one scenario that must be async.

    MCP TOOLS ARE ASYNC. `langchain-mcp-adapters` hands back coroutine tools, so
    an agent holding them has to be driven with `astream` — `stream` raises.
    """
    transcript = Transcript()
    async for step in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        stream_mode="updates",
        config={"recursion_limit": RECURSION_LIMIT},
    ):
        for node_output in step.values():
            _absorb(transcript, node_output or {})
    return transcript


@contextmanager
def gateway_mcp_server() -> Iterator[None]:
    """Run `mcp_server.py` over HTTP, on the port the GATEWAY expects, for one scenario.

    THE AGENT IS NEVER TOLD THIS PORT. The gateway's own config points at it — an
    `mcp_servers` entry on LiteLLM, an `MCPRoute` on Envoy — and the agent gets only
    `MCP_URL`, so a scenario that passes made its calls THROUGH the gateway.

    A PORT THAT IS ALREADY TAKEN FAILS LOUDLY, rather than testing a server some
    other run left behind.
    """
    if _listening(MCP_SERVER_PORT):
        raise RuntimeError(f"port {MCP_SERVER_PORT} is already in use: another run, or a server left behind")
    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen(
            [sys.executable, str(STDIO_SERVER), "--http", str(MCP_SERVER_PORT)], stdout=log, stderr=log
        )
        try:
            deadline = time.monotonic() + 30
            while not _listening(MCP_SERVER_PORT):
                if server.poll() is not None or time.monotonic() > deadline:
                    log.seek(0)
                    output = log.read().decode(errors="replace")
                    raise RuntimeError(f"mcp_server.py never listened on {MCP_SERVER_PORT}:\n{output}")
                time.sleep(0.2)
            yield
        finally:
            server.terminate()
            server.wait(timeout=10)


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def report(transcript: Transcript) -> None:
    """The one-line summary every scenario prints after its run."""
    print(
        f"\n  tools={','.join(transcript.tools) or '-'}"
        f"{' subagents=' + ','.join(transcript.subagents) if transcript.subagents else ''}"
        f" files={sorted(transcript.files) or '-'}"
    )
    print(f"  answer  {transcript.text.strip()[:200]!r}")


Scenario = Callable[[str], Any]


def run(scenario: Scenario, description: str, is_async: bool = False) -> int:
    """Parse `--model`, drive one scenario, print one PASS/FAIL row.

    THE SCENARIO RAISES TO FAIL. `AssertionError` is the expected way; anything
    else is a bug or a gateway error and is reported the same way.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=MODEL, help=f"alias to call (default: {MODEL})")
    args = parser.parse_args()

    title = description.strip().splitlines()[0]
    print(f"\n{'=' * 70}\n{title}")
    print(f"{NAME} -> {BASE_URL}  model={args.model}\n{'=' * 70}")

    started = time.perf_counter()
    try:
        if is_async:
            import asyncio

            summary = asyncio.run(scenario(args.model))
        else:
            summary = scenario(args.model)
        passed = True
    except Exception as error:  # noqa: BLE001 — a failing scenario reports, it does not crash
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {NAME:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1
