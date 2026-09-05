"""03 filesystem — the other half of the harness, and NOTHING TOUCHES YOUR DISK.

`write_file`, `read_file`, `ls` and `edit_file` operate on a dict inside the
graph state. That is why this scenario can write a report, read it back and
assert on it without any cleanup, and why running the suite cannot leave litter
behind.

WHAT IT PROVES ABOUT THE GATEWAY: a two-step tool chain where the SECOND call
depends on the result of the first. A gateway that loses a tool result passes 01
and fails here.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent

from common import build_model, drive, report, run

REPORT_PATH = "/bench.md"
CODE = "ZEBRA-77"


def scenario(model: str) -> str:
    agent = create_deep_agent(
        model=build_model(model),
        system_prompt="You are a helpful assistant. Save what you are asked to save with the write_file tool.",
    )
    answer = drive(
        agent,
        f"Write the exact text 'bench access code: {CODE}' to the file {REPORT_PATH} "
        "using the write_file tool. Then read it back with read_file and tell me what it says.",
    )
    report(answer)

    if not answer.used("write_file"):
        raise AssertionError(f"write_file was never called; the tools used were {answer.tools or 'none'}")
    if REPORT_PATH not in answer.files:
        raise AssertionError(f"{REPORT_PATH} is not in the virtual filesystem; it holds {sorted(answer.files)}")

    written = answer.file(REPORT_PATH)
    print(f"  {REPORT_PATH}  {written[:120]!r}")
    if CODE.lower() not in written.lower():
        raise AssertionError(f"{CODE} never reached {REPORT_PATH}: {written!r}")
    return f"filesystem: wrote and read back {REPORT_PATH} ({len(written)} chars)"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
