"""02 todos — the planner, and the middleware that turns it on.

`write_todos` lets the agent break a multi-step request into a plan and tick
items off, with the list living in the graph state rather than anywhere on disk.

IT IS NOT ON BY DEFAULT, and that is the first thing to know. In deepagents
0.7.13 the free harness is `ls`, `read_file`, `write_file`, `edit_file`, `glob`,
`grep`, `delete`, `execute` and `task` — no planner. Todos arrive as
`TodoListMiddleware`, which this scenario adds explicitly. Older guides that call
`write_todos` a built-in are describing 0.6.x; without the middleware the model
does the sensible thing and writes its plan to a FILE instead, which looks like
success and exercises nothing (measured 2026-09-04).

WHY IT IS WORTH A SCENARIO OF ITS OWN. The todo list is the agent's working
memory across steps. If the gateway mangles tool arguments — an array arriving as
a string, say — this is the first place it shows, because `write_todos` takes a
list of objects while most tools here take flat strings.

Everything specific to a gateway is in common.py. THIS FILE IS BYTE-IDENTICAL
ACROSS EVERY PROJECT THAT HAS IT.
"""

from __future__ import annotations

import sys

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

from common import build_model, drive, report, run


def scenario(model: str) -> str:
    agent = create_deep_agent(
        model=build_model(model),
        # THE LINE THAT ADDS THE PLANNER. Without it `write_todos` does not exist.
        middleware=[TodoListMiddleware()],
        # THE TOOL IS NAMED AND THE ALTERNATIVE IS FORBIDDEN. Left to itself a 4B
        # model writes the plan to `/todo.txt` with `write_file` — which looks
        # like planning, satisfies the request, and never touches the planner
        # this scenario exists to exercise (measured 2026-09-04).
        system_prompt=(
            "You are a planning assistant. Your FIRST action must be a call to the "
            "write_todos tool, passing one item per step. Never write a plan to a file: "
            "write_file is forbidden in this conversation. After the todos are recorded, "
            "reply with the single word DONE."
        ),
    )
    answer = drive(
        agent,
        "Plan the onboarding of a new laptop in exactly three steps: order it, image it, "
        "ship it. Record those three steps with write_todos, then say DONE.",
    )
    report(answer)
    print(f"  todos   {answer.todos}")

    if not answer.used("write_todos"):
        raise AssertionError(f"the planner was never called; the tools used were {answer.tools or 'none'}")
    if len(answer.todos) < 3:
        raise AssertionError(
            f"expected at least 3 todo items, the state holds {len(answer.todos)}: {answer.todos!r}. "
            "A list argument that arrives flattened shows up exactly like this."
        )
    return f"todos: {len(answer.todos)} items planned through write_todos"


if __name__ == "__main__":
    sys.exit(run(scenario, __doc__ or ""))
