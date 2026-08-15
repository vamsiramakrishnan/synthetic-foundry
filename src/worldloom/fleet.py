"""Admission control for a fleet of worlds: qualified for a purpose, or not shipped.

The measured problem: a fleet of worlds is generated (``mosaic``, ``sdk``, or a
directory of builds), measured six different ways — ``validate``, replay,
``spaces.holes``, ``outcomes.read``, ``vendi``, ``evaluate.across`` — and then
*all of it ships*. Nothing composes the measurements into "this fleet is
qualified for its purpose", and nothing turns "keep these, here are the holes"
into an artifact. Every reading exists; the verdict does not. This module is
the verdict and only the verdict: it composes the instruments this repository
already owns and adds no measurement of its own.

**A curator is downstream of generation. Nothing here may feed back into a
build.** That is the design decision, not an implementation accident: a
qualification that steered the next build would make the fleet converge on
whatever the qualifier rewards — the Goodhart failure ``outcomes`` draws its
line against, one level up. What a curation hands the next generation is its
*holes*: the niches nobody filled, which is a work list, not an objective. A
build that consumed a fitness from this module would also inherit its floats,
and one of them (`vendi`) is an eigendecomposition whose last bits vary by
BLAS — which is why effective diversity is **reported and never gates**
anything here, the same rule ``AGENTS.md`` states for ``--effective``.

**Why there is no "naturalistic" purpose.** Qualifying a fleet as resembling
real enterprise populations requires reference data — observed distributions
of organisation sizes, document-type mixes, filing cadences from actual
companies — and this repository has none. Every floor in this module is a
measurement that exists today; a "naturalistic" verdict would be a floor with
an invented denominator, converting this project's honest "we don't claim
realism" into a fake claim wearing a measurement's clothes. So the purpose is
refused, naming the data that would be needed, rather than offered and faked.

**What "qualified" means, per purpose.** A purpose is a use the fleet is being
admitted for, and each floor is checkable from the corpus alone:

* ``challenge`` — the fleet will be used to challenge a retrieval or assistant
  system. Every world must cohere (``validate``), every world must rebuild
  from its own recipe and ledger into the same fact ledger and artifact plan
  (replay), every world must mint at least one evaluation case (a challenge
  that asks nothing challenges nothing), and no two worlds may be the same
  world (identical fact digests — N copies of one world is one challenge
  reported N times).
* ``counterfactual`` — the fleet will be used for controlled comparison:
  factual against counterfactual. Coherence and replay as above, at least two
  worlds (a counterfactual needs a factual to counter), a shared archetype
  (varying the company *and* the input confounds the comparison — attribution
  is the whole point of a counterfactual), and no two worlds identical (a twin
  that varies nothing answers nothing).

Deterministic throughout: no clock, no ``random``, no UUID, no ``set``
iteration reaching output — members are visited in sorted directory order,
every mapping in a manifest is emitted under ``sort_keys``, and the one float
whose bits are machine-dependent (`vendi`) is rounded and labelled non-gating.
The coverage denominator is ``spaces.build_space()``, which is read from the
registries *at call time* on purpose (its own docstring's argument: a cached
axis list silently stops covering a newly registered value); a caller who has
installed packs and wants a clean reading wraps the call in
``registries.scoped()``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import archive

#: The uses a fleet can be admitted for. "naturalistic" is deliberately not a
#: member — see the module docstring — and `_checked_purpose` refuses it with
#: the reason rather than with a generic unknown-value error.
FleetPurpose = Literal["challenge", "counterfactual"]

PURPOSES: tuple[str, ...] = ("challenge", "counterfactual")

#: What `curate` writes at the fleet root. One name, so a fleet can carry at
#: most one curation and a re-curation replaces rather than accumulates.
MANIFEST_NAME = "fleet-manifest.json"


class FleetError(Exception):
    """Raised when a fleet cannot be read, or a purpose cannot be measured."""


_NATURALISTIC_REFUSAL = (
    "a 'naturalistic' purpose cannot be qualified: judging whether a fleet"
    " resembles real enterprise populations requires reference data this"
    " repository does not have — observed distributions of organisation sizes,"
    " document-type mixes, and filing cadences from actual companies, to serve"
    " as the denominator of every floor. Every figure this module reports is a"
    " measurement that exists today; offering the purpose without the data"
    " would convert 'we don't claim realism' into a fake claim. Qualify for"
    f" {' or '.join(repr(p) for p in PURPOSES)} instead."
)


def _checked_purpose(purpose: str) -> str:
    """*purpose* if this module can measure it, else a stated refusal.

    "naturalistic" gets its own message because it is the one plausible-looking
    value whose absence is a decision rather than an omission, and a generic
    "unknown purpose" would invite filing it as a feature request when the
    missing thing is reference data, not code.
    """
    if purpose == "naturalistic":
        raise FleetError(_NATURALISTIC_REFUSAL)
    if purpose not in PURPOSES:
        raise FleetError(
            f"unknown fleet purpose {purpose!r}; a fleet can be qualified for"
            f" {', '.join(PURPOSES)}"
        )
    return purpose


# ---------------------------------------------------------------------------
# Reading the fleet off disk
# ---------------------------------------------------------------------------


def _members(fleet_dir: str | Path) -> tuple[Path, ...]:
    """Every member corpus of the fleet, in sorted name order.

    A member is any subdirectory carrying a world header — the shape ``mosaic``
    writes (``world-NN/``) and the shape a hand-assembled directory of builds
    has. Two refusals are deliberate:

    * A ``world-*`` directory *without* a header is refused rather than
      skipped. Skipping it would silently shrink the fleet, and a fleet that
      qualifies because its broken member stopped counting is the exact
      failure an admission controller exists to prevent.
    * A ``mosaic.json`` plan whose count disagrees with the members present is
      refused too. A sharded or interrupted mosaic is an *incomplete* fleet,
      and qualifying the worlds that happen to exist would report a verdict
      about a fleet nobody asked about.
    """
    from . import corpus

    root = Path(fleet_dir)
    if not root.is_dir():
        raise FleetError(f"{root} is not a directory, so it is not a fleet")
    if (root / corpus.WORLD_FILE).exists():
        raise FleetError(
            f"{root} is a single corpus, not a fleet of them; point at the"
            " directory that contains the corpora"
        )

    members: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / corpus.WORLD_FILE).exists():
            members.append(child)
        elif child.name.startswith("world-"):
            raise FleetError(
                f"{child.name} looks like a fleet member and carries no"
                f" {corpus.WORLD_FILE}; a member that cannot be read must fail"
                " the fleet, not fall out of it"
            )
    if not members:
        raise FleetError(f"no member corpus found under {root}")

    plan = root / "mosaic.json"
    if plan.exists():
        try:
            expected = json.loads(plan.read_text(encoding="utf-8")).get("count")
        except (OSError, json.JSONDecodeError) as exc:
            raise FleetError(f"{plan.name} does not parse: {exc}") from exc
        if isinstance(expected, int) and expected != len(members):
            raise FleetError(
                f"the plan in {plan.name} names {expected} world(s) and"
                f" {len(members)} are present; an incomplete fleet is not the"
                " fleet the plan describes, so it is refused rather than"
                " qualified partially"
            )
    return tuple(members)


def _digest(models: Any) -> str:
    """A content digest over a sequence of pydantic models, order included.

    Order included on purpose: generation order is part of the determinism
    contract (ledger keys and minted ids depend on traversal order), so two
    corpora whose facts differ only in order are *not* the same corpus and must
    not digest equal.
    """
    from .ids import content_key

    return content_key(
        *(json.dumps(model.model_dump(mode="json"), sort_keys=True) for model in models)
    )


def _replayed(world: Any, facts_digest: str, plan_digest: str) -> tuple[bool, str]:
    """Whether *world* rebuilds from its recipe + ledger into the same corpus.

    Through ``recipe.rebuild`` and never through ``--replay`` with the original
    flags: ``tests/test_recipe_structure.py`` records the trap — a replay proof
    that re-supplies the command line lets the CLI reconstruct state from the
    flags, so the recording itself is never tested. Here nothing but the recipe
    and the ledger are on hand, which is the claim being verified.

    Compared on the fact ledger and the artifact *plan* (intents), both of
    which are final before narration — a rebuild is un-narrated, so comparing
    IRs would report every narrated corpus unverified for prose the ledger
    already protects.
    """
    from . import recipe as recipe_module
    from . import registries

    if recipe_module.has_actor_step(world.recipe):
        # An actor episode replays through the act handshake, which supplies a
        # provider for any decision the ledger lacks; verifying it here would
        # mean choosing a provider on the corpus's behalf. Stated rather than
        # silently passed, because "verified" must never mean "skipped".
        return False, (
            "actor-driven episode: replay verification needs an actor provider;"
            " drive it through the act handshake instead"
        )
    try:
        # Scoped so a pack-built member's registry installs do not outlive the
        # measurement — qualification is a reader, and a reader that left the
        # process's registries different is the leak `registries.scoped` exists
        # to stop.
        with registries.scoped():
            rebuilt = recipe_module.rebuild(world.recipe, ledger=world._ledger)
            rebuilt_facts = _digest(rebuilt.facts)
            rebuilt_plan = _digest(rebuilt.artifact_intents)
    except Exception as exc:  # noqa: BLE001 — see below
        # Broad on purpose: a tampered or truncated recipe raises whatever it
        # raises (`RecipeError`, `KeyError`, a pydantic error), and an admission
        # controller's job is to *name the member* that cannot be rebuilt, not
        # to die on it and report nothing about the rest of the fleet.
        return False, f"does not rebuild from its recipe: {exc}"
    if rebuilt_facts != facts_digest:
        return False, "rebuilt fact ledger differs from the shipped one"
    if rebuilt_plan != plan_digest:
        return False, "rebuilt artifact plan differs from the shipped one"
    return True, ""


# ---------------------------------------------------------------------------
# One member, measured — every field an instrument that already exists
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldRecord:
    """One member of the fleet, measured. Nothing here is new arithmetic:
    ``validate`` for coherence, ``validate.reachability`` for the spine,
    ``recipe.rebuild`` for replay, ``outcomes.read`` for the phenotype."""

    name: str
    seed: int
    archetype: str
    ok: bool
    checks_run: int
    violations: int
    violation_codes: tuple[str, ...]
    advisories: Mapping[str, int]
    """Advisory count by code — the channel ``validate`` reports findings that
    are true and are not incoherence (reachability above all)."""
    replay_verified: bool
    replay_detail: str
    facts_digest: str
    plan_digest: str
    questions: int
    families_present: int
    configuration: Mapping[str, str]
    """This member's position in ``spaces.build_space()``, derived from its
    recipe — see `configuration_of` for what is derivable and what is not."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seed": self.seed,
            "archetype": self.archetype,
            "validate": {
                "ok": self.ok,
                "checks_run": self.checks_run,
                "violations": self.violations,
                "violation_codes": list(self.violation_codes),
                "advisories": {code: self.advisories[code] for code in sorted(self.advisories)},
            },
            "replay": {"verified": self.replay_verified, "detail": self.replay_detail},
            "digests": {"facts": self.facts_digest, "plan": self.plan_digest},
            "questions": self.questions,
            "families_present": self.families_present,
            "configuration": {key: self.configuration[key] for key in sorted(self.configuration)},
        }


#: The shape `validate.reachability` files its findings in: one violation per
#: kind, opening "N of M <label>(s) ...". Parsed strictly and loudly — if the
#: message changes shape, `_survey` must fail naming the format, never degrade
#: into a spine share computed from half the kinds. The count is only carried
#: in prose because a `Violation` has no numeric field; the spine share is the
#: conjunction reading that module defines — a fact names the entity as
#: subject *and* a compiled document carries that fact.
_UNREACHED = re.compile(r"^(\d+) of (\d+) ")

#: Steps that are not episodes: they change the organisation, decay the
#: archive, or attach an authored estate, and counting them as periods would
#: report a twelve-step turbulent year as more periods than it has closes.
_NON_EPISODE_STEPS = frozenset({
    "Hire", "Departure", "Reorganisation", "HiringRound", "PerformanceCycle",
    "WorkforceChange", "StructuralChange", "Distractors", "Imperfections",
    "Compose",
})


def configuration_of(recipe: Mapping[str, Any]) -> dict[str, str]:
    """A corpus's recipe as a (partial) row of ``spaces.build_space()``.

    Partial honestly: a recipe records how a world was made, not which flags
    were typed, and three axes do not survive that translation. ``surface`` is
    structurally unrecoverable — a specification is *never* recorded, only its
    consequences (that is `--spec`'s own design), so a spec build and a flags
    build write identical recipes; `qualify` therefore measures coverage
    against the space *minus* that axis and names it underivable rather than
    scoring every fleet zero on pairs no recipe can witness. A timeline
    density is likewise recorded as its scheduled steps, not its name — a
    recipe whose closes force incidents in both directions is projected to
    ``"scheduled"``, a value the axis does not carry, so those pairs read as
    holes rather than as a density this function guessed. Same posture for a
    synthesis-only genome and a non-registry locale or messiness budget:
    `spaces.coverage` treats an unknown value as covering nothing, which is
    the truthful reading, and `BuildSpace.row`'s strict door is deliberately
    not used here because these rows arrive from recipes, not from hands.
    """
    from . import recipe as recipe_module

    steps: Sequence[Mapping[str, Any]] = recipe.get("steps") or ()
    closes = [step for step in steps if step.get("scenario") == "MonthEndClose"]
    episodes = [
        step for step in steps
        if "period" in step and step.get("scenario") not in _NON_EPISODE_STEPS
    ]

    forced = {step.get("incident") for step in closes} - {None}
    if forced == {True}:
        history = "incident"
    elif forced == {False}:
        history = "no_incident"
    elif not forced:
        history = "unforced"
    else:
        # Both directions forced across the steps: a timeline density decided
        # them, and which density is not on the recipe. See the docstring.
        history = "scheduled"

    densities = {step.get("eval_density", 1.0) for step in closes}
    density_names = {0.0: "low", 1.0: "standard", 2.0: "high"}
    if not closes:
        # The single-episode verticals take no density at all, and "standard"
        # is the one value legal on every engine — the projection target
        # `build_space`'s own docstring names for exactly this case.
        eval_density = "standard"
    elif len(densities) == 1:
        eval_density = density_names.get(next(iter(densities)), "mixed")
    else:
        eval_density = "mixed"

    genome_payload = recipe.get("structure") or {}
    omission = int(genome_payload.get("omission", 0) or 0)
    variant_bias = int(genome_payload.get("variant_bias", 0) or 0)
    if not genome_payload:
        genome = "authored"
    elif omission and variant_bias:
        genome = "both"
    elif omission:
        genome = "omission"
    elif variant_bias:
        genome = "variant_bias"
    else:
        genome = "synthesis"

    if any(step.get("conversations") for step in closes):
        knowledge = "conversations"
    elif recipe_module.has_actor_step(dict(recipe)):
        knowledge = "actors"
    else:
        knowledge = "none"

    imperfections = [step for step in steps if step.get("scenario") == "Imperfections"]
    profile = imperfections[-1].get("profile") if imperfections else "pristine"
    messiness = profile if isinstance(profile, str) else "custom"

    locale_payload = recipe.get("locale")
    if locale_payload is None:
        locale = "none"
    elif isinstance(locale_payload, str):
        locale = locale_payload
    else:
        locale = "custom"

    storylines = {step.get("storyline", "hierarchy_mapping") for step in closes}

    return {
        "archetype": str(recipe.get("archetype") or ""),
        "locale": locale,
        "estate": str(recipe.get("estate") or "none"),
        "policies": str(recipe.get("policies") or "none"),
        "messiness": messiness,
        "history": history,
        "periods": str(len(episodes)),
        "storyline": "varied" if len(storylines) > 1 else "fixed",
        "genome": genome,
        "eval_density": eval_density,
        "knowledge": knowledge,
    }


#: Why ``surface`` is measured around rather than through — kept as data so the
#: qualification record can carry the reason beside the omission.
_UNDERIVABLE = {
    "surface": (
        "a specification is resolved to consequences and never recorded"
        " (recipe design), so a spec build and a flags build write identical"
        " recipes and no fleet's recipes can witness this axis"
    ),
}


def _survey(
    fleet_dir: str | Path,
) -> tuple[tuple[WorldRecord, ...], tuple[Any, ...], dict[str, Any]]:
    """Load and measure every member. The expensive half of both verbs.

    Returns the spine reading alongside so each world is loaded exactly once —
    a member is validated, reachability-read, phenotype-read and rebuilt in one
    pass, and nothing later needs the ``World`` object again.
    """
    from . import outcomes
    from . import validate as validate_module
    from .world import World

    records: list[WorldRecord] = []
    readings: list[Any] = []
    declared = 0
    unreached = 0
    for member in _members(fleet_dir):
        world = World.load(member)
        report = world.validate()
        reach = validate_module.reachability(world)
        declared += reach.checks_run
        for violation in reach.violations:
            matched = _UNREACHED.match(violation.detail)
            if matched is None:
                raise FleetError(
                    "validate.reachability changed its finding format"
                    f" ({violation.detail[:60]!r}...); fleet._survey reads the"
                    " count off the front of it and must be updated with it"
                )
            unreached += int(matched.group(1))
        reading = outcomes.read(world, name=member.name, seed=world.seed or 0)

        facts_digest = _digest(world.facts)
        plan_digest = _digest(world.artifact_intents)
        replay_ok, replay_detail = _replayed(world, facts_digest, plan_digest)

        advisory_counts: dict[str, int] = {}
        for advisory in report.advisories:
            advisory_counts[advisory.code] = advisory_counts.get(advisory.code, 0) + 1

        records.append(WorldRecord(
            name=member.name,
            seed=world.seed or 0,
            archetype=str(world.recipe.get("archetype") or ""),
            ok=report.ok,
            checks_run=report.checks_run,
            violations=len(report.violations),
            violation_codes=tuple(sorted({v.code for v in report.violations})),
            advisories=advisory_counts,
            replay_verified=replay_ok,
            replay_detail=replay_detail,
            facts_digest=facts_digest,
            plan_digest=plan_digest,
            questions=len(reading.questions),
            families_present=sum(
                1 for key, value in reading.metrics.items()
                if key.startswith("family:") and value > 0
            ),
            configuration=configuration_of(world.recipe),
        ))
        readings.append(reading)
    spine = {
        "declared": declared,
        "unreached": unreached,
        "share": round((declared - unreached) / declared, 4) if declared else None,
    }
    return tuple(records), tuple(readings), spine


# ---------------------------------------------------------------------------
# Fleet-level readings, each from an instrument that already exists
# ---------------------------------------------------------------------------


def _question_readings(readings: Sequence[Any]) -> dict[str, Any]:
    """Total, distinct, and the cross-world near-duplicate share.

    "Near-duplicate" means here exactly what it means in ``stats`` and in
    ``outcomes``: same shingle size, same threshold, imported not restated. The
    share is per question — the fraction of the fleet's question instances that
    some *other* world restates — because a fraction of instances is actionable
    ("a fifth of this fleet's questions repeat across worlds") where a raw pair
    count is not (`outcomes._question_distance` makes the same argument).
    """
    from . import similarity
    from .stats import NEAR_DUPLICATE_THRESHOLD

    total = sum(len(reading.shingles) for reading in readings)
    restated = 0
    for i, reading in enumerate(readings):
        others = [
            shingle_set
            for j, other in enumerate(readings) if j != i
            for shingle_set in other.shingles
        ]
        for shingle_set in reading.shingles:
            if any(
                similarity.jaccard(shingle_set, other_set) >= NEAR_DUPLICATE_THRESHOLD
                for other_set in others
            ):
                restated += 1
    return {
        "total": total,
        "distinct": len({q for reading in readings for q in reading.questions}),
        "cross_world_restated_share": round(restated / total, 4) if total else 0.0,
    }


def _family_spread(readings: Sequence[Any]) -> dict[str, Any]:
    """How many worlds each evaluation family appears in, and the fleet total."""
    families = sorted({
        key.removeprefix("family:")
        for reading in readings for key in reading.metrics if key.startswith("family:")
    })
    per_family = {
        family: sum(
            1 for reading in readings if reading.metrics.get(f"family:{family}", 0) > 0
        )
        for family in families
    }
    return {
        "per_family": per_family,
        "present_somewhere": sum(1 for count in per_family.values() if count),
    }


def _effective_diversity(readings: Sequence[Any]) -> dict[str, Any]:
    """The fleet's effective number of distinct evaluation sets. **A reading.**

    Vendi over each world's pooled question shingles under Jaccard. Rounded and
    labelled non-gating in the record itself, because the label is the
    load-bearing part: an eigendecomposition's last bits vary by BLAS build, so
    the moment a floor compared this number the verdict would differ between
    machines — the contract rule this module exists under, stated where the
    number is, not only where the rule is.
    """
    from . import similarity, vendi

    pooled = [
        frozenset().union(*reading.shingles) if reading.shingles else frozenset()
        for reading in readings
    ]

    def kernel(left: frozenset, right: frozenset) -> float:
        # `similarity.jaccard` scores two empty sets 0.0, which is right for a
        # duplicate join and wrong for a kernel: vendi requires 1.0 on the
        # diagonal, and a world with no questions is identical to itself.
        if not left and not right:
            return 1.0
        return similarity.jaccard(left, right)

    return {
        "vendi_questions": round(vendi.vendi_of(pooled, kernel), 4),
        "gating": False,
        "note": (
            "effective number of distinct evaluation sets (vendi, Jaccard over"
            " question shingles); reported only — eigendecompositions vary in"
            " the last bits across BLAS builds, so no verdict reads this"
        ),
    }


def _floors(
    purpose: str, worlds: Sequence[WorldRecord]
) -> dict[str, dict[str, Any]]:
    """Every floor the purpose requires, each named with what failed it."""
    floors: dict[str, dict[str, Any]] = {}

    def floor(name: str, holds: bool, detail: str) -> None:
        floors[name] = {"holds": holds, "detail": detail if not holds else ""}

    incoherent = [w.name for w in worlds if not w.ok]
    floor(
        "every_world_coherent", not incoherent,
        "does not validate: " + ", ".join(
            f"{w.name} ({w.violations} violation(s))" for w in worlds if not w.ok
        ),
    )
    unreplayed = [w for w in worlds if not w.replay_verified]
    floor(
        "every_world_replays", not unreplayed,
        "; ".join(f"{w.name}: {w.replay_detail}" for w in unreplayed),
    )

    by_digest: dict[str, list[str]] = {}
    for w in worlds:
        by_digest.setdefault(w.facts_digest, []).append(w.name)
    repeated = sorted(names[0] for names in by_digest.values() if len(names) > 1)
    repeats_detail = "; ".join(
        " = ".join(sorted(names)) for names in by_digest.values() if len(names) > 1
    )
    floor("no_repeated_world", not repeated, f"identical fact ledgers: {repeats_detail}")

    if purpose == "challenge":
        silent = [w.name for w in worlds if w.questions == 0]
        floor(
            "every_world_asks", not silent,
            "no evaluation case minted: " + ", ".join(silent),
        )
    else:  # counterfactual
        floor(
            "at_least_two_worlds", len(worlds) >= 2,
            f"{len(worlds)} world(s); a counterfactual needs a factual to counter",
        )
        frames = sorted({w.archetype for w in worlds})
        floor(
            "shared_frame", len(frames) <= 1,
            "mixed archetypes confound the comparison: " + ", ".join(frames),
        )
    return floors


# ---------------------------------------------------------------------------
# qualify
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Qualification:
    """A fleet, measured, with a verdict for one declared purpose."""

    fleet: str
    purpose: str
    worlds: tuple[WorldRecord, ...]
    coverage: Mapping[str, Any]
    unvaried: tuple[str, ...]
    underivable: Mapping[str, str]
    spine: Mapping[str, Any]
    questions: Mapping[str, Any]
    families: Mapping[str, Any]
    effective_diversity: Mapping[str, Any]
    qualified: bool
    floors: Mapping[str, Mapping[str, Any]]
    failed: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fleet": self.fleet,
            "purpose": self.purpose,
            "worlds": [w.as_dict() for w in self.worlds],
            "configuration": {
                "coverage": dict(self.coverage),
                "unvaried": list(self.unvaried),
                "underivable": {k: self.underivable[k] for k in sorted(self.underivable)},
            },
            "spine": dict(self.spine),
            "questions": dict(self.questions),
            "families": {
                "per_family": dict(self.families["per_family"]),
                "present_somewhere": self.families["present_somewhere"],
            },
            "effective_diversity": dict(self.effective_diversity),
            "verdict": {
                "qualified": self.qualified,
                "floors": {name: dict(self.floors[name]) for name in sorted(self.floors)},
                "failed": list(self.failed),
            },
        }

    def manifest(self) -> str:
        """The record as canonical JSON — sorted keys, two-space indent, one
        trailing newline. Byte-for-byte identical across calls on one fleet,
        which is what lets a qualification be checked in and diffed."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


def qualify(fleet_dir: str | Path, purpose: FleetPurpose) -> Qualification:
    """Measure *fleet_dir* and rule on whether it is qualified for *purpose*.

    Reads only. No corpus is touched, nothing is written, and — the module
    docstring's design decision — nothing returned here is consumable by a
    build: the verdict names floors, the coverage names holes, and both are
    work lists for a *planner*, never objectives for a generator.
    """
    checked = _checked_purpose(purpose)
    root = Path(fleet_dir)
    records, readings, spine = _survey(root)

    from . import spaces

    space = spaces.build_space()
    derivable = space.select([n for n in space.names if n not in _UNDERIVABLE])
    rows = [dict(record.configuration) for record in records]
    holes = spaces.holes(derivable, rows)
    coverage = {
        "strength": 2,
        "share": round(spaces.coverage(derivable, rows), 4),
        "combinations": derivable.size_at(2),
        "missing": len(holes),
        # The first few holes only: the full list is `spaces.holes`' to give,
        # and a manifest carrying thousands of pairs would bury the verdict.
        "first_holes": [dict(hole) for hole in holes[:20]],
    }

    floors = _floors(checked, records)
    failed = tuple(sorted(name for name, entry in floors.items() if not entry["holds"]))
    return Qualification(
        fleet=root.name,
        purpose=checked,
        worlds=records,
        coverage=coverage,
        unvaried=spaces.unvaried(derivable, rows),
        underivable=dict(_UNDERIVABLE),
        spine=spine,
        questions=_question_readings(readings),
        families=_family_spread(readings),
        effective_diversity=_effective_diversity(readings),
        qualified=not failed,
        floors=floors,
        failed=failed,
    )


# ---------------------------------------------------------------------------
# curate
# ---------------------------------------------------------------------------

#: The niche axes, and why these two. Both are read off `outcomes.read` and
#: both are integers or argmaxes of exact integer ratios — never a float from
#: an eigendecomposition, which is the contract's hard line between features a
#: selection may use and readings it may only report.
#:
#: * ``gates`` — whether anything in the estate is a single point of failure
#:   (`graphs.chokepoints` count, zero or not). The repository's own topology
#:   reading says this is the clearest structural fact about an estate, and a
#:   fleet whose every world gates nothing cannot be asked half of what
#:   `worldloom topology` answers.
#: * ``difficulty_lead`` — which difficulty label leads the world's evaluation
#:   mix. Ties resolve toward the easier label, so a curation can understate a
#:   world's difficulty and can never overclaim it.
_NICHE_AXES: tuple[archive.Axis, ...] = (
    archive.Axis(name="gates", buckets=("none", "gated")),
    archive.Axis(name="difficulty_lead", buckets=("easy", "medium", "hard")),
)

#: What "best in niche" means, per purpose — each an integer reading from
#: `outcomes.read`. A challenge fleet keeps the world contributing the most
#: distinct document shapes, because shape scarcity is this repository's own
#: measured bottleneck (9 component shapes under a 42-ceiling heading
#: diversity); a counterfactual fleet keeps the richest fact ledger, because
#: the comparison is between ledgers and the poorer one bounds it.
_FITNESS: Mapping[str, str] = {
    "challenge": "distinct_shapes",
    "counterfactual": "facts",
}


def _niche(reading: Any) -> archive.Coordinates:
    """*reading*'s coordinates on `_NICHE_AXES`, in axis order."""
    gates = "gated" if reading.metrics.get("chokepoints", 0) > 0 else "none"
    shares = {
        label: reading.metrics.get(f"difficulty:{label}", 0.0)
        for label in ("easy", "medium", "hard")
    }
    # First maximum in easy→hard order: the conservative tie-break the axis
    # comment promises. `max` with a key would break ties by iteration order,
    # which happens to agree today and would drift silently if the tuple moved.
    lead = "easy"
    for label in ("medium", "hard"):
        if shares[label] > shares[lead]:
            lead = label
    return (gates, lead)


@dataclass(frozen=True)
class Champion:
    niche: Mapping[str, str]
    world: str
    fitness: int


@dataclass(frozen=True)
class Reject:
    world: str
    reason: str
    displaced_by: str
    """Empty when the world was never considered (it failed validation or
    replay), because nothing displaced it — it disqualified itself."""


@dataclass(frozen=True)
class Curation:
    """Champions per niche, the rejects and why, and the empty niches.

    The holes are the deliverable as much as the champions: they are the next
    generation's work list, handed to a *planner* — the one direction the
    module docstring permits information to flow.
    """

    fleet: str
    purpose: str
    fitness_metric: str
    champions: tuple[Champion, ...]
    rejects: tuple[Reject, ...]
    holes: tuple[Mapping[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fleet": self.fleet,
            "purpose": self.purpose,
            "niche_axes": [
                {"name": axis.name, "buckets": list(axis.buckets)} for axis in _NICHE_AXES
            ],
            "fitness": {
                "metric": self.fitness_metric,
                "gating": True,
                "note": (
                    "an integer reading from outcomes.read; effective diversity"
                    " (vendi) is deliberately not eligible here — selection may"
                    " only use deterministic integer/categorical features"
                ),
            },
            "champions": [
                {"niche": dict(champion.niche), "world": champion.world,
                 "fitness": champion.fitness}
                for champion in self.champions
            ],
            "rejects": [
                {"world": reject.world, "reason": reject.reason,
                 "displaced_by": reject.displaced_by}
                for reject in self.rejects
            ],
            "holes": [dict(hole) for hole in self.holes],
        }

    def manifest(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


def curate(fleet_dir: str | Path, purpose: FleetPurpose) -> Curation:
    """Keep one champion per niche, name every reject, list the empty niches.

    Writes ``fleet-manifest.json`` at the fleet root — deterministic
    byte-for-byte for the same fleet, so re-running it is a no-op diff — and
    touches nothing inside any member corpus.

    Only worlds that validate *and* replay are considered for a niche: a
    champion that is incoherent or cannot be rebuilt is not a champion, it is
    a defect with the best fitness in its cell. Such worlds are rejects with
    the disqualifying measurement as the reason and no ``displaced_by``,
    because nothing displaced them.
    """
    checked = _checked_purpose(purpose)
    root = Path(fleet_dir)
    # The spine reading is qualification's business, not curation's; surveyed
    # anyway because one pass per member is the deal `_survey` makes.
    records, readings, _ = _survey(root)

    metric = _FITNESS[checked]
    grid = archive.Archive(_NICHE_AXES)
    rejects: list[Reject] = []
    considered: list[tuple[WorldRecord, archive.Coordinates, int]] = []

    for record, reading in zip(records, readings, strict=True):
        if not record.ok:
            rejects.append(Reject(
                world=record.name,
                reason=f"does not validate ({record.violations} violation(s):"
                       f" {', '.join(record.violation_codes[:3])})",
                displaced_by="",
            ))
            continue
        if not record.replay_verified:
            rejects.append(Reject(
                world=record.name,
                reason=f"not replay-verified: {record.replay_detail}",
                displaced_by="",
            ))
            continue
        coordinates = _niche(reading)
        fitness = int(reading.metrics[metric])
        considered.append((record, coordinates, fitness))
        grid.consider(record.name, coordinates, float(fitness))

    elites = {elite.coordinates: elite for elite in grid.elites()}
    axis_names = tuple(axis.name for axis in _NICHE_AXES)

    for record, coordinates, fitness in considered:
        elite = elites[coordinates]
        if elite.key == record.name:
            continue
        if elite.fitness > fitness:
            reason = (
                f"niche held by a better {metric}:"
                f" {fitness} vs {int(elite.fitness)}"
            )
        else:
            # Equal fitness: `archive._beats` broke the tie on the smaller key,
            # which is a property of the candidates and of nothing else — said
            # here so a reject's line explains itself without reading archive.py.
            reason = f"equal {metric} ({fitness}); tie resolves to the smaller key"
        rejects.append(Reject(world=record.name, reason=reason, displaced_by=elite.key))

    curation = Curation(
        fleet=root.name,
        purpose=checked,
        fitness_metric=metric,
        champions=tuple(
            Champion(
                niche=dict(zip(axis_names, elite.coordinates, strict=True)),
                world=elite.key,
                fitness=int(elite.fitness),
            )
            for elite in grid.elites()
        ),
        rejects=tuple(sorted(rejects, key=lambda r: r.world)),
        holes=tuple(
            dict(zip(axis_names, hole, strict=True)) for hole in grid.holes()
        ),
    )
    (root / MANIFEST_NAME).write_text(curation.manifest(), encoding="utf-8")
    return curation


__all__ = [
    "MANIFEST_NAME",
    "PURPOSES",
    "Champion",
    "Curation",
    "FleetError",
    "FleetPurpose",
    "Qualification",
    "Reject",
    "WorldRecord",
    "configuration_of",
    "curate",
    "qualify",
]
