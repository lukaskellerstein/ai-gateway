---
description: "Reference: Code quality standards — SOLID, KISS, DRY, error handling, anti-patterns"
---

# Reference: Code Quality

Write code that is **simple, maintainable, and production-ready**. Prioritize
clarity over cleverness.

## Principles

1. **Simplicity First** (KISS)
2. **Consistency** in tech stack
3. **Maintainability** over cleverness
4. **DRY** — eliminate duplication
5. **YAGNI** — don't add speculative features
6. **SOLID** — Single Responsibility, Open/Closed, Liskov Substitution,
   Interface Segregation, Dependency Inversion

## Code Organization

- Keep functions small (< 20 lines ideally, < 100 lines max)
- One level of abstraction per function
- Use meaningful, pronounceable names
- Self-documenting code; comments explain "why", not "what"
- Prefer composition over inheritance

## Error Handling

- Fail fast and explicitly
- Use typed errors/exceptions with clear messages
- Never silently ignore errors
- Validate inputs at system boundaries

## Anti-Patterns to Avoid

- No commented-out code "just in case"
- No TODO comments
- No copy-paste instead of abstracting
- No premature optimization
- No over-engineering simple solutions
- No ignoring compiler/linter warnings

## Formatting and linting

This machine runs "no config, no tool": a formatter or linter acts on this repo
only if the repo carries that tool's own config file. If `:w` changes nothing and
the gutter stays empty, the marker file is missing — not the editor broken.

**This repo carries no marker files at all**, so the repo-wide check reports
every tool `gated-off` and nothing formats on save — how to read that output is
in [`machine-tools.md`](machine-tools.md). It is the configured state, not a
defect. Two facts behind it:

- **Nothing on this machine formats YAML**, marker or no marker — biome has no
  YAML parser and prettier is not installed. `compose.yml` and
  `litellm/config.*.yaml` are hand-formatted, and the editor gives them schema
  hints (`yaml-language-server`) and nothing more.
- **Markdown opts in per repo** via a `.markdownlint-cli2.yaml`; there is no
  global one. This repo has not opted in.

Do not add a marker file as a side effect of another task. The fix route, if one
is ever wanted, is `/lint-format-lsp` in mac-setup.

The contract, and the skill that applies it, are in mac-setup:
`projects/tooling.md` and `/lint-format-lsp`.
