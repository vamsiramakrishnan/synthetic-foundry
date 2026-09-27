"""From an accepted interview to a narrated, rendered corpus, its eval cases, and what it holds.

``realise`` is the whole back half in one call, each stage the seam that
already owns it:

1. **Build**: ``assemble.blueprint_of`` builds the interviewed company from
   its assembled pack under the enterprise realism profile.
2. **History**: ``assemble.run_history`` runs the reviewed timeline (each
   period's close, its incident when the interview scheduled one, its org
   changes) with every interviewed process run once per period, so records
   and documents evolve period by period and policies dated inside the
   history mint their own milestones.
3. **Narrate**: under fact constraints, through ``World.narrate``. Offline the
   writer is ``DeterministicProvider``; live it is a harness over the exec
   seam (``execseam.narrate_loop``), refused section by section until every
   claim checks against the facts.
4. **Render and validate**: ``World.render`` under the enterprise profile
   (revision files included), then ``World.validate``; an incoherent world is
   refused, never exported.
5. **Evals**: ``cases.build`` over the rendered world, through the same
   materialise, validate and compile path every enterprise case takes.
6. **Measure**: ``measure``, counts only.

Nothing here decides a fact: every figure is the engine's, every document the
compiler's, every case the enterprise grammar's.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .assemble import blueprint_of, pack_of, resolved, run_history
from .layers import State

DEFAULT_FORMATS: tuple[str, ...] = ("docx", "xlsx", "pptx", "markdown")


@dataclass(frozen=True)
class Realised:
    world: Any
    resolution: dict[str, Any]
    corpus: Any
    cases: tuple[Any, ...]
    planned: list[Any]
    measurements: dict[str, Any]


def realise(state: State, *, seed: int = 8128, formats: Sequence[str] = DEFAULT_FORMATS,
            narrate_command: str | None = None, model_id: str = "agent", timeout: float = 600.0) -> Realised:
    """Build, run, narrate, render and validate the interviewed world; then plan its cases and measure it.

    Inside ``registries.scoped()``: the build installs the company's document
    types, processes and LOBs, and leaving them installed would change what
    the next interview's lints accept in this process. The returned world is
    already rendered, so nothing after this needs them.
    """
    from .. import registries

    with registries.scoped():
        return _realise(state, seed=seed, formats=formats, narrate_command=narrate_command, model_id=model_id,
                        timeout=timeout)


def _realise(state: State, *, seed: int, formats: Sequence[str], narrate_command: str | None, model_id: str,
             timeout: float) -> Realised:
    from ..narrative.providers import DeterministicProvider
    from .cases import build as build_cases

    if state.evals is None:
        raise ValueError("the interview is not complete; answer every question before realising the world")
    resolution = resolved(state)
    pack = pack_of(state)
    world = blueprint_of(state, pack=pack, seed=seed).build().world
    world = run_history(world, state)
    world = world.compile()
    if narrate_command:
        from ..execseam import narrate_loop

        result = narrate_loop(world, narrate_command, model_id=model_id, timeout=timeout)
        if not result.complete or result.world is None:
            outstanding = "; ".join(f"{key}: {verdict}" for key, verdict in list(result.outstanding.items())[:3])
            raise ValueError(f"narration was not accepted: {outstanding}")
        world = result.world
    else:
        world = world.narrate(DeterministicProvider())
    world = world.render(*formats)
    report = world.validate()
    report.raise_if_failed()
    corpus, cases, planned = build_cases(world, resolution, state.evals.intents)
    return Realised(world=world, resolution=resolution, corpus=corpus, cases=cases, planned=planned,
                    measurements=measure(world, resolution, corpus, planned, state))


def case_sets(realised: Realised) -> dict[str, Any]:
    """One enterprise corpus per level: the unit a service serves (``cases.by_level``)."""
    from .cases import by_level

    return by_level(realised.corpus, realised.planned)


def prove(realised: Realised) -> dict[str, dict[str, int]]:
    """Run the reference agent over every level's case set: the executable ceiling, per level.

    A case the reference agent cannot pass is a defect in the case, found
    before any agent is evaluated on it.
    """
    from ..evalrun import ReferenceAgent, cases_from_corpus, run_cases, service_for

    out: dict[str, dict[str, int]] = {}
    for level, corpus in case_sets(realised).items():
        cases = cases_from_corpus(corpus)
        report = run_cases(service_for(cases, corpus.connector_data.records), cases, ReferenceAgent(cases))
        passed = sum(1 for result in report.results if result.graded and result.score is not None and result.score.passed)
        out[level] = {"cases": len(cases), "passed": passed}
    return out


def measure(world: Any, resolution: Mapping[str, Any], corpus: Any, planned: Sequence[Any], state: State) -> dict[str, Any]:
    """What the interviewed world holds, by the interview's own categories. Counts, never claims."""
    from .cases import dag_summary

    levels = resolution["levels"]
    roles = dict(world._roles)
    people_by_level = Counter(levels[key] for key in levels if key in roles)
    records = corpus.connector_data.records
    by_system = Counter(record.connector for record in records)
    interviewed = [record for record in records if any(key.startswith("interview_") for key in record.fields)]
    documents = [intent for intent in world.artifact_intents]
    role_of_person = {str(person): key for key, person in sorted(roles.items())}
    per_type_level: Counter[tuple[str, str]] = Counter()
    for intent in documents:
        role = role_of_person.get(intent.author_id, "")
        per_type_level[(intent.artifact_type, levels.get(role, "unlevelled"))] += 1
    from ..render.enterprise import REVISIONS_DIR

    revisions = sum(1 for item in world._rendered if item.path.startswith(REVISIONS_DIR + "/"))
    chains: Counter[str] = Counter()
    for record in records:
        history = record.fields.get("version_history")
        if record.fields.get("world_artifact_id") and isinstance(history, list) and len(history) > 1:
            chains[record.connector] += 1
    events = world.timeline()
    interviewed_steps = {str(step["step"]) for step in resolution["steps"].values()}
    lore_events = sum(1 for event in events if event.kind.startswith("milestone_"))
    periods = resolution["periods"]
    return {
        "company": world.company.name,
        "employees": {"people": len(world.people), "by_level": dict(sorted(people_by_level.items())),
                      "roles_levelled": len(levels),
                      # People the engine seats that no LOB declared (the close's
                      # finance team, the unit heads): real, but outside the ladder.
                      "unlevelled": len(world.people) - len({str(roles[key]) for key in levels if key in roles})},
        "lobs": len(state.lobs.lobs) if state.lobs else 0,
        "processes": sum(len(answer.episodes) for answer in state.processes().values()),
        "process_steps": len(resolution["steps"]),
        "systems_touched": sorted({system for step in resolution["steps"].values() for system in step["systems"]}
                                  | {system for document in resolution["documents"].values()
                                     for system in document.get("published_on", ())}),
        "records_per_system": dict(sorted(by_system.items())),
        "records_carrying_interview_fields": len(interviewed),
        "documents": {"intents": len(documents), "rendered_files": len(world._rendered),
                      "by_type_and_level": {f"{kind}@{level}": count for (kind, level), count in sorted(per_type_level.items())}},
        "revisions": {"revision_files": revisions, "records_with_revision_chains": dict(sorted(chains.items()))},
        "timeline": {"periods": len(periods), "first": periods[0], "last": periods[-1],
                     "events": len(events), "process_step_events": sum(1 for event in events if event.kind in interviewed_steps),
                     "incident_periods": len(resolution["incidents"]), "org_changes": len(resolution["changes"]),
                     "policies": len(resolution["policies"]), "policy_milestone_events": lore_events},
        "facts": len(world.facts),
        "cases": {"total": len(planned), "by_level": dag_summary(planned), "case_sets": _case_set_sizes(corpus, planned)},
    }


def _case_set_sizes(corpus: Any, planned: Sequence[Any]) -> dict[str, dict[str, Any]]:
    from .cases import by_level, tool_budget

    out: dict[str, dict[str, Any]] = {}
    for level, part in by_level(corpus, planned).items():
        systems = sorted({record.connector for record in part.connector_data.records})
        tools, admitted = tool_budget(systems)
        out[level] = {"cases": len(part.queries), "systems": systems, "records": len(part.connector_data.records),
                      "tools": tools, "tools_admitted": admitted}
    return out


def export(realised: Realised, out: str | Path) -> dict[str, Path]:
    """Write the corpus, one eval set per level with its provenance, the resolution and the measurements.

    ``<out>/corpus`` is an ordinary corpus directory (``worldloom validate``,
    ``render``, ``build --replay`` all read it). ``<out>/evals/<level>`` is an
    enterprise case set ``worldloom evalrun run`` reads, with
    ``provenance.jsonl`` beside it: per case, the intent, the level, the shape
    and the question behind every node.
    """
    from ..corpus import write_json
    from ..enterprise_io import export_corpus

    root = Path(out)
    paths = {"corpus": root / "corpus", "evals": root / "evals", "measurements": root / "measurements.json",
             "resolution": root / "interview-resolution.json"}
    realised.world.export(paths["corpus"], overwrite=True)
    write_json(paths["resolution"], realised.resolution)
    by_id = {item.query.id: item for item in realised.planned}
    for level, corpus in case_sets(realised).items():
        directory = paths["evals"] / level
        export_corpus(corpus, directory)
        with (directory / "provenance.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for query in corpus.queries:
                item = by_id[query.id]
                handle.write(json.dumps({"case": query.id, "intent": item.intent, "level": item.level,
                                         "shape": query.dimensions["dag_shape"], "nodes": item.provenance},
                                        sort_keys=True, separators=(",", ":")) + "\n")
        paths[f"evals/{level}"] = directory
    write_json(paths["measurements"], realised.measurements)
    return paths


__all__ = ["DEFAULT_FORMATS", "Realised", "case_sets", "export", "measure", "prove", "realise"]
