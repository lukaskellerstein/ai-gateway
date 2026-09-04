"""Run every numbered test script against this project's gateway, in one table.

Each script is a separate child process and a separate row, so one failure names
itself instead of hiding inside a combined result.

    uv run run_all.py
    uv run run_all.py --model lms-26b
    uv run run_all.py --verbose

IT DRIVES 25000 AND NOTHING ELSE. Before the split this looped over both gateways
and printed 8 rows; each gateway is a standalone compose project now, so this is
4 rows and the LiteLLM suite is `../../litellm/tests/`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import DEFAULT_MODEL, GATEWAY

HERE = Path(__file__).resolve().parent

# MLflow needs no key at all, and /health is one of the two routes exempt from
# its Host-header check. This is only asking "is the port answering at all" before
# four scripts fail the same way.
HEALTH_URL = "http://localhost:25000/health"


def scripts() -> list[Path]:
    """Every `NN_*.py` in this folder, in order. A new test needs no edit here."""
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
    finished = subprocess.run(
        command,
        cwd=HERE,
        capture_output=not verbose,
        text=True,
        check=False,
    )
    seconds = time.perf_counter() - started
    output = "" if verbose else (finished.stdout or "") + (finished.stderr or "")
    return finished.returncode == 0, seconds, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--verbose", action="store_true", help="stream each script's output instead of capturing it")
    args = parser.parse_args()

    if not is_up():
        print(
            f"{GATEWAY.name} is not answering on {HEALTH_URL} — start it with "
            "`cd .. && podman compose up -d`",
            file=sys.stderr,
        )
        return 1

    print(f"model={args.model}  gateway={GATEWAY.name}\n")
    rows: list[tuple[str, bool, float]] = []
    failures: list[tuple[str, str]] = []

    for script in scripts():
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
