"""The Anthropic surface of THIS gateway, and the machinery every scenario shares.

THE SIX NUMBERED SCRIPTS BESIDE THIS ONE ARE BYTE-IDENTICAL TO LITELLM'S. Every
difference between the two gateways lives here, as data — the same rule
`../2_openai_client/common.py` follows for the OpenAI surface. A scenario that
read the gateway's name would have stopped being portable, and porting these six
files to a third gateway is then a copy plus one new `common.py`.

WHAT IS DIFFERENT ABOUT ENVOY, and it is one line: `anthropic_alias()` below.
Envoy serves /anthropic/v1/messages by TRANSLATING Anthropic -> OpenAI onto the
engine's OpenAI schema, and that translation cannot carry an agent conversation.
The reason is not the gateway:

    `thinking` blocks. Envoy builds one into every reply out of the engine's
    `reasoning_content`. Claude Code stores the reply and sends it back on the
    next turn, the translator passes the block straight into the OpenAI body, and
    the ENGINE rejects it —

        400 messages.N.content.str: Input should be a valid string

    which reads like "content must be a string" and means "no branch of the
    content union matched". Measured 2026-09-04 DIRECT ON THE ENGINE, port 8888,
    with no gateway in the path at all: byte-identical error. Unsloth, LMStudio
    and Ollama all reject it, because an OpenAI `content` part may only be `text`
    or `image_url`.

    It was intermittent, which is worse than broken: the engine emits
    `reasoning_content` on some replies and not others, so a one-shot usually
    passed and an agent run failed about one time in five.

THE CURE IS THE `-anthropic` PASS-THROUGH ALIAS, and it is already in
../config/<engine>.yaml. It points at an `AIServiceBackend` whose schema is
`Anthropic`, so the body reaches the engine UNTRANSLATED. All three local engines
serve POST /v1/messages themselves — verified 2026-09-04, 200 from each — so
there is nothing to bridge and no block to mangle. `anthropic_alias()` resolves
the caller's alias to that route and REFUSES TO RUN without it, because a run
that silently used the translated path would go red at random later.

`MAX_THINKING_TOKENS=0` USED TO BE REQUIRED HERE AND NO LONGER IS. It existed to
stop `400 thinking.type` from the same translator; on the pass-through path the
engine accepts Claude Code's `thinking` field as sent. Verified 2026-09-04: a
multi-turn session with the variable unset now completes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# The shared facts — the Anthropic base URL, the key, the alias, the port.
sys.path.insert(0, str(HERE.parent))

from gateway import (  # noqa: E402
    ALIAS,
    ANTHROPIC_BASE_URL,
    API_KEY,
    BASE_URL,
    BODY_EXTRAS,
    NAME,
    REQUEST_TIMEOUT_SECONDS,
    ROOT_URL,
)

# THE ENVIRONMENT MUST BE SET BEFORE THE SDK IS IMPORTED-AND-RUN, because the
# values are read when it spawns the CLI, and the CLI inherits this process's
# environment. Setting them after a scenario has started changes nothing.
os.environ["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
os.environ["ANTHROPIC_AUTH_TOKEN"] = API_KEY
# ANTHROPIC_API_KEY takes precedence over AUTH_TOKEN and points at Anthropic's own
# servers. Left in the shell it silently sends the prompt to api.anthropic.com and
# bills a real account, so it is removed rather than blanked.
os.environ.pop("ANTHROPIC_API_KEY", None)

import anyio  # noqa: E402

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    query,
)

DEFAULT_MODEL = ALIAS

# WHAT `run_all.py` PROBES BEFORE IT STARTS, and on Envoy it is the DATA PLANE.
# aigw's admin server on 26064 answers /health several seconds BEFORE the listener
# on 26000 accepts a connection, so probing the admin port races the thing being
# tested and the first scenario then fails with a connection reset (measured
# 2026-09-04). /v1/models needs no key and only answers once 26000 is really up.
HEALTH_URL = f"{ROOT_URL}/v1/models"
START_HINT = "cd ../.. && podman compose up -d"

# ENVOY PASSES THE ENGINE'S REASONING THROUGH, because the `-anthropic` alias does
# not translate: the engine's own `/v1/messages` reply reaches the caller as it was
# written. Verified 2026-09-04 on all three local engines — unsloth 8 runs in 8,
# LMStudio 1033 characters, Ollama 891.
#
# NO PER-ENGINE TABLE IS NEEDED HERE, and that is the whole argument for the
# pass-through alias. LiteLLM's copy of this file carries one, because its
# Anthropic route translates and then loses the reasoning for the unsloth backend
# while keeping it for the other two.
THINKING_REACHES_CLIENT = True

# PRINTED BY 07_thinking.py ON EVERY RUN. Nothing to warn about on this gateway —
# the pass-through alias carries the engine's reasoning whole.
THINKING_NOTE = ""

# Scenario 04 spawns this file as a SEPARATE PROCESS and talks to it over stdio.
STDIO_SERVER = HERE / "mcp_server.py"

# Scenario 06 loads its skill from here. A LOCAL PLUGIN RATHER THAN
# `.claude/skills`, so that `setting_sources` can stay empty: with it set to
# ["project"] the CLI walks up the tree and loads whatever CLAUDE.md it finds
# above this folder, which makes the run depend on where the repo is checked out.
# A plugin directory is self-contained and copies into another project as it is.
PLUGIN_DIR = HERE / "bench_plugin"


# ---------------------------------------------------------------------------
# Which alias carries the Anthropic protocol
# ---------------------------------------------------------------------------


def anthropic_alias(alias: str) -> str:
    """The alias that reaches the engine UNTRANSLATED — see the note at the top.

    ASKED AT RUNTIME, NEVER ASSUMED. ../config/<engine>.yaml is edited by hand and
    the answer is different per engine, so the gateway is the only honest source.

    A MISSING ROUTE IS A HARD FAILURE, not a skip. Every local engine can serve
    one, so its absence is an unfinished config file and the message says which
    file and what to add.
    """
    if alias.endswith("-anthropic"):
        return alias

    candidate = f"{alias}-anthropic"
    try:
        with urllib.request.urlopen(f"{ROOT_URL}/v1/models", timeout=10) as response:
            listed = {row["id"] for row in json.load(response).get("data", [])}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"cannot list the aliases on {ROOT_URL}/v1/models: {error}") from error

    if candidate in listed:
        return candidate

    raise SystemExit(
        f"{candidate!r} is not among the aliases this gateway serves.\n"
        f"  The Claude Agent SDK cannot run on {alias!r} alone. Envoy translates\n"
        "  Anthropic -> OpenAI for that route, and the engine rejects the `thinking`\n"
        "  blocks the replies carry — 400 messages.N.content.str, intermittently.\n"
        f"  Add a {candidate!r} rule to ../config/<engine>.yaml pointing at an\n"
        "  `Anthropic`-schema AIServiceBackend. config/unsloth.yaml is the worked\n"
        "  example, and README.md § The pass-through alias explains the shape."
    )


# ---------------------------------------------------------------------------
# Driving the agent
# ---------------------------------------------------------------------------


def reasoning_baseline(model: str) -> int:
    """How much reasoning this ROUTE produces on the OpenAI surface, in characters.

    THE ANTHROPIC ASSERTION NEEDS A BASELINE, or it cannot tell two very different
    things apart: a gateway that LOSES the reasoning, and a model that never
    produced any. `openrouter-26b` is the second — 0 characters on
    `/v1/chat/completions` as well, measured 2026-09-05, 2 runs out of 2 — and a
    flat declaration reported that as a gateway bug.

    `-anthropic` is stripped because Envoy's pass-through alias exists only on the
    Anthropic surface; the OpenAI route serves the plain name. `**BODY_EXTRAS`
    carries whatever ceiling this gateway needs, under whatever name the upstream
    accepts.

    Standard library only — folder 5's venv has no HTTP client of its own.
    """
    body = json.dumps(
        {
            "model": model.removesuffix("-anthropic"),
            "messages": [{"role": "user", "content": "What is 17 * 23? Think it through."}],
            **BODY_EXTRAS,
        }
    ).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.load(response)
    return len(payload["choices"][0]["message"].get("reasoning_content") or "")


def agent_options(model: str, **overrides: Any) -> ClaudeAgentOptions:
    """The options every scenario starts from, with its own additions on top.

    `setting_sources=[]` KEEPS THE RUN OUT OF ~/.claude AND OUT OF EVERY
    CLAUDE.md, so it behaves the same on every machine. Scenario 06 needs a skill
    and still leaves this empty — it loads a local plugin instead.

    `max_turns` IS A RUNAWAY STOP, NOT AN ASSERTION ABOUT TURN COUNT. A small
    local model sometimes emits an empty assistant turn before the real answer,
    and a ceiling of 1 raises `Reached maximum number of turns` instead of
    returning the reply it was about to produce.
    """
    settings: dict[str, Any] = {
        "model": model,
        "system_prompt": "You are a helpful assistant. Answer in one short sentence.",
        "max_turns": 6,
        # NO BUILT-IN TOOLS AT ALL, and a scenario that needs one names it.
        # `tools` is the VISIBILITY list; `allowed_tools` below is only the
        # permission list and does not hide anything. Left at the CLI's default a
        # transport test would carry Read, Bash, SendMessage and the rest, and a
        # small model reaches for whichever it recognises.
        "tools": [],
        "allowed_tools": [],
        "setting_sources": [],
        "cwd": str(HERE),
        # The CLI's own stderr — a connectors warning and a session-title probe on
        # every run, neither of which says anything about the gateway. Captured
        # rather than printed, and printed only when a scenario fails.
        "stderr": _remember_stderr,
    }
    settings.update(overrides)
    return ClaudeAgentOptions(**settings)


_STDERR: list[str] = []


def _remember_stderr(line: str) -> None:
    _STDERR.append(line.rstrip())


@dataclass
class Transcript:
    """What one exchange produced: the words, the tools, and the result line."""

    text: str = ""
    tools: list[str] = field(default_factory=list)
    turns: int = 0
    duration_ms: int = 0
    is_error: bool = False
    # HOW MUCH REASONING REACHED THIS PROCESS. Counted rather than flagged, because a
    # gateway can return an EMPTY thinking block — LiteLLM does — and "a block
    # arrived" would call that a success.
    thinking_chars: int = 0

    def used(self, name: str) -> bool:
        """Was a tool whose name CONTAINS `name` called?

        A substring rather than an exact match on purpose. The delegation tool has
        been called both `Task` and `Agent` by different CLI versions, and an MCP
        tool arrives prefixed `mcp__<server>__<tool>`. Asserting the exact string
        would make this suite fail on a CLI upgrade that changed nothing.
        """
        return any(name in tool for tool in self.tools)

    def says(self, value: str) -> bool:
        """Is `value` in the reply, ignoring case, Markdown bold and digit commas.

        THE COMMA MATTERS. A model told the warehouse holds 1204 units writes
        "1,204 units", which is the same answer formatted for a human — and an
        exact match called that a failure (measured on LiteLLM, 2026-09-04).
        """
        return value.lower() in self.text.lower().replace("*", "").replace(",", "")


async def _collect(messages: AsyncIterator[Any]) -> Transcript:
    transcript = Transcript()
    async for message in messages:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    transcript.text += block.text
                elif isinstance(block, ToolUseBlock):
                    transcript.tools.append(block.name)
                elif isinstance(block, ThinkingBlock):
                    transcript.thinking_chars += len(getattr(block, "thinking", "") or "")
        elif isinstance(message, ResultMessage):
            # ACCUMULATED, NOT OVERWRITTEN. A run that delegates emits one
            # ResultMessage per agent loop — the subagent's and then the
            # parent's — and keeping only the last reported the sub-run's
            # numbers as if they were the whole exchange.
            transcript.turns += message.num_turns
            transcript.duration_ms += message.duration_ms
            transcript.is_error = transcript.is_error or message.is_error
    return transcript


async def ask(prompt: str, options: ClaudeAgentOptions) -> Transcript:
    """One stateless exchange through `query()`."""
    return await _collect(query(prompt=prompt, options=options))


async def turn(client: ClaudeSDKClient, prompt: str) -> Transcript:
    """One exchange inside a live `ClaudeSDKClient` session."""
    await client.query(prompt)
    return await _collect(client.receive_response())


def report(label: str, transcript: Transcript) -> None:
    """One line per exchange, in the same shape for every scenario."""
    tools = ",".join(transcript.tools) or "-"
    print(
        f"  {label:12s} turns={transcript.turns} tools={tools} thinking={transcript.thinking_chars} "
        f"{transcript.duration_ms} ms\n"
        f"  {'':12s} {transcript.text.strip()[:160]!r}"
    )


# ---------------------------------------------------------------------------
# The runner every scenario ends with
# ---------------------------------------------------------------------------

Scenario = Callable[[str], Awaitable[str]]


def run(scenario: Scenario, description: str) -> int:
    """Parse `--model`, drive one scenario, print one PASS/FAIL row.

    THE SCENARIO RAISES TO FAIL. `AssertionError` is the expected way; anything
    else is a bug or a gateway error and is reported the same way, with the CLI's
    captured stderr underneath so a real error is never swallowed.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"alias to call (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    title = description.strip().splitlines()[0]
    print(f"\n{'=' * 70}\n{title}")

    if shutil.which("claude") is None:
        print("\nFAIL  the `claude` CLI is not on PATH. The SDK spawns it, and npm installs it:")
        print("      npm install -g @anthropic-ai/claude-code")
        return 1

    model = anthropic_alias(args.model)
    print(f"{NAME} -> {ANTHROPIC_BASE_URL}/v1/messages  model={model}\n{'=' * 70}")

    started = time.perf_counter()
    try:
        summary, passed = anyio.run(scenario, model), True
    except Exception as error:  # noqa: BLE001 — a failing scenario reports, it does not crash
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    if not passed and _STDERR:
        print(f"\n{'-' * 70}\nthe CLI's stderr:")
        for line in _STDERR[-20:]:
            print(f"  {line}")

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {NAME:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1
