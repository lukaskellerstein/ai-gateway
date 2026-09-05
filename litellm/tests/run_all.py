"""Run every folder here against this project's gateway, in one table.

Each folder is a separate uv project and a separate row, so one failure names
itself instead of hiding inside a combined result. `uv run --directory` builds
whichever venv is missing, so a fresh clone needs no `uv sync` first.

    uv run run_all.py
    uv run run_all.py --model lms-26b
    uv run run_all.py --only 6_codex_sdk
    uv run run_all.py --verbose

IT DRIVES 24000 AND NOTHING ELSE. Each gateway is a standalone compose project, so
the Envoy suite is `../../envoy/tests/`, and NOTHING ANYWHERE compares the two —
see the note in README.md.

THIS SCRIPT HAS NO DEPENDENCIES, and must not grow any: it is the entry point that
runs before any venv exists.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Unauthenticated liveness route. LiteLLM's /health needs the master key;
# /health/liveliness does not, and this check is only asking "is the port
# answering at all" before seven folders fail the same way.
HEALTH_URL = "http://localhost:24000/health/liveliness"

# Folders in the order they should be read, which is also the order of increasing
# distance from the wire: raw HTTP, then the OpenAI client, then five agents.
FOLDERS = (
    "1_http_client",
    "2_openai_client",
    "3_langchain_langgraph",
    "4_deepagents",
    "5_claude_agent_sdk",
    "6_codex_sdk",
    "7_opencode_sdk",
)


def entry_point(folder: Path) -> str:
    """`run_all.py` if the folder has its own suite, else `main.py`.

    Only `2_openai_client` has one — four numbered scripts and a runner of its
    own. Everything else is a single `main.py`, so a new folder needs no edit here
    beyond its name in FOLDERS above.
    """
    return "run_all.py" if (folder / "run_all.py").is_file() else "main.py"


def is_up() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5):
            return True
    except (urllib.error.URLError, OSError):
        return False


def run_one(name: str, model: str | None, verbose: bool) -> tuple[bool, float, str]:
    folder = HERE / name
    command = ["uv", "run", "--directory", str(folder), entry_point(folder)]
    if model:
        command += ["--model", model]

    # VIRTUAL_ENV IS DROPPED, or uv warns on every row. This script is itself run
    # with `uv run`, so VIRTUAL_ENV points at THIS folder's venv while the child
    # is told to use the sub-folder's — and uv prints a paragraph about the
    # mismatch before doing the right thing anyway.
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}

    # `--model` MUST ALSO REACH THE CHILD AS AN ENVIRONMENT VARIABLE, not only on argv.
    # gateway.py resolves the alias at IMPORT time, before any scenario's argparse runs, so
    # on an engine whose default alias is None — `openai` — it raised there and every folder
    # died in 0.0 s with "no alias that passes every scenario here", while the message told
    # you to pass the `--model` that had just been ignored. Measured 2026-09-05, all four
    # paid folders. `AI_GATEWAY_TEST_MODEL` is the one hook gateway.py reads FIRST.
    if model:
        environment["AI_GATEWAY_TEST_MODEL"] = model

    started = time.perf_counter()
    finished = subprocess.run(
        command, capture_output=not verbose, text=True, check=False, env=environment
    )
    seconds = time.perf_counter() - started
    output = "" if verbose else (finished.stdout or "") + (finished.stderr or "")
    return finished.returncode == 0, seconds, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="alias to call in every folder (default: follows GATEWAY_ENGINE)")
    parser.add_argument("--only", choices=FOLDERS, help="run one folder instead of all seven")
    parser.add_argument("--verbose", action="store_true", help="stream each folder's output instead of capturing it")
    args = parser.parse_args()

    if not is_up():
        print(
            f"the LiteLLM gateway is not answering on {HEALTH_URL} — start it with "
            "`cd .. && podman compose up -d`",
            file=sys.stderr,
        )
        return 1

    chosen = [args.only] if args.only else list(FOLDERS)
    print(f"gateway=litellm  model={args.model or 'from GATEWAY_ENGINE'}  folders={len(chosen)}\n")

    rows: list[tuple[str, bool, float]] = []
    failures: list[tuple[str, str]] = []
    for name in chosen:
        passed, seconds, output = run_one(name, args.model, args.verbose)
        rows.append((name, passed, seconds))
        print(f"{'PASS' if passed else 'FAIL'}  {name:24s} {seconds:6.1f}s")
        if not passed and output:
            failures.append((name, output))

    for name, output in failures:
        print(f"\n{'=' * 70}\noutput of the failed run: {name}\n{'=' * 70}\n{output}")

    passed_count = sum(1 for _, passed, _ in rows if passed)
    print(f"\n{passed_count}/{len(rows)} passed")
    return 0 if passed_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
