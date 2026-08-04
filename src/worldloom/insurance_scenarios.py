"""Insurance scenarios.

``QuarterlyReserving`` is an ordinary frozen dataclass with a ``run`` method,
exactly as ``scenarios.py``'s docstring prescribes and as
``QuarterlyCapitalReturn`` already exercises — the third data point, not a
new pattern.

What repeats: the lore index and its multiplier helpers, ``period_end`` and
the business-day arithmetic, the recipe step discipline, and the
extend/derive shape every scenario's ``run`` has. What does not repeat: the
reserving cycle itself, which lives in ``generators/reserving.py`` and
``generators/triangles.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .parameters import DEFAULT, Parameters
from .rng import Rng
from .scenarios import lore_index

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


@dataclass(frozen=True)
class QuarterlyReserving:
    """One quarterly reserving cycle: triangle refresh, emergence, attribution,
    strengthening, and a partial-booking decision that opens a standing gap.

    ``period`` is the valuation quarter-end month as ``YYYY-MM`` — the same
    ``period_end``/``previous_periods`` arithmetic every other scenario uses,
    and no quarter grammar is parsed anywhere.

    Increment 1 is phase 1 only: the first run on a world mints the complete
    three-discipline record (triangle, estimate chain, decision) and leaves
    an open central-versus-booked gap. Phase 2 — the gap closing by
    reconciliation, a superseded attribution, the retrospective finding — is
    increment 2's scope, not this vertical's yet. A second run refuses,
    naming increment 2 explicitly, rather than silently minting a duplicate
    standing record or pretending to advance a phase this module cannot
    write. The guard lives here, inside the episode, and not in the CLI:
    ``tests/test_thin_waist.py`` forbids naming an engine's vocabulary in
    core, and "insurance" is exactly that.
    """

    period: str
    physics: Parameters = DEFAULT
    """The world physics this quarter's figures are drawn under. A field with
    a default rather than a ``run`` argument, so it reaches the generators the
    same way ``period`` does and a caller that has one states it once. How a
    non-default one arrives from outside — a pack's overrides, carried on the
    recipe so a replay needs no pack file — is the build's business, not this
    scenario's."""

    def run(self, world: World) -> World:
        from . import insurance_documents
        from .generators import insurance_evaluation, reserving, triangles
        from .generators.finance import previous_periods

        if world.seed is None:
            raise ValueError(
                "a scenario needs a seeded world; use InsuranceWorld(seed=...).build()"
            )
        if world._minter is None:
            raise ValueError(
                "this world was loaded from disk and cannot be advanced; build one from a seed"
            )
        if world._archetype is None:
            raise ValueError("this world has no archetype; build one with InsuranceWorld(...)")

        roles = dict(world._roles)
        if "cat_lt_liability" not in roles:
            raise ValueError(
                "this world has no long-tail liability book; QuarterlyReserving runs"
                " against an insurance archetype"
            )

        # The phase guard. A world already carries an open gap and standing
        # attribution facts once phase 1 has run once — reading the world's
        # own record (never a counter this scenario would have to thread
        # through the recipe) is the `prior_incident_periods` pattern
        # `operations.generate` already uses for its own recurrence check.
        if any(f.kind == "reserves.held_vs_central_gap" for f in world.facts):
            raise ValueError(
                "a second QuarterlyReserving run would be phase 2 (attribution"
                " supersession, gap closure, the retrospective finding) — increment 1"
                " implements phase 1 only. Increment 2 is where a second consecutive"
                " valuation quarter is supported; until then, build one quarter at a time."
            )

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
        minter = world._minter
        index = lore_index(world)

        # The standing margin policy: standard is 12% of the central
        # estimate, in the band the design record's "75th-percentile margin
        # policy" describes. A second quarter would resolve this from the
        # world exactly as `capital.minimum_cet1_requirement` does — moot
        # under the phase guard above, but the lookup costs nothing and
        # keeps this scenario shaped like the pattern it will extend into.
        existing_philosophy = world.authoritative("reserves.philosophy", world.company.id)
        existing_margin_policy = world.authoritative(
            "reserves.risk_margin_policy_pct", world.company.id
        )
        risk_margin_policy_pct = (
            existing_margin_policy.value.amount if existing_margin_policy is not None else 12.0
        )

        # Four accident cohorts, three months apart, ending three months
        # before the valuation — the episode's own choice of how far back to
        # ask the triangle generator for, never the archetype's (design
        # record, risk 2: a many-unit pack must not silently multiply the
        # grid).
        lookback = previous_periods(self.period, reserving.COHORT_COUNT * 3)
        accident_periods = tuple(lookback[i] for i in range(0, len(lookback), 3))

        triangle = triangles.generate(
            rng.derive("triangle"),
            accident_periods=accident_periods,
            risk_margin_policy_pct=risk_margin_policy_pct,
            physics=self.physics,
        )
        episode = reserving.generate(
            rng.derive("reserving"), minter,
            period=self.period,
            company_id=world.company.id,
            roles=roles,
            triangle=triangle,
            lore_by_target=index,
            risk_margin_policy_pct=risk_margin_policy_pct,
            # Pack episode-text overrides ride the recipe, so a pack-built
            # corpus rebuilds them with no pack file on hand.
            text=(world._recipe.get("pack") or {}).get("episode_text") or None,
            existing_philosophy=existing_philosophy,
            existing_margin_policy=existing_margin_policy,
            physics=self.physics,
        )

        intents, errors = insurance_documents.artifact_intents(
            minter, episode=episode, roles=roles,
        )
        cases = insurance_evaluation.evaluation_cases(
            minter, episode=episode, intents=intents, period=self.period,
            text=(world._recipe.get("pack") or {}).get("evaluation_text") or None,
        )

        from .recipe import with_step

        # `episode.facts` carries the standing philosophy/margin-policy
        # facts whether this quarter minted them or reused ones already on
        # the world's record — see `regulatory.py`'s identical comment on
        # why a reused fact must be filtered back out before `world.extend`,
        # which is append-only.
        known_fact_ids = set(world.facts.ids())
        new_facts = tuple(f for f in episode.facts if f.id not in known_fact_ids)

        return world.extend(
            events=episode.events,
            facts=new_facts,
            artifact_intents=intents,
            intentional_errors=errors,
            evaluations=cases,
            period=self.period,
            recipe=with_step(world._recipe, "QuarterlyReserving", period=self.period),
        )


# The recipe verb: registered here, from insurance's own module, through
# `recipe.register_step` rather than as a third literal in `recipe.py` —
# `QuarterlyReserving` was the rule-of-three trigger the design record names
# (banking's own two-line edit already having landed the first two: a
# `STEPS` entry and an `elif` branch), so this vertical is what pays for the
# registry rather than adding to what it replaces. Same calling convention
# as banking's: the scenario class itself is the builder,
# `QuarterlyReserving(period=...)`.
from . import recipe as _recipe  # noqa: E402

_recipe.register_step("QuarterlyReserving", ("period",), QuarterlyReserving)


__all__ = ["QuarterlyReserving"]
