"""An accepted interview, assembled into what the build already consumes.

Every accepted answer lands in one place a seam already reads. The company
specification resolves (``company.resolve``) into a composed ``packs.Pack``;
the lines of business, completed by their processes' responsibilities and
seats, become the pack's ``lobs``; the processes its ``episodes``; the
document types its ``artifact_types``; the policies its ``lore``; the
organisation its ``roles.table``. That pack embeds in the corpus recipe
verbatim, so the built world replays from its own directory with no
interview on hand.

What the pack has no field for is kept beside it in the *resolution*
(``resolved``): each role's seniority level, the systems each process step
touches, each document's review chain, the timeline's incidents and org
changes, and the eval intents. The resolution is what the projection and the
case generator read, and it names, for every item, the question whose answer
produced it, which is where a case's provenance comes from.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .layers import State, all_episodes, company_resolution, lob_roles
from .model import DocumentsAnswer, OrgChange, TimelineAnswer

RESOLUTION_SCHEMA = "worldloom.world-interview-resolution/v1"


def role_rows(state: State) -> tuple[tuple[str, str, str, str | None], ...]:
    """The company's organisation: its resolved table, then every LOB role it lacks."""
    resolution = company_resolution(state)
    rows = list(resolution.role_table or ()) if resolution is not None else []
    have = {row[0] for row in rows}
    for key, role in lob_roles(state).items():
        if key not in have:
            rows.append(role.as_row())
            have.add(key)
    return tuple(rows)


def _authored_table(state: State) -> list[tuple[str, str, str, str | None]] | None:
    """The rows the pack must author, or ``None`` when the engine's own table already seats every LOB role.

    Only when a LOB declares a post the resolved organisation lacks: the pack
    then carries the whole table, because a pack's table replaces the
    engine's rather than extending it. Otherwise the pack states no table and
    the engine's stays in force, which keeps the stand-ins the engine resolves
    for itself (a unit's managing director) out of an authored table they
    would collide with.
    """
    resolution = company_resolution(state)
    held = {row[0] for row in (resolution.role_table or ())}
    if all(key in held for key in lob_roles(state)):
        return None
    return list(role_rows(state))


def lobs_of(state: State) -> list[Any]:
    """Each line of business, completed by its processes answer: responsibilities, seats, contributions."""
    from .. import lob

    engine = str(company_resolution(state).engine)
    processes = state.processes()
    completed = []
    for draft in state.lobs.lobs if state.lobs is not None else ():
        answer = processes.get(draft.name)
        completed.append(lob.Lob(
            name=draft.name, title=draft.title, purpose=draft.purpose, engine=engine, roles=list(draft.roles),
            responsibilities=list(answer.responsibilities) if answer else [],
            episode_contributions=[spec.name for spec in answer.episodes] if answer else [],
            slot_bindings=list(answer.slot_bindings) if answer else [],
        ))
    return completed


def pack_of(state: State, *, documents: DocumentsAnswer | None = None, timeline: TimelineAnswer | None = None) -> Any:
    """The company pack the accepted answers assemble into (with *documents* / *timeline* standing in for unsettled ones)."""
    from .. import packs

    resolution = company_resolution(state)
    if resolution is None or resolution.pack is None:
        raise ValueError("the company is not settled; nothing to assemble")
    base = resolution.pack
    docs = documents if documents is not None else state.documents
    history_answer = timeline if timeline is not None else state.timeline
    body = base.model_dump(mode="json", exclude_none=True)
    body.update(
        episodes=[spec.model_dump(mode="json", exclude_none=True) for spec in all_episodes(state)],
        lobs=[item.model_dump(mode="json") for item in lobs_of(state)],
        artifact_types=[doctype.model_dump(mode="json", exclude_none=True) for doctype in (docs.doctypes if docs else ())],
        lore=[*body.get("lore", []), *(policy.model_dump(mode="json", exclude_none=True)
                                        for policy in (history_answer.policies if history_answer else ()))],
    )
    table = _authored_table(state)
    if table is not None:
        body["roles"] = {"table": [{"key": key, "title": title, "function": function, "reports_to": manager}
                                   for key, title, function, manager in table]}
    return packs.load(body)


def blueprint_of(state: State, *, pack: Any = None, seed: int = 8128) -> Any:
    """A blueprint that builds the interviewed company, under the enterprise realism profile."""
    from .. import sdk

    resolution = company_resolution(state)
    blueprint = sdk.from_resolution(resolution, seed=seed)
    chosen = pack if pack is not None else pack_of(state)
    return replace(blueprint, pack_source=chosen, domain_name=chosen.base, archetype_key=None,
                   role_rows=role_rows(state)).realism("enterprise")


def world_of(state: State, *, pack: Any = None, seed: int = 8128) -> Any:
    """The interviewed company, built and not yet run: what a history is reviewed against."""
    return blueprint_of(state, pack=pack, seed=seed).build().world


def _change(change: OrgChange) -> Any:
    from ..scenarios import Departure, Hire, Reorganisation

    if change.kind == "departure":
        return Departure(period=change.period, role_key=change.role_key)
    if change.kind == "reorganisation":
        return Reorganisation(period=change.period, unit_key=change.unit_key, new_leader_role=change.new_leader_role)
    return Hire(period=change.period, role_key=change.role_key, title=change.title or change.role_key,
                function=change.function or "Operations", unit_key=change.unit_key)


def history(answer: TimelineAnswer) -> Any:
    """The history as a ``timeline.Timeline``: each period's close, then that period's org changes."""
    from .. import timeline
    from ..scenarios import MonthEndClose

    steps: list[Any] = []
    for period in timeline.periods_from(answer.start, answer.periods):
        steps.append(MonthEndClose(period=period, include_operational_incident=period in answer.incidents))
        steps.extend(_change(change) for change in answer.changes if change.period == period)
    return timeline.Timeline(tuple(steps))


def run_history(world: Any, state: State) -> Any:
    """Run the reviewed history, with every interviewed process run once per period after that period's close.

    The processes are not steps of the ``Timeline``: its review treats a
    second episode in a period as a duplicate close, which is right for a
    close and wrong for a company's own processes. They run where the build
    command's ``--episode`` rounds run them, after the period's close and
    before the org changes that land at its boundary.
    """
    from .. import timeline as timeline_module
    from ..episodes import AuthoredEpisode
    from ..scenarios import MonthEndClose

    answer = state.timeline
    if answer is None:
        raise ValueError("the timeline is not settled")
    plan = history(answer)
    timeline_module.ensure(plan, timeline_module.Roster.of(world))
    names = [spec.name for spec in all_episodes(state)]
    for step in plan:
        world = world.run(step)
        if isinstance(step, MonthEndClose):
            for name in names:
                world = world.run(AuthoredEpisode(episode=name, period=step.period))
    return world


def resolved(state: State) -> dict[str, Any]:
    """The resolution: everything the pack has no field for, each item tagged with the question that produced it."""
    from ..timeline import periods_from

    if state.evals is None or state.timeline is None or state.documents is None or state.employees is None:
        raise ValueError("the interview is not complete; resolve it after the evals question is settled")
    processes = state.processes()
    steps: dict[str, dict[str, Any]] = {}
    for lob, answer in processes.items():
        for spec in answer.episodes:
            for event in spec.events:
                key = f"{spec.name}.{event.kind}"
                steps[key] = {"lob": lob, "process": spec.name, "step": event.kind,
                              "systems": list(answer.systems.get(key, [])), "question": f"processes:{lob}"}
    documents: dict[str, dict[str, Any]] = {}
    for spec in all_episodes(state):
        for artifact in spec.artifacts:
            documents.setdefault(artifact.artifact_type, {
                "process": spec.name, "author_role": artifact.author_role,
                "trigger": artifact.triggered_by_events[0] if artifact.triggered_by_events else "",
            })
    for chain in state.documents.chains:
        if chain.artifact_type in documents:
            documents[chain.artifact_type].update(reviewer=chain.reviewer, approver=chain.approver,
                                                  published_on=list(chain.published_on), question="documents")
    owners = {spec.name: lob for lob, answer in processes.items() for spec in answer.episodes}
    lob_of_role: dict[str, str] = {}
    for draft in state.lobs.lobs if state.lobs is not None else ():
        for role in draft.roles:
            lob_of_role.setdefault(role.key, draft.name)
    for item in documents.values():
        item["lob"] = owners.get(item["process"], "")
    return {
        "schema": RESOLUTION_SCHEMA,
        "company": state.company.spec if state.company is not None else {},
        "levels": dict(sorted(state.employees.levels.items())),
        "lob_of_role": dict(sorted(lob_of_role.items())),
        "steps": dict(sorted(steps.items())),
        "documents": dict(sorted(documents.items())),
        "periods": list(periods_from(state.timeline.start, state.timeline.periods)),
        "incidents": list(state.timeline.incidents),
        "changes": [change.model_dump(mode="json") for change in state.timeline.changes],
        "policies": [policy.model_dump(mode="json", exclude_none=True) for policy in state.timeline.policies],
        "intents": [intent.model_dump(mode="json") for intent in state.evals.intents],
        "questions": [key for key, _ in state.answers],
    }


__all__ = ["RESOLUTION_SCHEMA", "blueprint_of", "history", "lobs_of", "pack_of", "resolved", "role_rows",
           "run_history", "world_of"]
