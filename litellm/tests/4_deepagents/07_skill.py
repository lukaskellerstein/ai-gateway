"""07 skill — instructions the agent loads from disk, on its own, when they apply.

A SKILL IS A FOLDER WITH A `SKILL.md`, and progressive disclosure is the whole
mechanism: only the name and description go into the system prompt, and the agent
`read_file`s the full body ONLY when the task calls for it. A hundred skills
therefore cost a hundred description lines of context, not a hundred documents.

SKILLS ARE READ THROUGH THE BACKEND, which is the part that trips people up.
`skills=["/skills/"]` is a path inside the AGENT's filesystem, not on yours, so
it needs `FilesystemBackend(root_dir=...)` to mean this folder. With the default
in-state backend there is nothing on disk to read and the skill is simply never
found.

`virtual_mode=True` keeps every OTHER file operation in state, so a scenario that
loads a skill still cannot write to your disk.

THE CODE IS ONLY IN THE SKILL FILE — not in any prompt here — so it can reach the
answer only by the agent opening `skills/bench-facts/SKILL.md`.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from common import HERE, SKILLS_ROOT, build_model, drive, report, run

CODE = "ZEBRA-77"


def scenario(model: str) -> str:
    agent = create_deep_agent(
        model=build_model(model),
        backend=FilesystemBackend(root_dir=HERE, virtual_mode=True),
        skills=[SKILLS_ROOT],
        system_prompt="You are a reporting assistant. Use the skills you are given rather than guessing.",
    )
    answer = drive(agent, "Write a bench report. Use the bench-facts skill.")
    report(answer)

    if not answer.used("read_file"):
        raise AssertionError(
            f"the skill body was never opened — the tools called were {answer.tools or 'none'}. "
            "Only the name and description are in the prompt; the agent has to read the rest."
        )
    if not answer.says(CODE):
        raise AssertionError(
            f"{CODE} never appeared: {answer.text.strip()!r}. The skill was listed but its "
            "content did not reach the answer."
        )
    return f"skill: read from disk, {CODE!r} reported"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
