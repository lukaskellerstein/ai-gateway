"""The Responses surface of THIS gateway, and the machinery every scenario shares.

THE NUMBERED SCRIPTS BESIDE THIS ONE ARE BYTE-IDENTICAL TO LITELLM'S. Every
difference between the two gateways lives here — the same rule
`../5_claude_agent_sdk/common.py` follows for the Anthropic surface.

CODEX SPEAKS THE RESPONSES API AND NOTHING ELSE. `WireApi` in the Codex source
has exactly one variant, `Responses`; the `chat` variant older guides configure
was removed. So a gateway without `POST /v1/responses` cannot host Codex at all,
however well it serves chat completions. Both gateways here serve it.

HOW THE GATEWAY IS SELECTED: one `--config` line per key, exactly the keys
`~/.codex/config.toml` uses. `CodexConfig.config_overrides` turns each string
into a `--config key=value` argument on the runtime it spawns, so nothing is
written to your `~/.codex` and a run cannot disturb your own Codex setup.

`mcp_servers={}` AND `plugins={}` ARE NOT OPTIONAL, and they are the thing to
copy. Codex merges `~/.codex/config.toml` into every run, so a developer with
plugins installed hands the model their whole toolbox: on this machine that was
**~80 tools** — a full Playwright browser API, Codex Apps, site deployment —
and a small model cannot find one MCP tool in that crowd. Clearing both cuts it
to the 17 the harness itself needs. This is the Codex equivalent of
`setting_sources=[]` in folder 5, and without it the run depends on who is
sitting at the keyboard.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# The shared facts — the Responses base URL, the key, the alias.
sys.path.insert(0, str(HERE.parent))

from gateway import ALIAS, API_KEY, NAME, RESPONSES_BASE_URL, ROOT_URL  # noqa: E402

from openai_codex import (  # noqa: E402
    ApprovalMode,
    Codex,
    CodexConfig,
    Sandbox,
    TurnResult,
)

DEFAULT_MODEL = ALIAS

# WHAT `run_all.py` PROBES BEFORE IT STARTS, and on Envoy it is the DATA PLANE.
# aigw's admin server on 26064 answers /health several seconds BEFORE the
# listener on 26000 accepts a connection.
HEALTH_URL = f"{ROOT_URL}/v1/models"
START_HINT = "cd ../.. && podman compose up -d"

# Codex reads the key from an ENVIRONMENT VARIABLE THAT IT NAMES, never from the
# config value itself — `experimental_bearer_token` exists but the docs
# discourage it. A dedicated name is used rather than AI_GATEWAY_KEY so that
# nothing here depends on how the surrounding shell happens to be set up.
CODEX_KEY_ENV = "AI_GATEWAY_CODEX_KEY"
os.environ[CODEX_KEY_ENV] = API_KEY

PROVIDER = "ai_gateway"

# Scenario 04 spawns this file as a SEPARATE PROCESS and Codex talks to it over
# stdio. It writes a marker when it starts, which is what 04 asserts on.
STDIO_SERVER = HERE / "mcp_server.py"
START_MARKER = HERE / ".mcp_server_started"


def codex_config(alias: str) -> CodexConfig:
    """Every `--config` line the runtime needs to reach this gateway.

    `model_context_window` is set because Codex uses it to decide when to
    compact a conversation. Left unset for an unknown model it assumes a small
    default and compacts far too early, which on a local model looks like an
    agent that forgets things mid-task for no visible reason.
    """
    return CodexConfig(
        config_overrides=(
            f'model_providers.{PROVIDER}.name="AI Gateway ({NAME})"',
            f'model_providers.{PROVIDER}.base_url="{RESPONSES_BASE_URL}"',
            f'model_providers.{PROVIDER}.wire_api="responses"',
            f'model_providers.{PROVIDER}.env_key="{CODEX_KEY_ENV}"',
            f'model_provider="{PROVIDER}"',
            f'model="{alias}"',
            "model_context_window=122880",
            # See the note at the top — this is the isolation, not a tidy-up.
            "mcp_servers={}",
            "plugins={}",
        )
    )


def start_thread(codex: Codex, alias: str, **overrides: Any) -> Any:
    """A thread with the safe defaults every scenario wants.

    `read_only` because this is a transport test, not a coding session — a 4B
    model let loose on the repo is a second failure mode nobody asked for.
    `deny_all` because a headless run must never block waiting for a keypress.
    """
    settings: dict[str, Any] = {
        "model": alias,
        "sandbox": Sandbox.read_only,
        "approval_mode": ApprovalMode.deny_all,
    }
    settings.update(overrides)
    return codex.thread_start(**settings)


def items_of(result: TurnResult) -> list[str]:
    """The kind of every item in a turn — `agentMessage`, `mcpToolCall`, …"""
    return [item.root.type for item in (result.items or [])]


def report(label: str, result: TurnResult) -> None:
    """One line per turn, in the same shape for every scenario."""
    print(f"  {label:12s} items={','.join(items_of(result)) or '-'}")
    print(f"  {'':12s} {str(result.final_response).strip()[:160]!r}")


def says(result: TurnResult, value: str) -> bool:
    """Is `value` in the reply, ignoring case, Markdown bold and digit commas?"""
    text = str(result.final_response or "").lower().replace("*", "").replace(",", "")
    return value.lower() in text


Scenario = Callable[[str], str]


def run(scenario: Scenario, description: str) -> int:
    """Parse `--model`, drive one scenario, print one PASS/FAIL row."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"alias to call (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    title = description.strip().splitlines()[0]
    print(f"\n{'=' * 70}\n{title}")
    print(f"{NAME} -> {RESPONSES_BASE_URL}/responses  model={args.model}\n{'=' * 70}")

    started = time.perf_counter()
    try:
        summary, passed = scenario(args.model), True
    except Exception as error:  # noqa: BLE001 — a failing scenario reports, it does not crash
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {NAME:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1
