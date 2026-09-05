"""The Anthropic surface of THIS gateway, and the machinery every scenario shares.

THE SIX NUMBERED SCRIPTS BESIDE THIS ONE ARE BYTE-IDENTICAL TO ENVOY'S. Every
difference between the two gateways lives here, as data — the same rule
`../2_openai_client/common.py` follows for the OpenAI surface. A scenario that
read the gateway's name would have stopped being portable, and porting these six
files to a third gateway is then a copy plus one new `common.py`.

WHAT IS DIFFERENT ABOUT LITELLM, and it is one function: `anthropic_alias()`
below returns the alias unchanged, because there is nothing to work around.
LiteLLM serves POST /v1/messages beside its OpenAI routes and carries an agent
conversation on the ordinary alias.

THE COMPARISON IS THE POINT OF HAVING BOTH FOLDERS. Envoy translates
Anthropic -> OpenAI onto the engine's OpenAI schema, and that path cannot hold a
conversation: it passes the reply's `thinking` blocks straight into the OpenAI
body, where a `content` part may only be `text` or `image_url`, and the engine
answers `400 messages.N.content.str`. Envoy needs a second, `Anthropic`-schema
alias to get round it. LiteLLM needs none — verified 2026-09-04, a multi-turn
request carrying a `thinking` block returned 200 on the plain `unsloth-4b`.

That is a real difference between the two gateways and it belongs here, in the
one file per project that is allowed to know which gateway it is talking to.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
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

# WHAT `run_all.py` PROBES BEFORE IT STARTS. Liveliness and not readiness on
# purpose: these scenarios need the proxy to answer, not the database to be
# attached, and a suite that refuses to run over a missing database would hide
# the fact that completions keep working without one.
HEALTH_URL = f"{ROOT_URL}/health/liveliness"
START_HINT = "cd ../.. && podman compose up -d"

# REASONING REACHES THE CALLER ON EVERY ENGINE, and it took a config line in
# ../../config/settings.yaml to make that true. It was a PER-ENGINE table until
# 2026-09-05 — unsloth False, lms and ollama True — and the table was a symptom,
# not a fact about engines.
#
# WHAT IT ACTUALLY WAS: `/v1/messages` picks its upstream route by PROVIDER, and
# `_RESPONSES_API_PROVIDERS = frozenset({"openai"})` sends anything on the
# `openai/` provider through the RESPONSES API bridge, which does not carry
# `reasoning_content`. Our engines split exactly on that line — `lms-*` is
# `lm_studio/` and never went through the bridge, `ollama-*` and `unsloth-*` are
# `openai/` and did. `use_chat_completions_url_for_anthropic_messages: true`
# forces the chat-completions path, where the adapter already falls back to
# `reasoning_content`. Measured on 1.99.1, unsloth-4b, after the flag:
# 6 streaming runs out of 6 carried thinking, against 0 out of 5 before.
#
# IT WAS NOT THE TWO ISSUES THAT WERE CLOSED. BerriAI/litellm#29518 and #27946
# had both closed BEFORE any of this was measured, and neither fixes it;
# #29518's fix already shipped in 1.95.0. Do not read their closure as the cure.
#
# Envoy declares the same flat `True` for a different reason: its `-anthropic`
# alias does not translate at all, so the engine's own block arrives whole.
THINKING_REACHES_CLIENT = True

# PRINTED BY 07_thinking.py ON EVERY RUN. Empty — nothing left to warn about.
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
    """The alias itself. LiteLLM speaks Anthropic on every route it serves.

    IT EXISTS SO THE SIX SCENARIOS DO NOT HAVE TO KNOW THAT. Envoy's copy of this
    function resolves a second, pass-through alias and refuses to run without it;
    the scenarios call the same name and never learn which gateway answered.
    """
    return alias


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
