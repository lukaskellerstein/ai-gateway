"""Where this gateway is, and the OpenCode server every scenario drives.

THE NUMBERED SCRIPTS BESIDE THIS ONE ARE BYTE-IDENTICAL TO LITELLM'S. Every
difference between the two gateways lives here.

OPENCODE HAS NO PYTHON SDK. What it has is a documented HTTP server API: you
start `opencode serve` and everything after that is ordinary REST. So the
"SDK" below is sixty lines of `httpx`, which is the honest shape of the
integration and reads better than a wrapper would.

HOW THE GATEWAY IS SELECTED: a CUSTOM PROVIDER, declared inline. OpenCode
resolves providers through the Vercel AI SDK, and `@ai-sdk/openai-compatible` is
the driver for anything that speaks the OpenAI protocol — which is what this
gateway is. The whole configuration is a dict handed to the server through
`OPENCODE_CONFIG_CONTENT`, so nothing is written to your `~/.config/opencode`
and a run cannot disturb your own setup.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent

# The shared facts — the base URL, the key, the alias.
sys.path.insert(0, str(HERE.parent))

from gateway import ALIAS, API_KEY, BASE_URL, NAME, ROOT_URL  # noqa: E402

DEFAULT_MODEL = ALIAS

# WHAT `run_all.py` PROBES BEFORE IT STARTS. Liveliness, not readiness: these
HEALTH_URL = f"{ROOT_URL}/health/liveliness"
START_HINT = "cd ../.. && podman compose up -d"

# The provider id carries the gateway's name, so a stray `~/.config/opencode`
# entry cannot collide with it.
PROVIDER_ID = f"ai-gateway-{NAME}"

# Scenario 04 has OpenCode spawn this file and talk to it over stdio.
STDIO_SERVER = HERE / "mcp_server.py"
START_MARKER = HERE / ".mcp_server_started"
CALL_MARKER = HERE / ".mcp_tool_called"


def config_for(alias: str, **extra: Any) -> dict:
    """The whole OpenCode configuration, as a dict.

    `small_model` is set as well as `model`: OpenCode uses a cheaper model for
    side jobs like naming a session, and left unset it falls back to a provider
    you may not have configured — which fails at a moment unrelated to your
    prompt.
    """
    config: dict[str, Any] = {
        "autoupdate": False,
        "provider": {
            PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": f"AI Gateway ({NAME})",
                "options": {"baseURL": BASE_URL, "apiKey": API_KEY},
                "models": {alias: {"name": alias}},
            }
        },
        "model": f"{PROVIDER_ID}/{alias}",
        "small_model": f"{PROVIDER_ID}/{alias}",
        # A transport test has no business editing files or running commands.
        # It is also the lever that stops a small model answering a tool
        # question with the shell — see 04.
        "permission": {"bash": "deny", "edit": "deny"},
    }
    config.update(extra)
    return config


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@asynccontextmanager
async def opencode_server(alias: str, **extra: Any):
    """Start `opencode serve` on a free port, yield a client, always stop it.

    A free port rather than a fixed one because this must not collide with an
    OpenCode the user already has running — and because `../run_all.py` may run
    folders back to back.
    """
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    environment = {**os.environ, "OPENCODE_CONFIG_CONTENT": json.dumps(config_for(alias, **extra))}

    process = await asyncio.create_subprocess_exec(
        "opencode", "serve", "--hostname=127.0.0.1", f"--port={port}",
        cwd=str(HERE), env=environment,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        # A local model can take minutes to answer, so the request timeout is an
        # hour — the same 3600 s every route in ../../config/ allows.
        async with httpx.AsyncClient(base_url=url, timeout=3600.0) as client:
            for _ in range(300):
                if process.returncode is not None:
                    raise RuntimeError(f"opencode exited during startup with status {process.returncode}")
                try:
                    if (await client.get("/global/health", timeout=1.0)).is_success:
                        break
                except (httpx.HTTPError, OSError):
                    pass
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError(f"opencode did not become healthy at {url}")
            yield client
    finally:
        process.terminate()
        await process.wait()


async def new_session(client: httpx.AsyncClient, title: str) -> str:
    response = await client.post("/session", json={"title": title})
    response.raise_for_status()
    return response.json()["id"]


async def ask(client: httpx.AsyncClient, session_id: str, text: str, **body: Any) -> dict:
    """One prompt, one reply. Extra keys go straight into the request body."""
    payload: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
    payload.update(body)
    response = await client.post(f"/session/{session_id}/message", json=payload)
    response.raise_for_status()
    return response.json()


def text_of(message: dict) -> str:
    """A reply is a list of typed parts. Only the `text` ones are the answer."""
    return "".join(part.get("text", "") for part in message.get("parts") or [] if part.get("type") == "text")


def tools_of(message: dict) -> list[str]:
    """The tools the model actually invoked, by name.

    THIS IS A REPORT LINE, NOT AN ASSERTION, and it is often empty even when a
    tool ran: OpenCode returns the assistant's final message, and the tool parts
    can live in earlier messages of the session. `04_mcp.py` therefore asserts
    on the MCP server's own marker files, which cannot be empty by accident.
    """
    names = []
    for part in message.get("parts") or []:
        if part.get("type") == "tool":
            names.append(str(part.get("tool") or part.get("name") or "?"))
    return names


def says(message: dict, value: str) -> bool:
    """Is `value` in the reply, ignoring case, Markdown bold and digit commas?"""
    return value.lower() in text_of(message).lower().replace("*", "").replace(",", "")


def report(label: str, message: dict) -> None:
    print(f"  {label:12s} tools={','.join(tools_of(message)) or '-'}")
    print(f"  {'':12s} {text_of(message).strip()[:160]!r}")


Scenario = Callable[[str], Awaitable[str]]


def run(scenario: Scenario, description: str) -> int:
    """Parse `--model`, drive one scenario, print one PASS/FAIL row."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"alias to call (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    title = description.strip().splitlines()[0]
    print(f"\n{'=' * 70}\n{title}")

    if shutil.which("opencode") is None:
        print("\nFAIL  the `opencode` binary is not on PATH. Install it from https://opencode.ai")
        return 1

    print(f"{NAME} -> {BASE_URL}  model={args.model}\n{'=' * 70}")
    started = time.perf_counter()
    try:
        summary, passed = asyncio.run(scenario(args.model)), True
    except Exception as error:  # noqa: BLE001 — a failing scenario reports, it does not crash
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {NAME:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1
