"""The runnable example an industry starts from, as data rather than a branch.

``preset`` used to hold one ``if`` per engine: which simulation program and
at what size, the incident rule that opens a case, the use case's title, the
example's geography. Those are now one validated model,
``OperationalExample``, read from two places, first match wins:

1. the ``operational`` block of a visible industry pack of that name (a
   workspace upload or a harness-authored pack), whose ``example`` also names
   the company and its geography;
2. ``studio.operational`` in the policy pack, which ships the retail and
   banking examples exactly as the branches built them.

The simulation mechanisms themselves stay code (``synthesis.programs``): an
example chooses one by key and sizes it, it never describes a mechanism.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, ValidationError

from ..cascade import Finding
from ..models import Model
from ..synthesis.connectors import IncidentRule


class ExampleUseCase(Model):
    """The one use case an operational example opens with."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    count: int = Field(ge=1, le=100_000, strict=True)


class OperationalExample(Model):
    """What ``preset`` needs to build a runnable company for one industry."""

    engine: str
    """The generation engine the example company rides."""
    geo: str = ""
    """The example's locale; an industry pack's ``example.geo`` overrides it."""
    countries: tuple[str, ...] = ()
    """ISO countries of the operating structure; an industry pack's
    ``example.countries`` overrides them."""
    workflow: str
    """The operational workflow (``synthesis.operational.workflows``) its use case runs."""
    program: str
    """The simulation mechanism (``synthesis.programs.BUILDERS``) that emits its records."""
    sizing: dict[str, int]
    parameters: dict[str, int] = Field(default_factory=dict)
    incident: IncidentRule
    use_case: ExampleUseCase
    failures: tuple[str, ...]
    """The designed connector failures its scenario covers."""
    description: str = ""


def lint_operational(data: Any, *, where: str = "operational") -> list[Finding]:
    """Every reason *data* cannot build a runnable example, each naming its fix."""
    try:
        example = OperationalExample.model_validate(data)
    except ValidationError as error:
        return [f"{where}.{'.'.join(str(p) for p in item['loc']) or 'body'}: {item['msg']}" for item in error.errors()]
    from .. import domains, packkit
    from ..synthesis import SynthesisError, with_parameters
    from ..synthesis.programs import build

    findings: list[Finding] = []
    if example.engine not in domains.names():
        findings.append(f"{where}.engine: {example.engine!r} is not a registered engine; choose one of {', '.join(domains.names())}")
    workflows = packkit.policy("synthesis.operational.workflows")
    if example.workflow not in workflows:
        findings.append(f"{where}.workflow: {example.workflow!r} names no operational workflow; choose one of "
                        f"{', '.join(sorted(workflows))} or declare it under the policy `synthesis.operational.workflows`")
    try:
        program = build(example.program, example.sizing)
        if example.parameters:
            program = with_parameters(program, example.parameters)
    except SynthesisError as error:
        findings.append(f"{where}.program: {error}")
        return findings
    tables = {table.name: table for table in program.tables}
    table = tables.get(example.incident.table)
    if table is None:
        findings.append(f"{where}.incident.table: {example.program} has no table {example.incident.table!r}; "
                        f"its tables are {', '.join(sorted(tables))}")
    elif example.incident.signal not in {column.name for column in table.columns}:
        findings.append(f"{where}.incident.signal: {example.incident.table} has no column {example.incident.signal!r}; "
                        f"its columns are {', '.join(sorted(column.name for column in table.columns))}")
    return findings


def industry_pack(key: str) -> Any:
    """The industry pack a preset for *key* starts under, or ``None``.

    Only a pack someone supplied (a workspace, user or named root) shapes a
    preset. A shipped industry pack does not: the shipped presets start in the
    default language exactly as they did before industry packs existed, and
    an operator who wants the industry's words chooses its pack for the
    project, which is a reviewed revision rather than a side effect of
    clicking an example. A malformed key names no pack.
    """
    from .. import packkit

    try:
        pack = packkit.resolve(f"industry:{key}")
    except (KeyError, ValueError):
        return None
    return None if pack.origin == "builtin" else pack


def example(key: str) -> tuple[OperationalExample | None, Any]:
    """The operational example for *key* and the industry pack it came from (if any)."""
    from .. import packkit

    pack = industry_pack(key)
    if pack is not None and not pack.is_default and pack.body.operational is not None:
        return OperationalExample.model_validate(pack.body.operational), pack
    shipped = packkit.policy("studio.operational").get(key)
    return (OperationalExample.model_validate(shipped) if shipped is not None else None), pack


def company_name(pack: Any = None) -> str:
    """The example company's name: the industry pack's, else the shipped one."""
    from .. import packkit

    if pack is not None and pack.body.example is not None and pack.body.example.company_name.strip():
        return str(pack.body.example.company_name)
    return str(packkit.policy("studio.example.company_name"))


def sizing() -> dict[str, Any]:
    """A preset project's budgets, from the policy in force (an industry may resize them)."""
    from .. import packkit

    return {key: packkit.policy(f"studio.project.{key}") for key in (
        "seed", "max_batches", "pool_size", "planning_budget", "max_per_task", "max_per_case",
        "max_per_request", "minimum_tasks", "split_by", "split_weights")}


def project(chosen: OperationalExample, name: str, pack: Any = None) -> Any:
    """The runnable project *chosen* describes, for the company *name*."""
    from .. import company
    from ..process_bindings import BusinessUnit, default_company
    from ..synthesis import with_parameters
    from ..synthesis.connectors import operational_profile
    from ..synthesis.programs import build
    from .models import ProjectSpec, UseCase

    stated = pack.body.example if pack is not None and pack.body.example is not None else None
    geo = (stated.geo if stated is not None and stated.geo else chosen.geo)
    countries = (stated.countries if stated is not None and stated.countries else chosen.countries)
    document = {"engine": chosen.engine, "identity": {"company_name": name}, **({"geo": geo} if geo else {})}
    resolution = company.resolve(company.from_document(document))
    structure = default_company(chosen.engine, name=name)
    assert resolution.pack is not None
    operating = tuple(BusinessUnit(name=u.name, archetype="channel" if u.kind == "online" else "product_line")
                      for u in resolution.pack.units)
    support = tuple(b.model_copy(update={"countries": ()}) for b in structure.bus
                    if b.archetype in {"shared_service_centre", "group_function"})
    structure = structure.model_copy(update={"bus": (*operating, *support),
                                             **({"countries": tuple(countries)} if countries else {})})
    program = build(chosen.program, chosen.sizing)
    if chosen.parameters:
        program = with_parameters(program, chosen.parameters)
    profile = operational_profile(chosen.workflow)
    profile = profile.model_copy(update={"coverage": profile.coverage.model_copy(update={"failures": chosen.failures})})
    budgets = sizing()
    # Keep generated examples separate from accepted customer interview answers.
    # These limitations are still shown before the operator chooses to build.
    return ProjectSpec(company=document, structure=structure,
                       acknowledged_unmet=tuple(resolution.unmet),
                       packs=(pack.pinned,) if pack is not None and not pack.is_default else (),
                       use_cases=(UseCase(id=chosen.use_case.id, title=chosen.use_case.title,
                           objective=profile.additional_workflows[0].purpose,
                           owner=structure.bus[0].name, count=chosen.use_case.count, scenario=profile,
                           simulation=program, incident_rule=chosen.incident),),
                       **budgets)


def catalogue() -> list[dict[str, Any]]:
    """Every example a console can start from, for its onboarding page.

    The shipped operational examples, then each visible industry pack that
    names an example company or an operational block, then the connected
    retail pilot. Keys are what ``preset`` takes.
    """
    from .. import packkit

    out: dict[str, dict[str, Any]] = {}
    for key, data in sorted(packkit.policy("studio.operational").items()):
        chosen = OperationalExample.model_validate(data)
        out[key] = {"key": key, "engine": chosen.engine, "company_name": company_name(),
                    "title": chosen.use_case.title, "description": chosen.description, "origin": "builtin",
                    "operational": True}
    for located in packkit.discover("industry"):
        if located.envelope.name == "default":
            continue
        try:
            pack = packkit.resolve(located.envelope.ref())
        except (KeyError, ValueError):
            continue
        body = pack.body
        if body.example is None and body.operational is None:
            continue
        # A shipped pack does not shape a preset (`industry_pack`), so the
        # entry shows what `preset` returns: a shipped example keeps its own
        # entry, and the company is the shipped name.
        shipped = located.origin == "builtin"
        if shipped and pack.name in out:
            continue
        found, _ = example(pack.name)
        out[pack.name] = {"key": pack.name, "engine": (found.engine if found else body.engine) or "",
                          "company_name": company_name(None if shipped else pack), "industry": body.industry,
                          "title": located.envelope.title or (found.use_case.title if found else pack.name),
                          "description": (body.example.description if body.example else "") or located.envelope.description,
                          "origin": located.origin, "operational": found is not None,
                          **({} if shipped else {"pack": pack.pinned})}
    pilot = {"key": "retail-connected", "engine": "retail", "company_name": company_name(),
             "title": packkit.text("studio.console.pilot.title"),
             "description": packkit.text("studio.console.pilot.description"),
             "button": packkit.text("studio.console.pilot.button"), "origin": "builtin",
             "operational": True, "featured": True}
    return [pilot, *(out[key] for key in sorted(out))]


__all__ = ["ExampleUseCase", "OperationalExample", "catalogue", "company_name", "example", "industry_pack",
           "lint_operational", "project", "sizing"]
