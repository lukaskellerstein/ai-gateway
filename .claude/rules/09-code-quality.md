# Reference: Code quality

Write code that is simple, maintainable and production-ready. Clarity over cleverness:
KISS, DRY, YAGNI, SOLID.

- Keep functions small and to one level of abstraction.
- Meaningful names. Self-documenting code; comments explain **why**, not what.
- Fail fast with clear messages. Never silently ignore an error. Validate at boundaries.
- No commented-out code, no TODOs, no copy-paste instead of an abstraction, no premature
  optimisation.

## Formatting and linting — this repo gets none

This machine runs **"no config, no tool"**: a formatter or linter acts on a repo only if
the repo carries that tool's own config file. **This repo carries no marker files**, so
`nvim-tools` reports every tool `gated-off` and nothing formats on save. That is the
configured state, not a defect.

Two facts behind it:

- **Nothing on this machine formats YAML** — biome has no YAML parser and prettier is not
  installed. `compose.yml` and `litellm/*.yaml` are hand-formatted.
- **Markdown opts in per repo** via `.markdownlint-cli2.yaml`. This repo has not.

Do not add a marker file as a side effect of another task. The fix route, if one is ever
wanted, is `/lint-format-lsp` in mac-setup. How to read the tool output:
[`machine-tools.md`](machine-tools.md).
