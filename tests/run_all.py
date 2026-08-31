"""Run every numbered test script against both gateways and print one table.

Each pair (script, gateway) is a separate child process and a separate row. The
scripts can do `--gateway both` themselves, but then one gateway failing hides
the other inside a single row — and "which of the two is broken" is the first
question worth answering.

    uv run run_all.py
    uv run run_all.py --model lms-qwen
    uv run run_all.py --gateway mlflow --verbose
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import DEFAULT_MODEL, GATEWAYS, selected

HERE = Path(__file__).resolve().parent

# Unauthenticated liveness route per gateway. LiteLLM's /health needs the master
# key; /health/liveliness does not, and this check is only asking "is the port
# answering at all" before six calls fail the same way.
HEALTH_URLS = {
    "litellm": "http://localhost:24000/health/liveliness",
    "mlflow": "http://localhost:25000/health",
}


def scripts() -> list[Path]:
    """Every `NN_*.py` in this folder, in order. A new test needs no edit here."""
    return sorted(HERE.glob("[0-9][0-9]_*.py"))


def is_up(name: str) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URLS[name], timeout=5):
            return True
    except (urllib.error.URLError, OSError):
        return False


def run_one(script: Path, gateway: str, model: str, verbose: bool) -> tuple[bool, float, str]:
    command = [sys.executable, str(script), "--gateway", gateway, "--model", model]
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
    parser.add_argument("--gateway", choices=[*GATEWAYS, "both"], default="both")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--verbose", action="store_true", help="stream each script's output instead of capturing it")
    args = parser.parse_args()

    gateways = [gateway.name for gateway in selected(args.gateway)]
    down = [name for name in gateways if not is_up(name)]
    if down:
        print(f"not answering: {', '.join(down)} — start the stack with `podman compose up -d`", file=sys.stderr)
        return 1

    print(f"model={args.model}  gateways={', '.join(gateways)}\n")
    rows: list[tuple[str, str, bool, float]] = []
    failures: list[tuple[str, str, str]] = []

    for script in scripts():
        for gateway in gateways:
            passed, seconds, output = run_one(script, gateway, args.model, args.verbose)
            rows.append((script.name, gateway, passed, seconds))
            print(f"{'PASS' if passed else 'FAIL'}  {script.name:22s} {gateway:8s} {seconds:6.1f}s")
            if not passed and output:
                failures.append((script.name, gateway, output))

    for name, gateway, output in failures:
        print(f"\n{'=' * 70}\noutput of the failed run: {name} on {gateway}\n{'=' * 70}\n{output}")

    passed_count = sum(1 for _, _, passed, _ in rows if passed)
    print(f"\n{passed_count}/{len(rows)} passed")
    return 0 if passed_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
