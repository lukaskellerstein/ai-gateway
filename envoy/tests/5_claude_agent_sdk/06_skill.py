"""06 skill — instructions the agent loads from disk, on its own, when they apply.

A SKILL IS A FOLDER WITH A `SKILL.md`, and its front matter is the whole
mechanism: the `description` is all the agent sees until it decides the skill is
relevant, and only then is the body read. That is what makes skills cheap — a
hundred of them cost a hundred description lines of context, not a hundred
documents.

LOADED FROM A LOCAL PLUGIN, NOT FROM `.claude/skills`. Both work. A plugin
directory is self-contained, so `setting_sources` stays empty and the CLI never
walks up the tree looking for a CLAUDE.md above this folder — the run then
behaves the same on every machine and in every checkout. `bench_plugin/` beside
this file is the whole thing: a `plugin.json` and a skill.

THE CODE IS ONLY IN THE SKILL FILE. No model can know it, and it is not in any
prompt here, so it can reach the answer only by the agent reading
`bench_plugin/skills/gateway-facts/SKILL.md` off the disk.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from common import PLUGIN_DIR, agent_options, ask, report, run

CODE = "ZEBRA-77"


async def scenario(model: str) -> str:
    answer = await ask(
        "What is the bench access code? Use the gateway-facts skill.",
        agent_options(
            model,
            plugins=[{"type": "local", "path": str(PLUGIN_DIR)}],
            # The filter, by skill name. Without it every discovered skill is
            # offered; naming one keeps this scenario about that one.
            skills=["gateway-facts"],
            # `tools` NARROWS WHAT EXISTS, `allowed_tools` AUTO-APPROVES IT. Both
            # are needed: without the first the CLI also offers Read, Bash and the
            # rest, and a small model reads the SKILL.md with Read instead of
            # loading it as a skill — which passes the value assertion while
            # proving nothing about skills.
            tools=["Skill"],
            allowed_tools=["Skill"],
            system_prompt="You are a helpful assistant. Use the skills you are given rather than guessing.",
            max_turns=8,
        ),
    )
    report("skill", answer)

    if not answer.used("Skill"):
        raise AssertionError(
            f"the skill was never loaded — the tools called were {answer.tools or 'none'}."
        )
    if not answer.says(CODE):
        raise AssertionError(
            f"{CODE} never appeared: {answer.text.strip()!r}. The skill loaded but its "
            "content did not reach the answer."
        )
    return f"skill: loaded from disk, {CODE!r} reported"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
