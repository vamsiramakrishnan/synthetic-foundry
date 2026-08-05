"""Lines of Business as authored data — a schema and a cascade.

A LOB spec is built in stages, like a probe. A harness seeds a LOB with a
minimal premise — name, purpose, engine — and then asks for roles and
responsibility edges through a handshake, refusing incoherence at each stage.
The final accepted spec — roles, responsibilities, and derived accountability
structures — rides the pack/recipe and replays byte-for-byte.

**Responsibilities are the cohesion primitive.** One declared edge — "the
controller answers for financial facts and authors memos" — derives:
- role table rows
- authorship hints the planner reads
- accountability facts minting a person and a measure

Never five hand-written tables: declare responsibility once, derive all
consequences.

**The cascade.** Stage one: seed with name, purpose, engine. Stage two: propose
roles. Stage three: propose responsibility edges (refused if they name fact
kinds nothing generates). Final: the harness derives the role table,
authorship hints, and accountability mapping from accepted responsibilities.

**Determinism.** The final accepted spec is deterministic and replays from
the ledger. Entries are ordered by key; no draw, no clock, no set iteration.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as _field, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .roles import Role, to_rows

__all__ = [
    "LobSeed", "Lob", "RoleSpec", "Responsibility", "load_seed", "open",
    "resolve", "publish", "installed", "describe", "lint_seed", "lint_roles",
    "lint_responsibilities",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class LobModel(BaseModel):
    """Base for all LOB schema objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RoleSpec(LobModel):
    """One role a LOB declares."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The role's key, lowercase snake_case. Appears in ids and lookups."""
    title: str = Field(min_length=1)
    """The role's title — what documents print."""
    function: str = Field(min_length=1)
    """The function this role sits in (Finance, Technology, etc.)."""
    reports_to: str | None = None
    """The role this one reports to, or None for the root."""

    def as_row(self) -> tuple[str, str, str, str | None]:
        """Convert to the tuple shape generators consume."""
        return (self.key, self.title, self.function, self.reports_to)


class Responsibility(LobModel):
    """One role's accountability for facts and documents."""

    role_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The role answerable for this responsibility."""
    fact_kinds: list[str] = Field(default_factory=list)
    """Fact kinds this role answers for (e.g., 'financial.revenue')."""
    artifact_types: list[str] = Field(default_factory=list)
    """Artifact types this role authors or approves."""


class LobSeed(LobModel):
    """The seed for a new LOB: minimal, just name and purpose."""

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    """The LOB's key name."""
    title: str = Field(min_length=1)
    """A short title (e.g., 'Finance')."""
    purpose: str = Field(min_length=1)
    """One sentence describing why this LOB exists."""
    engine: str = Field(min_length=1)
    """Which engine this LOB is for (retail, banking, insurance)."""


class Lob(LobModel):
    """A complete, accepted LOB specification.

    This is what rides the pack/recipe and replays. Derived from accepted
    roles and responsibilities; never authored directly.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    roles: list[RoleSpec]
    responsibilities: list[Responsibility]
    artifact_filings: list[str] = Field(default_factory=list)
    episode_contributions: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Session:
    """A LOB being authored, stored between calls.

    The graph and final spec are *derived*, never stored. This holds only
    the accepted stages: seed and the accepted answers to each stage.
    """

    name: str
    title: str
    purpose: str
    engine: str
    #: Accepted roles, keyed by role_key for lookup
    roles: Mapping[str, RoleSpec] = _field(default_factory=dict)
    #: Accepted responsibilities
    responsibilities: tuple[Responsibility, ...] = ()

    def to_lob(
        self,
        artifact_filings: list[str] | None = None,
        episode_contributions: list[str] | None = None,
    ) -> Lob:
        """Convert the session to a final Lob spec."""
        return Lob(
            name=self.name,
            title=self.title,
            purpose=self.purpose,
            engine=self.engine,
            roles=list(self.roles.values()),
            responsibilities=list(self.responsibilities),
            artifact_filings=artifact_filings or [],
            episode_contributions=episode_contributions or [],
        )

    def to_role_table(self) -> tuple[Role, ...]:
        """Derive the role table from accepted roles."""
        return tuple(Role(*spec.as_row()) for spec in self.roles.values())


@dataclass(frozen=True)
class Brief:
    """The next question in LOB authoring."""

    stage: str
    """Which stage: 'roles' or 'responsibilities'."""
    asks: str
    """The question being asked."""
    context: dict[str, Any] = _field(default_factory=dict)
    """Context needed to answer (e.g., list of existing roles)."""


class Answer(LobModel):
    """One answer to a LOB brief."""

    stage: str = Field(min_length=1)
    roles: list[RoleSpec] = Field(default_factory=list)
    """If stage is 'roles', the proposed roles."""
    responsibilities: list[Responsibility] = Field(default_factory=list)
    """If stage is 'responsibilities', the proposed edges."""


# ---------------------------------------------------------------------------
# Cascade operations
# ---------------------------------------------------------------------------


def open(seed: LobSeed | dict[str, Any]) -> Session:
    """Start authoring a new LOB from a seed.

    Args:
        seed: A ``LobSeed`` or a dict matching its shape.

    Returns:
        A ``Session`` ready for the role-proposal stage.
    """
    if isinstance(seed, dict):
        seed = LobSeed.model_validate(seed)
    return Session(
        name=seed.name,
        title=seed.title,
        purpose=seed.purpose,
        engine=seed.engine,
    )


def next_stage(session: Session) -> Brief:
    """What to ask the harness next.

    Returns:
        A ``Brief`` with the stage, question, and context needed to answer.
    """
    if not session.roles:
        return Brief(
            stage="roles",
            asks="Propose the roles this LOB needs, each with a key, title, "
            "function, and who it reports to. One role should report to nobody "
            "(the root). These will be checked for tree structure and "
            "consistency.",
            context={
                "example_role": {
                    "key": "controller",
                    "title": "Financial Controller",
                    "function": "Finance",
                    "reports_to": "cfo",
                }
            },
        )
    if not session.responsibilities:
        return Brief(
            stage="responsibilities",
            asks="For each role, propose what facts and documents it answers for. "
            "A responsibility is a role_key, a list of fact_kinds, and a list of "
            "artifact_types. These will be refused if they name fact kinds or "
            "types that nothing in the corpus declares.",
            context={"roles": {k: v.title for k, v in session.roles.items()}},
        )
    return Brief(
        stage="resolve",
        asks="All stages are complete. Call resolve() to finalize the LOB.",
        context={},
    )


def accept(
    session: Session,
    answer: Answer | dict[str, Any],
) -> Session:
    """Accept an answer to a brief.

    Args:
        session: The current ``Session``.
        answer: An ``Answer`` or dict matching its shape.

    Returns:
        A new ``Session`` with the answer incorporated.

    Raises:
        ValueError: If the answer is invalid for the current stage.
    """
    if isinstance(answer, dict):
        answer = Answer.model_validate(answer)

    if answer.stage == "roles":
        findings = lint_roles(answer.roles, engine=session.engine)
        if findings:
            raise ValueError(
                f"roles rejected: {'; '.join(findings[:3])}"
                + (f"; and {len(findings) - 3} more" if len(findings) > 3 else "")
            )
        roles = {r.key: r for r in answer.roles}
        return replace(session, roles=roles)

    if answer.stage == "responsibilities":
        findings = lint_responsibilities(
            answer.responsibilities,
            roles=[r.key for r in session.roles.values()],
        )
        if findings:
            raise ValueError(
                f"responsibilities rejected: {'; '.join(findings[:3])}"
                + (
                    f"; and {len(findings) - 3} more"
                    if len(findings) > 3
                    else ""
                )
            )
        return replace(session, responsibilities=tuple(answer.responsibilities))

    raise ValueError(f"unknown stage: {answer.stage!r}")


def resolve(
    session: Session,
    artifact_filings: list[str] | None = None,
    episode_contributions: list[str] | None = None,
) -> Lob:
    """Finalize the LOB from an accepted session.

    At this point, all stages are complete and the spec is ready to ride the
    pack/recipe. The role table and accountability mapping are derived from
    the accepted responsibilities.

    Args:
        session: The completed ``Session``.
        artifact_filings: Optional list of doctype names this LOB files.
        episode_contributions: Optional list of episodes this LOB participates in.

    Returns:
        A final ``Lob`` spec ready to be installed.
    """
    if not session.roles or not session.responsibilities:
        raise ValueError("cannot resolve: not all stages have been accepted yet")

    return session.to_lob(
        artifact_filings=artifact_filings,
        episode_contributions=episode_contributions,
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_seed(source: str | Path | dict[str, Any]) -> LobSeed:
    """Load a LOB seed from a path, JSON text, or parsed data."""
    if isinstance(source, (str, Path)) and Path(str(source)).exists():
        source = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, str):
        source = json.loads(source)
    return LobSeed.model_validate(source)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


#: All installed LOBs, by name.
_INSTALLED: dict[str, Lob] = {}


def installed() -> dict[str, Lob]:
    """The LOBs this process holds. A copy: the registry is not a surface."""
    return dict(_INSTALLED)


def describe(lob_name: str) -> Lob | None:
    """Retrieve an installed LOB, or None if not found."""
    return _INSTALLED.get(lob_name)


def install(lobs: Sequence[Lob]) -> None:
    """Register *lobs* into the process registry.

    Refuses a LOB already installed with a different spec.
    """
    fresh = [lob for lob in lobs if _INSTALLED.get(lob.name) != lob]
    if not fresh:
        return

    for spec in fresh:
        _INSTALLED[spec.name] = spec


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def lint_seed(seed: LobSeed | dict[str, Any]) -> list[str]:
    """Findings for a LOB seed before opening."""
    if isinstance(seed, dict):
        try:
            seed = LobSeed.model_validate(seed)
        except Exception as e:
            return [str(e)]

    findings: list[str] = []
    if not seed.name or not seed.name.replace("_", "").isalnum():
        findings.append("name must be lowercase alphanumerics and underscores")
    if not seed.engine or seed.engine not in {"retail", "banking", "insurance"}:
        findings.append(f"engine must be one of: retail, banking, insurance")
    return findings


def lint_roles(
    roles: Sequence[RoleSpec],
    *,
    engine: str = "",
) -> list[str]:
    """Findings for proposed roles before accepting."""
    findings: list[str] = []

    if not roles:
        findings.append("must propose at least one role")
        return findings

    by_key: dict[str, RoleSpec] = {}
    for i, role in enumerate(roles):
        if role.key in by_key:
            findings.append(f"roles[{i}]: key '{role.key}' is duplicated")
            continue

        if not role.key or not role.key.replace("_", "").isalnum():
            findings.append(
                f"roles[{i}] ({role.key}): key must be lowercase"
                " alphanumerics and underscores"
            )

        if not role.title.strip():
            findings.append(f"roles[{i}] ({role.key}): title must be non-empty")

        if not role.function.strip():
            findings.append(
                f"roles[{i}] ({role.key}): function must be non-empty"
            )

        by_key[role.key] = role

    # Check tree structure
    roots = [r.key for r in roles if r.reports_to is None]
    if len(roots) != 1:
        findings.append(
            f"must have exactly one root role (reporting to nobody);"
            f" found {len(roots)}"
        )
    elif roots[0] != "ceo":
        findings.append(
            f"by convention, the root role should be 'ceo', not '{roots[0]}'"
        )

    # Check reporting chain
    for i, role in enumerate(roles):
        if role.reports_to is not None and role.reports_to not in by_key:
            findings.append(
                f"roles[{i}] ({role.key}): reports to '{role.reports_to}'"
                " which is not in the proposed roles"
            )

        # Check for cycles
        seen = set()
        cursor = role.key
        while cursor is not None and cursor in by_key:
            if cursor in seen:
                findings.append(
                    f"roles[{i}] ({role.key}): reporting chain has a cycle"
                )
                break
            seen.add(cursor)
            cursor = by_key[cursor].reports_to

    return findings


def lint_responsibilities(
    responsibilities: Sequence[Responsibility],
    *,
    roles: Sequence[str],
) -> list[str]:
    """Findings for proposed responsibilities before accepting."""
    findings: list[str] = []

    if not responsibilities:
        findings.append("must propose at least one responsibility")
        return findings

    roles_set = set(roles)
    seen_resp: dict[str, int] = {}

    for i, resp in enumerate(responsibilities):
        key = f"{resp.role_key}/{':'.join(sorted(resp.fact_kinds))}"
        if key in seen_resp:
            findings.append(
                f"responsibilities[{i}]: duplicate of"
                f" responsibilities[{seen_resp[key]}]"
            )
        seen_resp[key] = i

        if resp.role_key not in roles_set:
            findings.append(
                f"responsibilities[{i}]: role_key '{resp.role_key}' is not"
                " in the proposed roles"
            )

        if not resp.fact_kinds and not resp.artifact_types:
            findings.append(
                f"responsibilities[{i}] ({resp.role_key}): must name at least"
                " one fact kind or artifact type"
            )

    return findings


# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------


def publish() -> dict[str, Lob]:
    """The standard library: minimal LOB seeds/expansions.

    Shipped as resolved LOBs demonstrating the cascade.
    """
    return {
        "finance": _FINANCE,
        "procurement": _PROCUREMENT,
        "hr": _HR,
    }


#: Finance LOB: controllers, analysts, CFOs
_FINANCE = Lob(
    name="finance",
    title="Finance",
    purpose="Financial management, reporting, and close-out.",
    engine="retail",
    roles=[
        RoleSpec(key="cfo", title="Chief Financial Officer", function="Finance"),
        RoleSpec(
            key="controller",
            title="Financial Controller",
            function="Finance",
            reports_to="cfo",
        ),
        RoleSpec(
            key="reporting_manager",
            title="Reporting Manager",
            function="Finance",
            reports_to="controller",
        ),
    ],
    responsibilities=[
        Responsibility(
            role_key="cfo",
            fact_kinds=["financial.revenue", "financial.cost"],
            artifact_types=["executive_summary"],
        ),
        Responsibility(
            role_key="controller",
            fact_kinds=["financial.revenue", "financial.cost"],
            artifact_types=["cfo_variance_memo"],
        ),
    ],
    artifact_filings=["cfo_variance_memo"],
    episode_contributions=["MonthEndClose"],
)


#: Procurement LOB: CPO, category managers, accounts payable
_PROCUREMENT = Lob(
    name="procurement",
    title="Procurement",
    purpose="Procurement, purchasing, and accounts payable.",
    engine="retail",
    roles=[
        RoleSpec(
            key="chief_procurement",
            title="Chief Procurement Officer",
            function="Procurement",
        ),
        RoleSpec(
            key="category_manager",
            title="Category Manager",
            function="Procurement",
            reports_to="chief_procurement",
        ),
    ],
    responsibilities=[
        Responsibility(
            role_key="chief_procurement",
            fact_kinds=["procurement.order"],
            artifact_types=["purchase_order"],
        ),
    ],
    artifact_filings=["purchase_order"],
    episode_contributions=["ProcurementCycle"],
)


#: HR LOB: heads of people, recruiters, payroll
_HR = Lob(
    name="hr",
    title="Human Resources",
    purpose="Employee management, recruitment, and payroll.",
    engine="retail",
    roles=[
        RoleSpec(
            key="head_of_people",
            title="Head of People",
            function="HR",
        ),
        RoleSpec(
            key="recruiter",
            title="Recruiter",
            function="HR",
            reports_to="head_of_people",
        ),
    ],
    responsibilities=[
        Responsibility(
            role_key="head_of_people",
            fact_kinds=["employee.headcount"],
            artifact_types=["org_announcement"],
        ),
        Responsibility(
            role_key="recruiter",
            fact_kinds=["employee.hire"],
            artifact_types=["hire_announcement"],
        ),
    ],
    artifact_filings=["org_announcement"],
    episode_contributions=["Hire"],
)
