"""The OpenCode server every scenario drives, and the config it is handed.

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS, like every file here but one: where the
gateway is, which alias to call and how OpenCode is isolated all live in settings.py.

OPENCODE HAS NO PYTHON SDK. What it has is a documented HTTP server API: you
start `opencode serve` and everything after that is ordinary REST. So the
"SDK" below is sixty lines of `httpx`, which is the honest shape of the
integration and reads better than a wrapper would.

HOW THE GATEWAY IS SELECTED: a CUSTOM PROVIDER, declared inline. OpenCode
resolves providers through the Vercel AI SDK, and `@ai-sdk/openai-compatible` is
the driver for anything that speaks the OpenAI protocol — which is what this
gateway is. The whole configuration is a dict handed to the server through
`OPENCODE_CONFIG_CONTENT`, so nothing is written to your `~/.config/opencode`
and a run cannot disturb your own setup — and settings.py keeps your setup out of
the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx

from settings import (
    API_KEY,
    BASE_URL,
    MCP_SERVER_PORT,
    MODEL,
    NAME,
    OPENCODE_ENVIRONMENT,
    PROVIDER_ID,
    REASONING_EFFORT,
    REQUEST_TIMEOUT_SECONDS,
)

HERE = Path(__file__).resolve().parent

# THE THINKING LEVEL a run asks for (settings.py). OpenCode hands a model's
# `options` to the AI SDK provider, which sends `reasoningEffort` as the body's
# `reasoning_effort`.
EFFORT_MODEL_OPTIONS: dict[str, Any] = (
    {"options": {"reasoningEffort": REASONING_EFFORT}} if REASONING_EFFORT else {}
)

# Scenario 04 has OpenCode spawn this file and talk to it over stdio. Scenario 06
# runs the SAME file over HTTP, behind the gateway — `gateway_mcp_server`.
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
                "models": {alias: {"name": alias, **EFFORT_MODEL_OPTIONS}},
            }
        },
        "model": f"{PROVIDER_ID}/{alias}",
        "small_model": f"{PROVIDER_ID}/{alias}",
        # A transport test has no business editing files or running commands.
        # It is also the lever that stops a small model answering a tool
        # question with the shell — see 04. Denied outright, the tools are not
        # even offered: `bash`, `edit` and `write` are absent from every request
        # (stub provider, OpenCode 1.18.30, 2026-09-30).
        # `external_directory` is denied for the opposite reason: its default is
        # `ask`, and nobody is there to answer. Gemma 4 31B asked `read` for
        # `/order.json` — the disk root, not the working directory — and the
        # session sat on that prompt until the 3600 s request timeout
        # (lms-gemma-4-31b through Envoy, 2026-10-02). Denied, the tool returns
        # an error the model can recover from.
        "permission": {"bash": "deny", "edit": "deny", "external_directory": "deny"},
    }
    config.update(extra)
    return config


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


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@asynccontextmanager
async def opencode_server(alias: str, directory: Path = HERE, **extra: Any):
    """Start `opencode serve` on a free port, yield a client, always stop it.

    A free port rather than a fixed one because this must not collide with an
    OpenCode the user already has running — and because `../run_all.py` may run
    folders back to back. `directory` is OpenCode's working directory: the one its
    file tools see, and the one its system prompt names.
    """
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        **OPENCODE_ENVIRONMENT,
        "OPENCODE_CONFIG_CONTENT": json.dumps(config_for(alias, **extra)),
    }

    process = await asyncio.create_subprocess_exec(
        "opencode", "serve", "--hostname=127.0.0.1", f"--port={port}",
        cwd=str(directory), env=environment,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with httpx.AsyncClient(base_url=url, timeout=REQUEST_TIMEOUT_SECONDS) as client:
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
    """A new conversation. THE TITLE IS NOT DECORATION: an untitled session has
    `small_model` write one, a second model request beside the first (stub
    provider, 2026-09-30).
    """
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
    parser.add_argument("--model", default=MODEL, help=f"alias to call (default: {MODEL})")
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
