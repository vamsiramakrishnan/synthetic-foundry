"""Who exists in a world, and how much of that a model may decide.

The role table is the organisation. ``("controller", "Group Financial
Controller", "Finance", "cfo")`` says a person exists, what they are called,
what they do, and who they report to; fourteen of those rows plus three per
business unit are the whole retail company. They are a literal tuple in
``generators/organisation.py``, which means every retail world this tool has
built has had the same fifteen job titles in the same reporting shape, with
only the names and the unit count varying.

Opening that up runs into something the numeric registry did not have to face.
**Generator code looks roles up by name.** ``scenarios`` asks for
``roles["controller"]`` to sign a close, ``regulatory`` asks for
``roles["prudential_risk_head"]`` to challenge a return, the actor policy
activates ``platform_senior`` when an incident opens. A model handed a blank
sheet writes a plausible organisation with none of those keys in it, and the
build does not produce a different company — it raises ``KeyError`` halfway
through an episode.

So the same shape as everywhere else here: **a closed vocabulary where code
reads, and freedom above it.** ``SPINE`` is the set of keys the engine consults
by name — through ``roles[...]``, through the ``role_ids[...]`` map the org
generators build, or through any other literal lookup. A proposed table must contain every one of them; it may rename their
*titles*, move them in the tree, change what function they sit in, and add as
many roles as it likes around them. Thirteen keys are load-bearing in retail out of
a table of sixteen, sixteen of eighteen in banking, and — tellingly — seven of
seven in insurance. That last one is a finding, not a coincidence: the insurer
ships the thinnest role table of the three and consults all of it, so it is the
one engine whose organisation cannot be authored at all until its table grows.

**The spine is computed, not maintained.** ``tests/test_roles.py`` scans this
package for literal ``roles["..."]`` lookups, intersects them with each
engine's own table, and asserts the result is exactly what is declared below. A
new lookup added anywhere starts being enforced without anyone remembering to
update a list, and a lookup removed stops constraining authors. A hand-kept
list would be wrong within a month and would be wrong *silently*, which is the
failure mode this project spends most of its invariants avoiding.

**Shape, not rows.** A probe's organisation and reporting layers do not produce
seventeen rows — they produce headcount, span of control, depth, and a set of
functions. ``from_shape`` is the bridge: given those, the tree is determined up
to how the remainder is distributed, and that is a choice with a defensible
answer rather than a matter of taste. See its docstring.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

#: The suffixes of the roles minted per business unit. Spelled *with* the
#: leading underscore, deliberately: ``domains.Domain.unit_role_suffixes``
#: publishes exactly these strings (``("_md",)`` for banking and insurance,
#: all three for retail), so a second spelling without the underscore would
#: put the separator in two vocabularies and every bridge between them would
#: be an ``lstrip`` — the string surgery this module exists to retire.
UNIT_ROLE_SUFFIXES: tuple[str, ...] = ("_md", "_bp", "_buyer")


def unit_role_key(unit_key: str, suffix: str) -> str:
    """The role key minted for *unit_key*'s post with *suffix* (``"gm"``,
    ``"_md"`` → ``"gm_md"``).

    This function and ``parse_unit_role`` are the whole of the per-unit key
    format. Before they existed the format lived in ~10 call sites as
    f-strings and ``role[:-3]`` / ``role[:-6]`` slices, which meant renaming a
    suffix silently detached everybody in a unit from their business unit —
    the parse sites kept slicing three characters off keys the mint sites no
    longer produced. Minting and parsing now share one definition, so the two
    cannot disagree.
    """
    return unit_key + suffix


def parse_unit_role(
    key: str, suffixes: Sequence[str] = UNIT_ROLE_SUFFIXES
) -> tuple[str, str] | None:
    """The inverse of ``unit_role_key``: ``(unit_key, suffix)``, or ``None``
    for a key that is not a per-unit role.

    *suffixes* defaults to the retail triple; engines that mint fewer pass
    their own (``domains.Domain.unit_role_suffixes`` plugs in directly) so a
    banking role that happens to end in ``_bp`` is not mistaken for a unit
    post the banking generator never minted. First match wins, in the order
    given — the same order the ``endswith`` chains this replaces checked in.
    A bare suffix with no unit key in front of it is not a unit role.
    """
    for suffix in suffixes:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)], suffix
    return None


#: Per-unit role key templates, one per suffix, minted for every business unit
#: the archetype declares. Derived through ``unit_role_key`` rather than typed,
#: so the template and the accessor cannot drift. These keys are load-bearing
#: the same way a spine key is: generator code parses the suffix back off (via
#: ``parse_unit_role``) to decide which unit a person belongs to.
UNIT_ROLES: tuple[str, ...] = tuple(
    unit_role_key("{unit}", suffix) for suffix in UNIT_ROLE_SUFFIXES
)


@dataclass(frozen=True)
class UnitRole:
    """One per-unit row an organisation generator mints for every business
    unit — the authorable form of the literals that used to sit inline in
    ``generators/organisation.py``.

    ``title`` is a template; ``{unit}`` is replaced with the unit's display
    name (by ``str.replace``, not ``str.format``, so a unit name containing a
    brace can never raise from inside a build). The manager is either a fixed
    role key (``manager="ceo"``) or a sibling post in the same unit
    (``manager_suffix="_md"`` — retail's buyer reports to their own unit's
    MD); exactly one of the two should be set, and ``manager_suffix`` wins
    because a same-unit reference is the narrower claim.
    """

    suffix: str
    title: str
    function: str
    manager: str | None = None
    manager_suffix: str | None = None

    def row(self, unit_key: str, unit_name: str) -> tuple[str, str, str, str | None]:
        """The role-table row this spec mints for one unit."""
        manager = (
            unit_role_key(unit_key, self.manager_suffix)
            if self.manager_suffix is not None
            else self.manager
        )
        return (
            unit_role_key(unit_key, self.suffix),
            self.title.replace("{unit}", unit_name),
            self.function,
            manager,
        )

#: The role keys each engine's own code looks up by name. Verified against a
#: scan of this package — see the module docstring. Ordered as frozensets
#: because membership is the only question ever asked of them.
SPINE: Mapping[str, frozenset[str]] = {
    "retail": frozenset({
        "audit", "ceo", "cfo", "cio", "controller", "merch_analyst", "merch_lead",
        "platform_engineer", "platform_lead", "platform_senior", "reporting_manager",
        "svc_desk", "svc_incident",
    }),
    "banking": frozenset({
        "audit", "audit_manager", "ceo", "cfo", "cio", "controller", "credit_risk_lead",
        "cro", "liquidity_analyst", "platform_lead", "platform_senior",
        "prudential_risk_head", "reg_analyst", "reg_reporting_manager", "svc_desk",
        "svc_incident",
    }),
    "insurance": frozenset({
        "audit", "ceo", "cfo", "chief_actuary", "claims_director",
        "financial_controller", "reserving_actuary",
    }),
}

#: The one key that must be the tree's root. Not merely load-bearing —
#: `scenarios.chief_executive` resolves it directly, and the org tree is
#: validated as having a single root, so a table whose ceo reports to somebody
#: is two errors at once.
ROOT = "ceo"


@dataclass(frozen=True)
class Role:
    """One row of the organisation."""

    key: str
    title: str
    function: str
    manager: str | None

    def as_row(self) -> tuple[str, str, str, str | None]:
        """The tuple shape the generators already consume.

        The generators take tuples, not this dataclass, and converting here
        rather than changing them is deliberate: threading a new type through
        `sorted_roles` and three org generators would touch far more code than
        the freedom is worth, and every one of those touches is a chance to
        move a byte in a build that must not move.
        """
        return (self.key, self.title, self.function, self.manager)


@dataclass(frozen=True)
class Rejection:
    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.rule} — {self.detail}"


def required(engine: str, unit_keys: Sequence[str] = ()) -> tuple[str, ...]:
    """Every key a table for *engine* must contain, spine and per-unit alike."""
    try:
        spine = SPINE[engine]
    except KeyError:
        raise KeyError(
            f"unknown engine {engine!r}; known: {sorted(SPINE)}. A new engine"
            " needs its own spine entry, and `tests/test_roles.py` will tell"
            " you what belongs in it."
        ) from None
    return tuple(sorted(spine)) + tuple(
        unit_role_key(unit, suffix)
        for unit in unit_keys
        for suffix in UNIT_ROLE_SUFFIXES
    )


def review(
    table: Sequence[Role],
    *,
    engine: str,
    unit_keys: Sequence[str] = (),
) -> list[Rejection]:
    """Every reason this organisation cannot be built. All of them, not the first.

    The checks are the ones the generator would otherwise discover by crashing,
    stated up front so an author can predict a rejection instead of debugging
    a ``KeyError`` from inside an episode.
    """
    found: list[Rejection] = []

    def refuse(subject: str, rule: str, detail: str) -> None:
        found.append(Rejection(subject, rule, detail))

    by_key: dict[str, Role] = {}
    for role in table:
        if role.key in by_key:
            refuse(role.key, "duplicate_role", "declared twice")
            continue
        by_key[role.key] = role
        if not role.key or not role.key.replace("_", "").isalnum():
            refuse(role.key, "bad_key",
                   "role keys are lowercase alphanumerics and underscores; they"
                   " appear in ids and in generator lookups")
        if not role.title.strip():
            refuse(role.key, "untitled", "every role needs a title — it is what documents print")
        if not role.function.strip():
            refuse(role.key, "no_function",
                   "every role needs a function; cost centre and persona are"
                   " decided from it")

    for key in required(engine, unit_keys):
        if key not in by_key:
            refuse(key, "missing_from_spine",
                   f"the {engine} engine looks this role up by name. You may"
                   " retitle it, move it, and change its function — you may not"
                   " remove it, because generator code would raise KeyError"
                   " part-way through an episode rather than build a different"
                   " company.")

    roots = [role.key for role in by_key.values() if role.manager is None]
    if len(roots) != 1:
        refuse(", ".join(sorted(roots)) or "(none)", "not_a_tree",
               f"an organisation has exactly one root; found {len(roots)}")
    elif roots[0] != ROOT:
        refuse(roots[0], "wrong_root",
               f"the root must be {ROOT!r} — `scenarios.chief_executive` resolves it directly")

    for role in by_key.values():
        if role.manager is not None and role.manager not in by_key:
            refuse(role.key, "unknown_manager",
                   f"reports to {role.manager!r}, which is not in the table")

    # Cycles, walked per node with a seen-set rather than by a topological sort:
    # a sort that fails tells you a cycle exists, and this tells you which
    # people are in it, which is the only version an author can act on.
    for role in sorted(by_key.values(), key=lambda r: r.key):
        seen, cursor = [role.key], role.manager
        while cursor is not None and cursor in by_key:
            if cursor in seen:
                refuse(role.key, "reports_in_a_circle",
                       " → ".join([*seen, cursor]))
                break
            seen.append(cursor)
            cursor = by_key[cursor].manager

    return found


# ---------------------------------------------------------------------------
# Shape to table
# ---------------------------------------------------------------------------

#: Seniority words by distance from the root, and the last one repeats. Titles
#: a synthesiser invents are placeholders — a model authoring an organisation
#: should replace them with what the business actually calls these people, and
#: `review` deliberately does not enforce any naming convention because
#: "Regional Operations Manager" and "Area Lead" are both real and the
#: difference between them is exactly the texture a corpus is for.
_LADDER: tuple[str, ...] = ("Chief", "Director of", "Head of", "Manager,", "Lead,", "")


def from_shape(
    *,
    functions: Sequence[str],
    headcount: int,
    span: int,
    levels: int,
    engine: str = "retail",
    unit_keys: Sequence[str] = (),
) -> tuple[Role, ...]:
    """A reporting tree of *headcount* people, *levels* deep, *span* wide.

    This is what a probe's organisation and reporting layers actually produce.
    Nobody derives seventeen rows from a premise; they derive "nine hundred
    people, spans of eight, five levels", and those three numbers over-determine
    the tree — which is the point, because it means the shape can be *checked*
    against what was claimed rather than taken on trust.

    Filled breadth-first, and the remainder goes to the lowest-index manager
    first. That tie-break is not cosmetic: the alternative — spreading the
    remainder evenly, or randomly — makes the tree depend on iteration order or
    on a seed, and this runs inside a build whose output must be byte-identical
    on replay.

    The spine is placed first and kept: every key the engine consults appears
    at the shallowest level that can hold it, so a synthesised organisation is
    buildable rather than merely plausible. That is the compromise the module
    docstring describes, made concrete — a model gets to choose the shape, and
    does not get to choose it into something the engine cannot run.

    Titles are placeholders from a seniority ladder. Replacing them is the
    interesting half of authoring an organisation and is left to whoever is
    authoring it.
    """
    if span < 1:
        raise ValueError(f"span must be at least 1, got {span}")
    if levels < 1:
        raise ValueError(f"levels must be at least 1, got {levels}")
    if not functions:
        raise ValueError("an organisation needs at least one function")

    reachable = sum(span ** level for level in range(levels + 1))
    if headcount > reachable:
        raise ValueError(
            f"{headcount} people do not fit in {levels} level(s) at a span of"
            f" {span}: that shape holds at most {reachable}. Widen the span,"
            " add a level, or reduce headcount — the three are not independent,"
            " which is what a probe's cross-layer link is for."
        )

    ordered_functions = tuple(functions)
    spine_keys = [key for key in required(engine, unit_keys) if key != ROOT]

    # Which function a spine key sits in is *read by the engine*, so it is
    # closed for exactly the reason the key itself is. `organisation.generate`
    # builds an access policy "Finance and audit only" out of
    # `allow_functions=["Finance", "Audit"]`, and `world._policy_for("finance")`
    # hands it to the workbook and the variance memo — so a `controller` placed
    # in Merchandising is an author who cannot read what they wrote.
    # Round-robin by position did exactly that: it put `audit` in Finance,
    # `cfo` in Technology and `controller` in Merchandising, and every mosaic
    # world of every engine failed `author_cannot_see_own_artifact` (retail 2-6,
    # banking 9, insurance 2-4). Invisible until a mosaic was narrated, because
    # the check reads compiled artifacts and a plan-only corpus has none.
    #
    # The caller's `functions` still decides where every *synthesised* role
    # goes, which is the freedom this function exists to offer. It does not
    # decide where the spine goes, any more than it decides which keys the
    # spine contains.
    engine_functions = {role.key: role.function for role in _shipped(engine)}

    # How many people sit at each level, root downwards.
    #
    # Filled greedily — each level takes as many as its parents' span allows —
    # while *reserving one person for every level still to come*. That reserve
    # is the whole of the fix for a defect measurement caught: without it the
    # fill runs out of people part-way down and returns a tree shallower than
    # was asked for, reporting success. Since `measure` exists precisely so a
    # handshake can refuse a shape that does not match its claim, a synthesiser
    # that quietly produced one was the worst possible caller of it.
    sizes = [1]
    remaining = headcount - 1
    for level in range(1, levels + 1):
        still_to_come = levels - level
        take = min(sizes[-1] * span, remaining - still_to_come)
        if take < 1:
            raise ValueError(
                f"{headcount} people cannot fill {levels} level(s): a tree that"
                f" deep needs at least {levels + 1} people, one per level."
            )
        sizes.append(take)
        remaining -= take
    if remaining:
        raise ValueError(
            f"{headcount} people do not fit in {levels} level(s) at a span of"
            f" {span}: that shape holds at most {headcount - remaining}. Widen"
            " the span, add a level, or reduce headcount — the three are not"
            " independent, which is what a probe's cross-layer link is for."
        )

    # The root is part of the load-bearing spine too. Leaving it on the first
    # caller-supplied function made a mosaic's CEO a Merchandising employee who
    # authored the strategy pack; access happened to permit it, but the artifact
    # contract correctly refused the departmental contradiction.
    roles: list[Role] = [Role(
        ROOT, "Chief Executive Officer",
        engine_functions.get(ROOT, ordered_functions[0]), None,
    )]
    pending = list(spine_keys)
    made = 0
    parents = [ROOT]
    for depth, size in enumerate(sizes[1:], start=1):
        level: list[str] = []
        for index in range(size):
            if pending:
                key = pending.pop(0)
            else:
                made += 1
                key = f"role_{made:03d}"
            # Parents cycle lowest-index-first, so the remainder lands on the
            # earliest managers. Not cosmetic: the alternative spreads it by
            # iteration order or by a seed, and this runs inside a build whose
            # output must be byte-identical on replay.
            manager = parents[index % len(parents)]
            # `.get`, not `[]`: a per-unit key (`{unit}_md`) is required for
            # whatever units this world declares and is in no shipped table, so
            # it takes the caller's rotation like any synthesised role. Falling
            # back rather than raising because a unit role has no function the
            # engine reads it by — `assign` finds it by parsing the suffix off
            # the key, which is why renaming a unit key breaks and re-filing it
            # does not.
            function = engine_functions.get(
                key, ordered_functions[len(roles) % len(ordered_functions)]
            )
            roles.append(Role(key, _title(key, function, depth), function, manager))
            level.append(key)
        parents = level

    if pending:
        # Everything the engine consults must exist, even if the shape asked
        # for fewer people than the spine needs. Reported by raising rather
        # than by quietly exceeding the headcount: a caller who asked for forty
        # people and got fifty-three has had their claim overruled, and should
        # find that out here rather than from a headcount fact later.
        raise ValueError(
            f"a {engine} organisation needs at least {len(spine_keys) + 1} roles for"
            f" the engine's own lookups; a headcount of {headcount} leaves"
            f" {len(pending)} unplaced ({', '.join(pending[:5])}"
            f"{'…' if len(pending) > 5 else ''})"
        )
    return tuple(roles)


def _title(key: str, function: str, depth: int) -> str:
    word = _LADDER[min(depth, len(_LADDER) - 1)]
    readable = key.replace("_", " ").title()
    return f"{word} {function}".strip() if word else readable


def measure(table: Sequence[Role]) -> dict[str, int]:
    """What a table actually is: headcount, depth, and the widest span in it.

    The other half of ``from_shape``. A handshake that accepted a claimed shape
    on trust would be a handshake in name only — this is what lets ``review``
    say "you asked for spans of eight and wrote a table whose widest is three".
    """
    by_key = {role.key: role for role in table}
    reports: dict[str, int] = {}
    for role in table:
        if role.manager is not None:
            reports[role.manager] = reports.get(role.manager, 0) + 1

    def depth_of(key: str) -> int:
        seen, depth, cursor = {key}, 0, by_key[key].manager
        while cursor is not None and cursor in by_key and cursor not in seen:
            seen.add(cursor)
            depth += 1
            cursor = by_key[cursor].manager
        return depth

    return {
        "headcount": len(table),
        "levels": max((depth_of(role.key) for role in table), default=0),
        "widest_span": max(reports.values(), default=0),
        "managers": len(reports),
        "functions": len({role.function for role in table}),
    }


# ---------------------------------------------------------------------------
# The handshake
# ---------------------------------------------------------------------------

#: The grammar, in sentences, because a model told the rules can obey them and
#: a model told "invalid" can only guess. Carried on every request.
RULES: tuple[str, ...] = (
    "Every role in `must_contain` has to appear. You may retitle it, move it"
    " under a different manager, and change its function — you may not remove"
    " it. Generator code looks those keys up by name and would raise KeyError"
    " part-way through an episode rather than build a different company.",
    "Add as many roles as you like around them. Most of an organisation is"
    " yours: in retail, eleven of fifteen roles are load-bearing and everything"
    " else is free.",
    "Exactly one role reports to nobody, and it is the chief executive.",
    "Every other role reports to a role that exists, and nobody reports to"
    " themselves through any number of hops.",
    "Titles are the interesting half. 'Regional Operations Manager' and 'Area"
    " Lead' are both real organisations and the difference between them is the"
    " texture a corpus exists to carry, so no naming convention is enforced —"
    " but a role with no title is refused, because a title is what documents"
    " print.",
    "If you state a shape — headcount, span of control, reporting depth — the"
    " table you submit is measured against it and refused if it disagrees."
    " Those three numbers are not independent, so state them only if you mean"
    " them.",
)


@dataclass(frozen=True)
class Shape:
    """A claimed organisation shape. Every field optional; stated ones are checked."""

    headcount: int | None = None
    levels: int | None = None
    widest_span: int | None = None

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in
                (("headcount", self.headcount), ("levels", self.levels),
                 ("widest_span", self.widest_span)) if v is not None}


def request(engine: str, unit_keys: Sequence[str] = ()) -> dict[str, object]:
    """What an author needs to propose an organisation, and nothing else.

    Self-contained on purpose, the same as every other request in this project:
    an author should not have to read this repository to answer, and a rule
    they cannot see is a rejection they could not have predicted.
    """
    return {
        "engine": engine,
        "must_contain": list(required(engine, unit_keys)),
        "free_to_invent": True,
        "shipped_shape": measure(_shipped(engine)),
        "rules": list(RULES),
    }


def _shipped(engine: str) -> tuple[Role, ...]:
    """The engine's own table, as a reference point for an author."""
    from importlib import import_module

    module = import_module({
        "retail": "worldloom.generators.organisation",
        "banking": "worldloom.generators.banking_org",
        "insurance": "worldloom.generators.insurance_org",
    }[engine])
    return from_rows(module._ROLES)


def check(
    table: Sequence[Role],
    *,
    engine: str,
    unit_keys: Sequence[str] = (),
    shape: Shape | None = None,
) -> list[Rejection]:
    """``review``, plus the claimed shape measured against the table submitted.

    Split from ``review`` rather than folded into it because they answer
    different questions: ``review`` asks whether this organisation can be
    *built*, and is what the generator needs; this asks whether it is the
    organisation its author said it was, which only a handshake cares about.
    A generator that enforced a claim nobody made would be refusing tables for
    failing to match a shape of ``None``.
    """
    found = review(table, engine=engine, unit_keys=unit_keys)
    if shape is None:
        return found

    actual = measure(table)
    for field, claimed in shape.as_dict().items():
        if actual[field] != claimed:
            found.append(Rejection(
                field, "shape_disagrees",
                f"you stated {field} {claimed} and submitted a table whose"
                f" {field} is {actual[field]}. Headcount, span and depth are"
                " three numbers with two degrees of freedom — changing one"
                " moves another, so this is usually a sign the shape was"
                " chosen before the table rather than with it.",
            ))
    return found


def from_rows(rows: Iterable[tuple[str, str, str, str | None]]) -> tuple[Role, ...]:
    """The generators' tuple shape, as ``Role`` objects."""
    return tuple(Role(*row) for row in rows)


def to_rows(table: Sequence[Role]) -> tuple[tuple[str, str, str, str | None], ...]:
    return tuple(role.as_row() for role in table)


__all__ = [
    "ROOT", "RULES", "Rejection", "Role", "SPINE", "Shape", "UNIT_ROLES",
    "UNIT_ROLE_SUFFIXES", "UnitRole", "check", "from_rows", "from_shape",
    "measure", "parse_unit_role", "request", "required", "review", "to_rows",
    "unit_role_key",
]
