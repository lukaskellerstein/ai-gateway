"""01 one shot — a fresh Codex thread, one question.

The smallest thing Codex can do, and the first thing to check when anything else
here fails. It proves the gateway's `/v1/responses` route answers and the reply
reaches Python.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import Codex, codex_config, report, run, says, start_thread


def scenario(model: str) -> str:
    with Codex(config=codex_config(model)) as codex:
        thread = start_thread(codex, model)
        answer = thread.run("What is the capital of France? Answer in one short sentence.")
    report("query", answer)

    if not says(answer, "paris"):
        raise AssertionError(f"expected Paris, got {answer.final_response!r}")
    return f"one shot: {str(answer.final_response).strip()[:60]!r}"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
