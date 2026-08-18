"""The CLI's import time is a budget, and this test is its regression tripwire.

`worldloom --help` is `import worldloom.cli` plus argument parsing — the
console script resolves `worldloom.cli:app`, so whatever that module drags in
at import is the floor under every invocation, including the ones that print
help and exit. Measured before W6, the floor was ~0.74s of import work
(pydantic, four verticals, the render stack) for a command that touches none
of it; after, the module imports in under 0.1s because the domain surface
loads lazily through `worldloom._install`.

This test exists to catch eager-import creep, not to benchmark. One stray
module-level `from .world import World` in cli.py — or an eager re-export in
`worldloom/__init__` — puts the whole model stack back on the floor and takes
the measured time from ~0.1s to ~0.7s, which is why a generous ceiling still
catches the only regression class that matters: the difference is not noise,
it is 7x. Hence:

- the *minimum* of three runs, not the mean: CI machines stall, and a single
  slow run must not fail the build, but the fastest of three cannot beat the
  import work that is actually mandatory;
- a 0.5s ceiling, roughly double the healthy time and well under half the
  eager time, so scheduler noise passes and a real regression cannot.
"""

import subprocess
import sys
import time


def test_cli_import_stays_under_the_budget() -> None:
    # A fresh interpreter per run: the point is the *cold* import, and this
    # process has long since imported everything.
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        subprocess.run(
            [sys.executable, "-c", "import worldloom.cli"],
            check=True,
        )
        timings.append(time.perf_counter() - started)
    assert min(timings) < 0.5, (
        f"importing worldloom.cli took {min(timings):.2f}s at best (runs: "
        f"{[f'{t:.2f}' for t in timings]}) — something is imported eagerly "
        "again; the heavy stack belongs behind worldloom._install"
    )
