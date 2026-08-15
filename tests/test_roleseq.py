"""What `roleseq` claims, checked against the outlines it claims it about.

The module's headline is a table of eight projections, and a table nobody
recomputes is a comment — so most of what follows re-derives it from the shipped
outlines rather than restating it.

Two things the numbers needed before they could be pinned at all. They are
counted over `engine_outlines()`, not over `documents._OUTLINES`, because that
dict is a process-global registry a pack fixture can add to. And the `heading`
row of the table is checked as a *ratio* rather than a digit, because it moves
whenever somebody renames a heading — which happened during this very wave — and
an intended edit to `policies.py` must not read as a defect in `roleseq.py`.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest

import worldloom  # noqa: F401  — imports every vertical, which is what installs them
from worldloom import adjacency, doctypes, roleseq
from worldloom.documents import _OUTLINES
from worldloom.rng import Rng


def engine_outlines() -> dict[str, tuple]:
    """`documents._OUTLINES` minus anything a pack authored.

    Not a precaution: `_OUTLINES` is a process-global registry and
    `doctypes.install` deliberately never un-installs, so any pack fixture
    anywhere in the suite leaves its type in the dict for every test that runs
    afterwards. Measured before this filter, the table below read
    `(71, 64, 87, 49)` in a full run against `(71, 63, 84, 47)` alone — the
    signature `tests/test_optional_sections.installed` documents at length, on
    `franchisee_trading_statement` from the doctypes fixtures.

    The figures in `roleseq.py`'s docstring are a claim about *the fleet this
    repository ships*, so that is what they are counted over. A pack's own
    outlines are the pack author's business, and a measurement that silently
    absorbs them is measuring whoever ran first.
    """
    authored = set(doctypes.installed())
    return {key: plans for key, plans in _OUTLINES.items() if key not in authored}


@dataclass(frozen=True)
class Plan:
    """A stand-in for `documents.SectionPlan`, satisfying `roleseq.Section`.

    Hand-rolled rather than imported so the unit tests below state their own
    inputs: a projection test that has to be read against a 2,600-line module to
    know what went in is a test of two things.
    """

    heading: str
    kinds: tuple[str, ...]
    scope: str


# --- who issues what --------------------------------------------------------
#
# The vertical partition is the caller's, not the library's, because "which
# companies exist" is a fact about this repository's engines and `roleseq` is
# meant to outlive them. It is spelled out here rather than derived from which
# module happens to mention a key, so that adding a document type fails the
# completeness check below instead of being silently filed under retail.

_BANKING = (
    "rwa_working_paper",
    "second_line_challenge_memo",
    "internal_audit_review",
    "board_risk_committee_summary",
)
_INSURANCE = (
    "claims_emergence_note",
    "actuarial_valuation_report",
    "margin_decision_memo",
    "underwriting_result_commentary",
)
_PROCUREMENT = ("match_exception_report", "payment_approval_memo", "vendor_master_change")

#: Families every company has, whatever engine built it: ten policies and five
#: workforce records. They belong under every tag, which is what lets a policy
#: section splice into four verticals' documents while the verticals stay apart.
_EVERY_COMPANY = (
    "delegation_of_authority",
    "code_of_conduct",
    "business_continuity_policy",
    "expense_policy",
    "travel_policy",
    "leave_policy",
    "remote_work_policy",
    "information_security_policy",
    "data_retention_policy",
    "procurement_policy",
    "job_requisition",
    "offer_letter",
    "onboarding_checklist",
    "performance_review",
    "one_to_one_note",
)

#: The retail engine's own close and incident paperwork, plus the archetype
#: variants (a mutual's member report, a government body's ministerial brief).
_RETAIL = (
    "cfo_variance_memo",
    "executive_summary",
    "working_note",
    "confluence_page",
    "knowledge_article",
    "unit_close_commentary",
    "close_calendar",
    "service_impact_assessment",
    "remediation_scope_review",
    "peak_trading_review",
    "audit_committee_pack",
    "sponsor_pack",
    "member_report",
    "ministerial_brief",
    "estate_change_notice",
    "routine_notice",
)

#: Every type the engine ships, spelled out so that the vertical attribution
#: below is total and "the 43 shipped outlines" is a fact a reader can check.
FLEET = _RETAIL + ("incident_rca",) + _BANKING + _INSURANCE + _PROCUREMENT + _EVERY_COMPANY

VERTICALS = ("banking", "insurance", "procurement", "retail")


def tags_for(key: str) -> tuple[str, ...]:
    if key in _EVERY_COMPANY:
        return VERTICALS
    if key in _BANKING:
        return ("banking",)
    if key in _INSURANCE:
        return ("insurance",)
    if key in _PROCUREMENT:
        return ("procurement",)
    if key == "incident_rca":
        # Planned by both the retail incident scenario and the banking one, and
        # the only type in the fleet that genuinely belongs to two engines.
        return ("banking", "retail")
    return ("retail",)


@pytest.fixture
def shipped() -> dict[str, list[tuple]]:
    """The fleet, partitioned by who issues it.

    Function-scoped rather than module-scoped: `engine_outlines` reads a global
    registry whose contents depend on what has run, and a fixture cached across
    a module would freeze whichever answer the first test happened to get.
    """
    engine = engine_outlines()
    examples: dict[str, list[tuple]] = {tag: [] for tag in VERTICALS}
    for key, outline in engine.items():
        for tag in tags_for(key):
            examples[tag].append(outline)
    return examples


def test_every_shipped_type_is_attributed_to_a_company_that_issues_it() -> None:
    """The fleet is what it says it is, in both directions.

    `tags_for` has an `else` that says retail, which is right for the sixteen
    retail close and incident types and wrong for the next vertical somebody
    adds. This is the check that makes the wrongness loud: a type that ships and
    is not named here goes unmeasured, and a type named here that no longer ships
    would quietly shrink the corpus the table is quoted against.
    """
    assert len(FLEET) == len(set(FLEET)) == 43
    assert set(FLEET) == set(engine_outlines()), (
        "the shipped fleet has moved. Name the new type in `_RETAIL` or the"
        " vertical family that issues it, then re-derive roleseq.py's table —"
        " a document type is a row of the measurement, not a detail below it."
    )


# --- the projection ---------------------------------------------------------


def test_symbol_spells_the_projection_the_docstring_advertises() -> None:
    plan = Plan("By business unit", ("financial.revenue.", "financial.gross_profit."), "unit")
    assert roleseq.symbol(plan) == "unit:financial.revenue"
    assert roleseq.symbol(plan, projection="kind") == "financial.revenue"
    assert roleseq.symbol(plan, projection="domain") == "financial"
    assert roleseq.symbol(plan, projection="scope+domain") == "unit:financial"
    assert roleseq.symbol(plan, projection="scope") == "unit"
    assert roleseq.symbol(plan, projection="heading") == "By business unit"
    assert (
        roleseq.symbol(plan, projection="kinds")
        == "financial.revenue+financial.gross_profit"
    )
    assert roleseq.symbol(plan, tag="retail") == "retail|unit:financial.revenue"


def test_a_section_with_no_kind_projects_to_a_symbol_rather_than_vanishing() -> None:
    """`routine_notice` carries `kinds=("",)` and is a real start and end window."""
    assert roleseq.symbol(Plan("Status", ("",), "any")) == "any:"
    assert roleseq.symbol(Plan("Status", (), "any")) == "any:"


def test_a_tag_may_not_smuggle_the_separator() -> None:
    with pytest.raises(ValueError, match="separates"):
        roleseq.symbol(Plan("h", ("a.b",), "any"), tag="retail|banking")


def test_an_unknown_projection_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown projection"):
        roleseq.symbol(Plan("h", ("a.b",), "any"), projection="vibes")  # type: ignore[arg-type]


# --- the measurement --------------------------------------------------------

MAX_LENGTH = 8
"""The bound the module's table is quoted at: the longest shipped outline plus
two, which is enough room for a splice to exceed both of its parents."""

#: The docstring's table, for the seven projections that read `kinds`/`scope`
#: and are therefore unaffected by anybody renaming a heading.
#: (symbols, windows, admitted-within-one-vertical, novel).
#:
#: The `heading` row is deliberately absent. It is the control, it is 84/63/34/1,
#: and it moves the moment a heading is edited — which lane C of this very wave
#: is about to do to ten policies. Pinning it here would make an intended change
#: to `policies.py` look like a defect in `roleseq.py`. What is worth asserting
#: about the control is a *ratio*, and `test_roles_beat_headings_by_two_orders`
#: asserts that instead.
TABLE: dict[str, tuple[int, int, int, int]] = {
    "kinds": (72, 63, 114, 76),
    "scope+kinds": (73, 64, 85, 47),
    "kind": (54, 59, 265, 229),
    "scope+kind": (56, 60, 196, 159),
    "domain": (15, 27, 1089, 1060),
    "scope+domain": (18, 30, 836, 806),
    "scope": (3, 8, 282, 268),
}


def _pooled(shipped: dict[str, list[tuple]], projection: str):
    """One untagged model over every outline, whoever issues it."""
    flat = [outline for tag in VERTICALS for outline in shipped[tag]]
    return roleseq.learn_roles({"": flat}, projection=projection)  # type: ignore[arg-type]


def _measure(shipped: dict[str, list[tuple]], projection: str) -> tuple[int, int, int, int]:
    pooled = _pooled(shipped, projection)
    tagged = roleseq.learn_roles(shipped, projection=projection)  # type: ignore[arg-type]
    candidates = roleseq.admitted(pooled, max_length=MAX_LENGTH)
    refused = set(roleseq.refused(tagged, VERTICALS, candidates))
    kept = [shape for shape in candidates if shape not in refused]
    training = {
        roleseq.project(outline, projection=projection)  # type: ignore[arg-type]
        for tag in VERTICALS
        for outline in shipped[tag]
    }
    novel = [shape for shape in kept if shape not in training]
    return len(pooled.alphabet), len(pooled.windows), len(kept), len(novel)


@pytest.mark.parametrize("projection", sorted(TABLE))
def test_the_docstring_table_is_what_the_shipped_outlines_actually_say(
    shipped: dict[str, list[tuple]], projection: str
) -> None:
    assert _measure(shipped, projection) == TABLE[projection], (
        f"the {projection!r} row of roleseq.py's table has moved. That is not"
        " automatically a defect — a document type gaining a section moves it —"
        " but the docstring is the deliverable here, so update it in the same"
        " change rather than adjusting this pin."
    )


#: A corpus small enough to check by hand, so the machinery has an exact pin
#: that does not move when somebody edits a document type. Two "verticals"
#: sharing one family, which is the shipped shape in miniature.
_TOY: dict[str, list[tuple[Plan, ...]]] = {
    "alpha": [
        (Plan("Position", ("fin.rev.",), "group"), Plan("By unit", ("fin.rev.",), "unit")),
        (Plan("Purpose", ("pol.hr.",), "any"), Plan("Duties", ("pol.hr.",), "any")),
    ],
    "beta": [
        (Plan("Capital", ("cap.rwa.",), "any"), Plan("Ruling", ("cap.challenge.",), "any")),
        (Plan("Purpose", ("pol.hr.",), "any"), Plan("Duties", ("pol.hr.",), "any")),
    ],
}


def test_the_toy_corpus_measures_exactly_what_it_looks_like() -> None:
    """An exact pin on the machinery rather than on the fleet.

    Six symbols pooled — `group:fin.rev`, `unit:fin.rev`, `any:pol.hr`,
    `any:cap.rwa`, `any:cap.challenge`, and nothing else — three windows, and
    `any:pol.hr` follows itself. The whole point of having this beside the
    measurement against `_OUTLINES` is that a change to a document type moves
    that one and must not move this one.
    """
    pooled = roleseq.learn_roles({"": _TOY["alpha"] + _TOY["beta"]})
    assert pooled.alphabet == (
        "any:cap.challenge",
        "any:cap.rwa",
        "any:pol.hr",
        "group:fin.rev",
        "unit:fin.rev",
    )
    assert len(pooled.windows) == 3
    # `any:pol.hr` self-loops, so the pooled model admits pol.hr sequences of
    # every length; the bound is what makes the count finite.
    assert len(roleseq.admitted(pooled, max_length=4)) == 5
    tagged = roleseq.learn_roles(_TOY)
    assert len(tagged.alphabet) == 6  # five pooled roles, pol.hr counted once per tag
    assert len(tagged.windows) == 4
    # Nothing crosses: alpha's revenue pair and beta's capital pair never meet,
    # which at this size can be read off the corpus above.
    candidates = roleseq.admitted(pooled, max_length=4)
    assert roleseq.refused(tagged, ("alpha", "beta"), candidates) == ()


def _shuffles_admitted(shipped: dict[str, list[tuple]], projection: str) -> tuple[int, int]:
    """How many reorderings of real outlines the model waves through.

    The coarse-end failure test. A projection that admits every permutation of a
    document somebody wrote has learned that sections exist, not what order they
    go in.
    """
    model = _pooled(shipped, projection)
    seen: set[tuple] = set()
    total = admitted = 0
    for tag in VERTICALS:
        for outline in shipped[tag]:
            if not 2 <= len(outline) <= 6 or id(outline) in seen:
                continue
            seen.add(id(outline))
            base = roleseq.project(outline, projection=projection)  # type: ignore[arg-type]
            for permutation in itertools.permutations(base):
                if permutation == base:
                    continue
                total += 1
                admitted += adjacency.admits(model, permutation)
    return admitted, total


@pytest.mark.parametrize("projection", ["kinds", "scope+kinds", "kind", "scope+kind"])
def test_a_kind_bearing_projection_admits_no_reordering_of_a_real_document(
    shipped: dict[str, list[tuple]], projection: str
) -> None:
    admitted, total = _shuffles_admitted(shipped, projection)
    assert total > 1000
    assert admitted == 0


@pytest.mark.parametrize("projection", ["domain", "scope+domain", "scope"])
def test_a_coarse_projection_waves_reorderings_through(
    shipped: dict[str, list[tuple]], projection: str
) -> None:
    """The measured reason `domain` and `scope` are not the pick.

    Asserted as "some, and fewer than everything" rather than as an exact count,
    because the claim that decided the projection is qualitative: at this
    coarseness the model stops constraining order at all, which is what
    `adjacency` exists to prevent.
    """
    admitted, total = _shuffles_admitted(shipped, projection)
    assert 0 < admitted < total


def test_dropping_scope_merges_the_two_sections_of_the_variance_memo(
    shipped: dict[str, list[tuple]],
) -> None:
    """The fine-end argument, as a fact rather than a preference.

    `cfo_variance_memo` opens "Position" (group) then "By business unit" (unit)
    over identical kinds. Without scope they are one symbol, so the model learns
    a self-loop and can emit "state the group position, then state it again" —
    which is most of the gap between the `kind` and `scope+kind` rows above.
    """
    loops = {
        projection: {
            window[0]
            for window in _pooled(shipped, projection).windows
            if len(window) == 2 and window[0] == window[1]
        }
        for projection in ("kind", "scope+kind")
    }
    assert "financial.revenue" in loops["kind"]
    assert "any:financial.revenue" not in loops["scope+kind"]
    assert "unit:financial.revenue" not in loops["scope+kind"]
    # What remains at `scope+kind` is the policy family's real pair — purpose
    # then responsibilities, both over one `policy.*` kind — and that loop is a
    # document two authors wrote, not an artifact of the projection.
    assert loops["scope+kind"] and all(s.startswith("any:policy.") for s in loops["scope+kind"])


def test_roles_beat_headings_by_two_orders(shipped: dict[str, list[tuple]]) -> None:
    """The headline: the vocabulary was the ceiling, not the algorithm.

    Stated as a ratio because the heading baseline moves whenever somebody edits
    a heading, and the claim being made does not.
    """
    _, _, _, novel_headings = _measure(shipped, "heading")
    _, _, _, novel_roles = _measure(shipped, roleseq.DEFAULT)
    assert novel_headings <= 5
    assert novel_roles > 100 * max(novel_headings, 1)


def test_the_cross_vertical_guard_refuses_more_than_it_keeps(
    shipped: dict[str, list[tuple]],
) -> None:
    """218 refused against 196 kept, and the refusals are the interesting half.

    A splice whose windows are each real and whose whole is issued by no company
    is exactly the defect the last wave's report named. Asserting the guard bites
    hard — more than a third of the pooled space — is the check that tagging did
    something, as opposed to being a prefix nothing ever collides on.
    """
    pooled = _pooled(shipped, roleseq.DEFAULT)
    tagged = roleseq.learn_roles(shipped)
    candidates = roleseq.admitted(pooled, max_length=MAX_LENGTH)
    refused = roleseq.refused(tagged, VERTICALS, candidates)
    assert len(refused) > len(candidates) // 3
    for shape in refused:
        assert adjacency.admits(pooled, shape)
        for tag in VERTICALS:
            assert not adjacency.admits(tagged, tuple(f"{tag}|{sym}" for sym in shape))


def test_no_learned_window_ever_crosses_two_verticals(shipped: dict[str, list[tuple]]) -> None:
    """The guard, structurally: the tag is inside the symbol, so it cannot leak."""
    model = roleseq.learn_roles(shipped)
    for window in model.windows:
        assert len({symbol.split("|", 1)[0] for symbol in window}) == 1


# --- realisation ------------------------------------------------------------


def test_realise_never_uses_one_heading_twice(shipped: dict[str, list[tuple]]) -> None:
    catalogue = roleseq.catalogue(shipped)
    rng = Rng(8128, "realise")
    model = roleseq.learn_roles(shipped)
    seen = 0
    for shape in roleseq.admitted(model, max_length=6):
        realised = roleseq.realise(shape, catalogue, rng=rng.derive(str(seen)))
        if realised is None:
            continue
        seen += 1
        headings = [section.heading for section in realised]
        assert len(headings) == len(set(headings)) == len(shape)
    assert seen > 100


def test_realise_backtracks_rather_than_reporting_a_false_refusal() -> None:
    """Greedy fails here; the search must not.

    Two symbols, and the first one's only overlap with the second is a heading
    the second cannot do without. Take it greedily and the second symbol has
    nothing left, so a greedy implementation answers "no realisation" for a
    sequence that plainly has one.
    """
    shared = Plan("Shared", ("a.one.",), "any")
    only = Plan("Only", ("a.two.",), "any")
    catalogue = roleseq.Catalogue(
        projection="scope+kind",
        sections={"any:a.one": (shared,), "any:a.two": (shared, only)},
    )
    realised = roleseq.realise(("any:a.two", "any:a.one"), catalogue, rng=Rng(1, "t"))
    assert realised is not None
    assert [section.heading for section in realised] == ["Only", "Shared"]


def test_realise_refuses_what_the_catalogue_cannot_supply() -> None:
    catalogue = roleseq.Catalogue(
        projection="scope+kind", sections={"any:a.one": (Plan("Only one", ("a.one.",), "any"),)}
    )
    assert roleseq.realise(("any:a.one", "any:a.one"), catalogue, rng=Rng(1, "t")) is None
    assert roleseq.realise(("any:nope",), catalogue, rng=Rng(1, "t")) is None
    assert roleseq.realise((), catalogue, rng=Rng(1, "t")) is None


def test_the_catalogue_is_sorted_and_carries_its_projection(
    shipped: dict[str, list[tuple]],
) -> None:
    catalogue = roleseq.catalogue(shipped)
    assert catalogue.projection == roleseq.DEFAULT
    assert list(catalogue.symbols) == sorted(catalogue.symbols)
    for symbol in catalogue.symbols:
        sections = catalogue.for_symbol(symbol)
        assert list(sections) == sorted(sections, key=lambda s: (s.heading, s.scope, s.kinds))
    assert catalogue.for_symbol("retail|any:not.a.kind") == ()


# --- sampling ---------------------------------------------------------------


def test_outlines_are_reproducible_from_the_seed(shipped: dict[str, list[tuple]]) -> None:
    model, catalogue = roleseq.learn_roles(shipped), roleseq.catalogue(shipped)
    first = roleseq.outlines(model, catalogue, rng=Rng(8128, "o"), tag="retail", length=4, count=8)
    again = roleseq.outlines(model, catalogue, rng=Rng(8128, "o"), tag="retail", length=4, count=8)
    assert [[s.heading for s in o] for o in first] == [[s.heading for s in o] for o in again]
    assert first


def test_each_outline_has_its_own_stream(shipped: dict[str, list[tuple]]) -> None:
    """Asking for more outlines must not disturb the ones already drawn.

    The reason `outlines` derives per index instead of sharing one stream:
    `synthesise` and `realise` both backtrack, so a shared stream would make
    every outline depend on how hard the previous one was to find.
    """
    model, catalogue = roleseq.learn_roles(shipped), roleseq.catalogue(shipped)

    def draw(count: int) -> list[list[str]]:
        return [
            [s.heading for s in o]
            for o in roleseq.outlines(
                model, catalogue, rng=Rng(8128, "o"), tag="retail", length=4, count=count
            )
        ]

    few, many = draw(3), draw(12)
    assert few == many[: len(few)]


def test_outlines_stay_inside_the_vertical_they_were_asked_for(
    shipped: dict[str, list[tuple]],
) -> None:
    model, catalogue = roleseq.learn_roles(shipped), roleseq.catalogue(shipped)
    for tag in VERTICALS:
        issuable = {
            section.heading
            for symbol in roleseq.symbols_for(model, tag)
            for section in catalogue.for_symbol(symbol)
        }
        for outline in roleseq.outlines(
            model, catalogue, rng=Rng(8128, tag), tag=tag, length=3, count=6
        ):
            assert {section.heading for section in outline} <= issuable


def test_every_sampled_outline_is_one_the_examples_vouch_for(
    shipped: dict[str, list[tuple]],
) -> None:
    model, catalogue = roleseq.learn_roles(shipped), roleseq.catalogue(shipped)
    produced = 0
    for tag in VERTICALS:
        for length in (2, 3, 4, 5):
            for outline in roleseq.outlines(
                model, catalogue, rng=Rng(8128, tag), tag=tag, length=length, count=5
            ):
                produced += 1
                assert len(outline) == length
                assert adjacency.admits(model, roleseq.project(outline, tag=tag))
    assert produced > 10


# --- the enumerator ---------------------------------------------------------


def test_admitted_agrees_with_admits_by_brute_force() -> None:
    """The enumerator is a closure over prefixes; `admits` is a direct check.

    They are two implementations of one definition, so on a model small enough to
    enumerate by hand they must agree exactly — including on the short whole
    examples that are their own window.
    """
    examples = [("a", "b", "c"), ("a", "d"), ("c",), ("d", "b", "c")]
    model = adjacency.learn(examples, order=2)
    found = set(roleseq.admitted(model, max_length=4))
    brute = {
        sequence
        for length in range(1, 5)
        for sequence in itertools.product(model.alphabet, repeat=length)
        if adjacency.admits(model, sequence)
    }
    assert found == brute
    assert ("a", "b", "c") in found


def test_admitted_respects_its_bound(shipped: dict[str, list[tuple]]) -> None:
    model = roleseq.learn_roles(shipped)
    for bound in (1, 3, 6):
        sequences = roleseq.admitted(model, max_length=bound)
        assert all(len(sequence) <= bound for sequence in sequences)
        assert list(sequences) == sorted(sequences)
    assert roleseq.admitted(model, max_length=0) == ()


def test_two_policies_of_one_function_are_one_role(shipped: dict[str, list[tuple]]) -> None:
    """A known limit of the projection, fenced so that fixing it is noticed.

    Every section of every HR policy carries the prefix `policy.hr.`, so leave
    and remote work project to the same symbol at *every* projection this module
    offers, including the full kind tuple. The model will therefore splice a
    leave heading and a remote-work heading into one outline: locally each window
    is real, and a company issues them as two documents.

    That is not fixable here. It needs the policy *area* inside the fact kind —
    `policy.hr.leave.` against `policy.hr.remote_work.` — which is
    `policies.py` and `factkinds.py`, neither of which this lane owns. When
    somebody does it, this test fails, and deleting it is the right response.
    """
    leave, remote = _OUTLINES["leave_policy"], _OUTLINES["remote_work_policy"]
    for projection in ("kinds", "scope+kinds", "kind", "scope+kind"):
        symbols = {
            roleseq.symbol(section, projection=projection)  # type: ignore[arg-type]
            for outline in (leave, remote)
            for section in outline
        }
        assert len(symbols) == 1, f"{projection} now separates leave from remote work"


def test_untag_inverts_the_tag(shipped: dict[str, list[tuple]]) -> None:
    outline = shipped["retail"][0]
    tagged = roleseq.project(outline, tag="retail")
    assert roleseq.untag(tagged) == roleseq.project(outline)
