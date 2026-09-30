"""Test 5 — the thinking level a caller asks for reaches the model.

Qwen 3.8's chat template takes `reasoning_effort` and WRITES THE LEVEL INTO THE TOP
OF THE SYSTEM PROMPT: `xhigh`, its default, adds "Reasoning effort is set to xhigh.
..." and `medium` adds nothing. So the same request costs fewer prompt tokens at
`medium` — and EQUAL counts mean something between the caller and the template
dropped the field. Measured 2026-09-30, one system + user message: 62 and 24 on
LMStudio direct; 62 and 62 through LiteLLM before `allowed_openai_params` went on
the route, because `drop_params: true` deleted a field `lm_studio/` does not list.

It is not a small loss. At `xhigh` one agent step took 693 s and answered nothing;
at `medium` 231 s. `max_tokens: 1` keeps this check to a few seconds: only the
prompt is counted, nothing needs generating.

    uv run 05_reasoning_effort.py --model lms-qwen38-27b
"""

import sys

from common import Gateway, check, client_for, run

# The aliases whose template writes the level into the prompt, which is what makes
# the prompt-token count a witness. Gemma 4 ignores the field (25 tokens at every
# level, 2026-09-30), so there equal counts are correct and prove nothing. Add an
# alias here only after measuring its template direct, with no gateway in between.
LEVEL_IN_PROMPT = {"lms-qwen38-27b", "unsloth-qwen38-27b"}

MESSAGES = [
    {"role": "system", "content": "You are a careful assistant."},
    {"role": "user", "content": "Say OK."},
]

# The ceiling and the level are set here, so neither may come from `body_extras`.
OWN_FIELDS = ("max_tokens", "max_completion_tokens", "reasoning_effort")


def prompt_tokens(gateway: Gateway, model: str, level: str) -> int:
    extras = {key: value for key, value in gateway.body_extras.items() if key not in OWN_FIELDS}
    ceiling = "max_completion_tokens" if "max_completion_tokens" in gateway.body_extras else "max_tokens"
    response = client_for(gateway).chat.completions.create(
        model=model,
        messages=MESSAGES,
        reasoning_effort=level,
        **{ceiling: 1},
        **extras,
    )
    return response.usage.prompt_tokens


def scenario(gateway: Gateway, model: str) -> str:
    if model not in LEVEL_IN_PROMPT:
        return f"not applicable: {model}'s template does not write the level into the prompt"

    at_xhigh = prompt_tokens(gateway, model, "xhigh")
    at_medium = prompt_tokens(gateway, model, "medium")
    print(f"--- prompt tokens: xhigh={at_xhigh} medium={at_medium} ---")

    check(
        at_medium < at_xhigh,
        f"`reasoning_effort` never reached the template: {at_xhigh} prompt tokens at both levels. "
        "On LiteLLM, the route needs `allowed_openai_params: [\"reasoning_effort\"]` in "
        "../../config/<engine>.yaml.",
    )
    return f"the level arrives: xhigh={at_xhigh} medium={at_medium} prompt tokens"


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 5 — the thinking level reaches the model"))
