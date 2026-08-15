## What

## Why

## Gates

- [ ] `ruff check` and `mypy` exit 0
- [ ] `pytest -q` passes
- [ ] `worldloom validate retail-close` passes
- [ ] `worldloom docs --check` passes (CLI or docs changed? they move together)
- [ ] Byte-identity: default builds are unchanged, **or** this PR changes
      corpora deliberately and says so above
- [ ] No clock, `random`, UUID, or `set`-order reaching output; prompt edits
      bump their version
