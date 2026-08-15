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
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .parameters import DEFAULT, Parameters
from .recipe import locale_of
from .rng import Rng
from .scenarios import lore_index

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


@dataclass(frozen=True)
class QuarterlyReserving:
    """One quarterly reserving cycle: triangle refresh, emergence, attribution,
    strengthening, and a partial-booking decision that opens a standing gap —
    and, beside it, the quarter's book cut by the organisation that wrote it.

    The second half is not part of the reserving argument and is deliberately
    not entangled with it. It exists because the reserving cycle is about one
    long-tail book and named no business unit, no branch, no claims centre, no
    underwriting office, no cost centre and no system: a whole insurer declared
    in the archetype and reaching nothing. ``generators/insurance_book.py``
    states the measures each of those places actually owns, and why
    ``reserves.*`` is not one of them.

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
        from .generators import insurance_book, insurance_evaluation, reserving, triangles
        from .generators.finance import previous_periods
        from .generators.operations import business_days_after, period_end

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
            # This corpus's own working week — see `MonthEndClose.run`. Every
            # date the reserving cycle places is the quarter end plus a count of
            # working days, so without this a Gulf insurer signs off its
            # triangle on a Friday.
            calendar=locale_of(world.recipe),
            physics=self.physics,
        )

        # The book, cut by the organisation that wrote it. Run *after* the
        # reserving cycle rather than before it for two reasons, and both are
        # about identity rather than taste. `Minter` is sequential, so putting
        # this first would renumber every FACT and EV id the reserving episode
        # mints and detach the checked-in narration from the facts it cites.
        # And the ordering is also the truth: the valuation reads a closed
        # quarter, so the quarter's own book position is a fact of the close and
        # not of the valuation — which is why its facts are dated to the working
        # day after the ledger locked (`bd(5)`) rather than to the valuation.
        archetype = world._archetype
        # Pure arithmetic on the period string and on this corpus's own working
        # week — `scenarios.finalised_at`'s style exactly, and no clock, so
        # replay stays byte-identical. Five working days after the quarter end
        # is one day after the ledger locks (`reserving.generate`'s `bd(4)`).
        settled = business_days_after(
            period_end(self.period), 5, locale_of(world.recipe)
        )
        recorded_at = datetime(
            settled.year, settled.month, settled.day, 8, 30, tzinfo=timezone.utc
        )
        book = insurance_book.generate(
            rng.derive("book"), minter,
            period=self.period,
            company_id=world.company.id,
            unit_ids={unit.key: roles[f"unit_{unit.key}"] for unit in archetype.units},
            unit_shares={unit.key: unit.share for unit in archetype.units},
            categories=tuple(world.categories),
            sites=tuple(world.sites),
            cost_centres=tuple(world.cost_centres),
            systems=tuple(world.systems),
            # A quarter of the archetype's declared annual figure. How many
            # periods a year holds is this scenario's arithmetic — `Domain.
            # period_step_months` is 3 here — and not the generator's.
            quarterly_revenue=world._annual_revenue // 4,
            money_unit=f"{world.company.currency}_{world.company.currency_unit}",
            recorded_at=recorded_at,
            caused_by=[episode.keys["event_close_finalised"]],
            lore_by_target=index,
            policy_admin_id=roles["sys_policy_admin"],
            claims_system_id=roles["sys_claims"],
            general_ledger_id=roles["sys_general_ledger"],
            physics=self.physics,
        )

        intents, errors = insurance_documents.artifact_intents(
            minter, episode=episode, roles=roles, book=book,
            units=tuple(
                (unit.key, roles[f"unit_{unit.key}"], unit.name)
                for unit in archetype.units
            ),
        )
        cases = insurance_evaluation.evaluation_cases(
            minter, episode=episode, intents=intents, period=self.period,
            company=world.company.name,
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
            events=(*episode.events, *book.events),
            facts=(*new_facts, *book.facts),
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
