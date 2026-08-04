#!/usr/bin/env python3
"""Stop hook: refuse to end a refinement loop that has not finished.

The loop in `.claude/skills/worldloom-refine/SKILL.md` is a sequence of tool
calls, and the failure mode of any agent-driven sequence is stopping early —
three rewrites in, the numbers are better, and it reads as done. Nothing about
the tools prevents that: `submit_section` accepts a good rewrite whether it is
the last one or the fourth of twenty-seven.

So the harness enforces the loop rather than the prompt asking for it. While
``.worldloom/refining`` exists and names a corpus, this hook re-runs the same
measurement the loop is driven by and blocks the stop with the number still
outstanding. The agent gets that message and carries on. When nothing repeats
any more the marker is removed and the stop goes through.

That is the whole point of putting it here rather than in the skill text: a
skill can be forgotten mid-session, and a hook cannot.

Exit codes are the Claude Code hook contract: 0 allows the stop, 2 blocks it
and feeds stderr back to the agent. Anything unexpected exits 0 — a broken
guard must not be able to trap a session in a loop it cannot leave, which is a
worse failure than stopping early.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = Path(".worldloom/refining")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}

    # `stop_hook_active` means this stop was already blocked once and the agent
    # is trying again after doing more work. Still enforced — that is the point
    # — but never on a marker that has gone stale, which the checks below rule
    # out anyway.
    if not MARKER.exists():
        return 0

    corpus = MARKER.read_text(encoding="utf-8").strip()
    if not corpus or not Path(corpus).exists():
        MARKER.unlink(missing_ok=True)
        return 0

    try:
        from worldloom import refine
        from worldloom.world import World

        measurement = refine.measure(World.load(corpus))
        outstanding = refine.targets(measurement, budget=1_000_000)
    except Exception as exc:  # noqa: BLE001
        # A guard that cannot measure has no business blocking. Say why on
        # stderr and let the session end.
        print(f"worldloom refine guard could not measure {corpus}: {exc}", file=sys.stderr)
        return 0

    if not outstanding:
        MARKER.unlink(missing_ok=True)
        print(
            f"worldloom: {corpus} has no near-duplicate passages left "
            f"({measurement.passages} passages, {measurement.distinct_shapes} distinct "
            f"shapes). Refinement complete.",
            file=sys.stderr,
        )
        return 0

    worst = outstanding[0]
    print(
        f"The refinement loop on {corpus} is not finished: "
        f"{measurement.repeated_passages} of {measurement.passages} passages are still "
        f"near-duplicates of each other, across {len(measurement.clusters)} group(s), "
        f"and {len(outstanding)} section(s) are still worth rewriting.\n"
        f"The worst is {worst.id}, currently {worst.similarity:.2f} similar to the "
        f"passage in {worst.exemplar_of} (it needs to be at or below {worst.ceiling:.2f}).\n"
        f"Call next_target and keep going. If you are deliberately stopping early, "
        f"delete {MARKER} first — that is the explicit way out, and it leaves a trace "
        f"that the loop was abandoned rather than completed.",
        file=sys.stderr,
    )
    _ = payload  # the hook contract supplies session metadata; none of it is needed here
    return 2


if __name__ == "__main__":
    sys.exit(main())
