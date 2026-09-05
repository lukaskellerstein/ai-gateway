"""Run every numbered scenario in this folder against this project's gateway.

Each scenario is a separate child process and a separate row, so one failure
names itself instead of hiding inside a combined result.

    uv run run_all.py
    uv run run_all.py --model unsloth-26b
    uv run run_all.py --verbose
    uv run 03_sdk_mcp.py                  one scenario, directly

THESE ARE SLOW, AND THAT IS THE MODEL AND NOT THE GATEWAY. Every scenario spawns
the `claude` CLI, and the agentic ones spend several turns on a local model. The
gateway's own share of it is 10-20 ms — see ../../../benchmark/.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import DEFAULT_MODEL, HEALTH_URL, NAME, START_HINT

HERE = Path(__file__).resolve().parent


def scenarios() -> list[Path]:
    """Every `NN_*.py` here, in order. A new scenario needs no edit in this file.

    `common.py` and `mcp_server.py` are deliberately outside the pattern: one is
    the shared machinery and the other is a server 04 starts, not a test.
    """
    return sorted(HERE.glob("[0-9][0-9]_*.py"))


def is_up() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5):
            return True
    except (urllib.error.URLError, OSError):
        return False


def run_one(script: Path, model: str, verbose: bool) -> tuple[bool, float, str]:
    command = [sys.executable, str(script), "--model", model]
    started = time.perf_counter()
    finished = subprocess.run(command, cwd=HERE, capture_output=not verbose, text=True, check=False)
    seconds = time.perf_counter() - started
    output = "" if verbose else (finished.stdout or "") + (finished.stderr or "")
    return finished.returncode == 0, seconds, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"alias to call (default: {DEFAULT_MODEL})")
    parser.add_argument("--verbose", action="store_true", help="stream each scenario's output instead of capturing it")
    args = parser.parse_args()

    if not is_up():
        print(f"{NAME} is not answering on {HEALTH_URL} — start it with `{START_HINT}`", file=sys.stderr)
        return 1

    print(f"model={args.model}  gateway={NAME}\n")
    rows: list[tuple[str, bool, float]] = []
    failures: list[tuple[str, str]] = []

    for script in scenarios():
        passed, seconds, output = run_one(script, args.model, args.verbose)
        rows.append((script.name, passed, seconds))
        print(f"{'PASS' if passed else 'FAIL'}  {script.name:22s} {seconds:6.1f}s")
        if not passed and output:
            failures.append((script.name, output))

    for name, output in failures:
        print(f"\n{'=' * 70}\noutput of the failed run: {name}\n{'=' * 70}\n{output}")

    passed_count = sum(1 for _, passed, _ in rows if passed)
    print(f"\n{passed_count}/{len(rows)} passed")
    return 0 if passed_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
