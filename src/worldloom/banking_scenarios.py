"""Banking scenarios.

``QuarterlyCapitalReturn`` is an ordinary frozen dataclass with a ``run``
method, exactly as ``scenarios.py``'s docstring prescribes and for the same
reason: the scenario abstraction gets extracted from what two verticals
*actually repeat*, not designed ahead of the second one. This is the second
one — the repetition evidence, not the abstraction.

What repeats already, reused rather than re-invented: the lore index and its
multiplier helpers (generic over lore), ``period_end``/``business_days_after``
(pure calendar arithmetic), the recipe step discipline, and the extend/derive
shape of ``MonthEndClose.run``. What does not repeat: everything the episode
generates — which is the point of a second vertical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .generators.operations import business_days_after, period_end
from .rng import Rng
from .scenarios import lore_index

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: Where the daily liquidity window sits relative to period end: it opens two
#: business days after the return is lodged (bd 18) and runs long enough that
#: the reconciliation break lands on its fifth day, with one further
#: observation after it — the daily cadence keeps ticking through detection.
_LIQUIDITY_START_BD = 20


@dataclass(frozen=True)
class QuarterlyCapitalReturn:
    """One quarterly capital-return cycle: prepared, challenged, filed anyway,
    caught by the daily cadence, and restated.

    ``period`` is the quarter-end month as ``YYYY-MM`` — the label "Q1" exists
    only inside prose. Every ``YYYY-MM`` consumer in the core (``period_end``,
    ``previous_periods``, the period boundary arithmetic) works unchanged, and
    no quarter grammar is ever parsed anywhere.
    """

    period: str

    def run(self, world: World) -> World:
        from . import banking_documents
        from .generators import banking_evaluation, capital, liquidity, regulatory

        if world.seed is None:
            raise ValueError(
                "a scenario needs a seeded world; use BankingWorld(seed=...).build()"
            )
        if world._minter is None:
            raise ValueError(
                "this world was loaded from disk and cannot be advanced; build one from a seed"
            )
        if world._archetype is None:
            raise ValueError("this world has no archetype; build one with BankingWorld(...)")

        rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
        minter = world._minter
        roles = dict(world._roles)
        index = lore_index(world)

        if "cat_sme_secured" not in roles:
            raise ValueError(
                "this world has no SME Secured Lending book; QuarterlyCapitalReturn"
                " runs against a banking archetype"
            )

        # Books are every category with an income share — the treasury unit has
        # none, honestly. RWA weights follow the same two-level share the
        # archetype states for income.
        books = tuple(c for c in world._categories if c.revenue_share > 0)
        unit_share_of = {
            roles[f"unit_{unit.key}"]: unit.share for unit in world._archetype.units
        }

        position = capital.generate(
            rng.derive("capital"),
            books=books,
            affected_book_id=roles["cat_sme_secured"],
            unit_share_of=unit_share_of,
        )
        series = liquidity.generate(
            rng.derive("liquidity"),
            start=business_days_after(period_end(self.period), _LIQUIDITY_START_BD),
            days=regulatory.LIQUIDITY_DAYS,
        )
        episode = regulatory.generate(
            rng.derive("regulatory"), minter,
            period=self.period,
            company_id=world.company.id,
            roles=roles,
            position=position,
            liquidity=series,
            book_names={c.id: c.name for c in world._categories},
            lore_by_target=index,
        )

        intents, errors = banking_documents.artifact_intents(
            minter, episode=episode, roles=roles,
        )
        cases = banking_evaluation.evaluation_cases(
            minter, episode=episode, intents=intents, period=self.period,
        )

        from .recipe import with_step

        return world.extend(
            events=episode.events,
            facts=episode.facts,
            artifact_intents=intents,
            intentional_errors=errors,
            evaluations=cases,
            period=self.period,
            recipe=with_step(world._recipe, "QuarterlyCapitalReturn", period=self.period),
        )


__all__ = ["QuarterlyCapitalReturn"]
