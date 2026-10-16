# Contributor entry points. CONTRIBUTING.md ("The gates a PR must pass") is
# the source of truth for what CI blocks on; `make check` runs exactly that
# list, and the other targets are local shortcuts that never replace it.
#
#   make check-fast    lint, types, and only the tests your change can reach
#   make test-changed  the tests your change can reach, nothing else
#   make check         every gate CI runs, the whole suite
#
# A `.venv` at the repository root is used when present; otherwise whatever
# `python` and `worldloom` are on PATH. Override either, or the worker count:
#   make check PYTHON=python3.12 JOBS=2

VENV_BIN := $(if $(wildcard .venv/bin/python),.venv/bin/,)
PYTHON ?= $(VENV_BIN)python
WORLDLOOM ?= $(VENV_BIN)worldloom
JOBS ?= auto

# pytest-testmon (the `dev` extra) records which source lines each test ran
# and selects the tests a change reaches. `--testmon-forceselect` because the
# default `-m 'not slow'` in pyproject's addopts would otherwise switch its
# selection off. The first run records everything and costs a full suite
# under a tracer; later runs are the fast ones. Without testmon installed the
# fallback is last-failed-first: no deselection, but failures surface first.
HAVE_TESTMON := $(shell $(PYTHON) -c "import testmon" 2>/dev/null && echo yes)
CHANGED := $(if $(HAVE_TESTMON),--testmon --testmon-forceselect,--lf --ff)

.PHONY: check check-fast test-changed lint types

lint:
	$(PYTHON) -m ruff check

types:
	$(PYTHON) -m mypy

test-changed:
	$(PYTHON) -m pytest -q -n $(JOBS) $(CHANGED)

check-fast: lint types test-changed

check: lint types
	$(PYTHON) -m pytest -q -n $(JOBS)
	$(WORLDLOOM) validate retail-close
	$(WORLDLOOM) docs --check
