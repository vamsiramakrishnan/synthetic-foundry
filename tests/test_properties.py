"""The universally-quantified claims, checked mechanically rather than at points.

Almost every rule in this repository is stated with an *any* in it — the parts
sum to the total for **any** allocation, the lint refuses **any** spec citing an
undeclared kind, intersection is associative for **any** three intervals — and
the rest of the suite checks them at hand-picked arguments. That is the right
way to pin behaviour a reader has to understand. It is the wrong way to find the
cases nobody thought of, and the bugs this project has actually hit are all of
that second kind: a double-rounding defect in a physics span, a bit-exact pin
broken by CPython's Neumaier ``sum()``, a last-ulp score difference that could
swap a ranking, a shadowed local that disabled every exclusion rule. Each was
found by accident. Each is what a property test finds on purpose.

So these are the same claims, quantified, with Hypothesis choosing the
arguments. Three defects came out of writing them, and each fix carries the
minimal failing example in the comment beside it:

* ``detail.allocate_scaled`` returned parts that summed exactly as integers and
  *not* as the floats it handed back, once the fixed-point total passed the
  precision a float can carry — surfacing a whole pipeline later as
  ``rows_do_not_sum`` against a rendered document.
* ``probe.Interval.width`` was ``nan`` for ``[∞, ∞]``, a value that compares
  False against everything and therefore *silently disabled* narrowing at that
  node, which is the failure mode the module's own ``__mul__`` comment exists
  to prevent one layer down.
* ``probe.propagate`` ground through ~700,000 revisions on a two-node graph with
  one link, taking eleven seconds inside ``probe accept`` and landing on the
  meaningless domain ``[-∞, -∞]``, because ``_MEANINGFUL`` bounds how *small* a
  narrowing may be and nothing bounded how *many* there are.

Two rules held while writing them. **A property is never weakened to make it
pass** — a property that was edited until it agreed with the code is a
restatement of the code, and tests nothing. And **nothing under ``src/`` gains a
source of randomness**: Hypothesis's own draws are test-only, seeded, and
reproducible from its database, and the database is gitignored so CI derives its
examples rather than replaying a checked-in file.

Runtime is capped deliberately. ``max_examples`` is small where an example is
expensive, and no property here builds a world — a build is seconds, and a
property that can only afford thirty examples is a slow unit test wearing a
property's name. Every claim below is reachable at the unit level.
"""

from __future__ import annotations

import math

import pytest

# Skipped rather than failed when absent: `hypothesis` is in the dev extra and
# not in the runtime dependencies, and a package installed for use rather than
# for development should not report a broken test suite for lacking a test-only
# tool. Every gate that matters runs it — `pip install -e ".[dev]"` is what
# CLAUDE.md's `pytest -q` assumes.
pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, assume, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from worldloom import (  # noqa: E402
    detail,
    dispersion,
    domains,
    doctypes,
    episodes,
    factkinds,
    lob,
    parameters,
    probe,
    process,
    roles,
    similarity,
)
from worldloom.episodes import EpisodeSpec, EventSpec, FactKindSpec, Invariant  # noqa: E402
from worldloom.generators.finance import allocate  # noqa: E402

#: The house profile. `deadline` is per example and is the only thing standing
#: between a slow-convergence bug and a suite that appears to hang — it is what
#: caught `propagate`'s divergent cycle, so it is set rather than disabled.
_FAST = settings(max_examples=400, deadline=1000)

#: For properties whose single example is genuinely expensive (building specs,
#: running a lint that imports the registries). Fewer draws, more room each.
_SLOW = settings(
    max_examples=120,
    deadline=4000,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# 1. Largest-remainder allocation — detail.allocate_scaled
# ---------------------------------------------------------------------------
#
# The newest load-bearing arithmetic in the product, and the one whose failure
# is least visible: a column that does not sum back to its fact produces a
# workbook that renders, opens, and disagrees with the ledger by a cent.

#: Non-negative, because that is the whole domain `allocate` is sound over: a
#: negative weight passes its `pool > 0` guard and then produces a negative
#: part, and `_lognormal_weights` / `_zipf_weights` — the only two callers —
#: cannot emit one. Generating them would be testing a case the type does not
#: admit and the code does not claim.
_weights = st.lists(
    st.floats(min_value=1e-9, max_value=1e9, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=48,
)

#: Bounded so the fixed-point total stays inside the precision a float carries
#: back — the boundary `allocate_scaled` now refuses at, asserted separately
#: below. 10^9 at six places is 10^15 scaled units, just under the frontier.
_totals = st.floats(
    min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False
)
_decimals = st.integers(min_value=0, max_value=6)


@_FAST
@given(_totals, _weights, _decimals)
def test_allocated_parts_sum_to_the_total_in_fixed_point(total, weights, decimals):
    """The claim the validator actually checks, quantified.

    Compared in scaled integers, not floats, because that is `validate`'s own
    comparison (`detail.check`: `sum(round(row * scale)) == round(amount *
    scale)`). Asserting `sum(parts) == total` in floats would be a weaker
    property that the code is not required to satisfy and that no caller wants.
    """
    parts = detail.allocate_scaled(total, weights, decimals=decimals)
    scale = 10**decimals
    assert len(parts) == len(weights)
    assert sum(round(part * scale) for part in parts) == round(total * scale)


@_FAST
@given(_totals, _weights, _decimals)
def test_allocated_parts_are_never_negative(total, weights, decimals):
    """A negative line in a detail table is a refund nobody booked."""
    parts = detail.allocate_scaled(total, weights, decimals=decimals)
    assert all(part >= 0.0 for part in parts)


@_FAST
@given(_totals, _weights, _decimals)
def test_allocation_is_a_function_of_its_arguments(total, weights, decimals):
    """Determinism, stated as the absence of hidden state.

    `allocate_scaled` draws from no `Rng` — the *weights* are the stream's
    contribution and they arrive as an argument — so two calls with equal
    arguments must be equal. This is the property that would fail the moment
    somebody reached for a clock, a `set` iteration, or `hash()`, which is the
    class of change `AGENTS.md` forbids and CI's byte-for-byte replay catches
    only after a corpus has been built.
    """
    first = detail.allocate_scaled(total, weights, decimals=decimals)
    second = detail.allocate_scaled(total, weights, decimals=decimals)
    assert first == second


@_FAST
@given(
    st.integers(min_value=0, max_value=10**12),
    st.lists(
        st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=32,
    ),
)
def test_the_remainder_goes_to_the_largest_remainders_and_nowhere_else(total, weights):
    """The distribution rule, not merely the sum.

    Largest-remainder means three things at once and the sum only pins the
    first: every part is its own floor or one above it, exactly `remainder` of
    them are rounded up, and the ones rounded up are the ones with the largest
    fractional parts (ties to the lowest index). A round-and-hope
    implementation, or one that dumped the whole residual on row 0, would still
    sum to the total and would put the difference in the wrong line.
    """
    assume(sum(weights) > 0)
    parts = allocate(total, weights)
    pool = sum(weights)
    raw = [total * weight / pool for weight in weights]
    floors = [math.floor(value) for value in raw]

    assert [part - floor for part, floor in zip(parts, floors, strict=True)] == [
        0 if part == floor else 1 for part, floor in zip(parts, floors, strict=True)
    ], "every part is its floor or one above it"

    rounded_up = {i for i, (p, f) in enumerate(zip(parts, floors, strict=True)) if p > f}
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    assert rounded_up == set(order[: len(rounded_up)]), (
        "the units go to the largest remainders, ties to the lowest index"
    )


@_FAST
@given(_weights, _decimals)
def test_a_negative_total_is_refused_rather_than_allocated(weights, decimals):
    with pytest.raises(ValueError, match="negative total"):
        detail.allocate_scaled(-1.0, weights, decimals=decimals)


def test_a_total_past_the_float_round_trip_is_refused_not_silently_wrong():
    """The defect this file found, pinned at its minimal example.

    `allocate_scaled` scales to integers, allocates exactly, and divides back —
    and the division is where the exactness could be lost. `42_413_116_570` at
    five places puts one part on `4_142_676_502_186_047` scaled units; that
    part comes back through `part / scale` as a float whose spacing at that
    magnitude is wider than one unit, and `round(value * scale)` — the exact
    inverse `validate` applies — recovers `…048`. The parts summed to the total
    as integers and were one unit over as the figures the rows print.

    It surfaced nowhere near here: the corpus generated clean and failed later
    as `rows_do_not_sum` against a rendered document, phrased as if the rows
    were at fault. So the refusal is at the arithmetic, naming the total.
    """
    with pytest.raises(ValueError, match="precision a float can carry back"):
        detail.allocate_scaled(42_413_116_570.0, [1.0, 42.0], decimals=5)


# ---------------------------------------------------------------------------
# 2. Interval algebra and AC-3 — probe.Interval, probe.propagate
# ---------------------------------------------------------------------------

_bounds = st.one_of(
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.just(math.inf),
    st.just(-math.inf),
    st.just(0.0),
)


@st.composite
def _intervals(draw, *, empty_allowed: bool = True):
    low, high = draw(_bounds), draw(_bounds)
    if not empty_allowed:
        low, high = min(low, high), max(low, high)
    return probe.Interval(low, high)


def _pair(interval):
    """Bounds as a tuple, so two intervals compare by value and not by the
    dataclass's `==` — which agrees here, but would quietly start comparing
    something else if a field were ever added."""
    return (interval.low, interval.high)


@_FAST
@given(_intervals(), _intervals())
def test_meet_is_commutative(a, b):
    assert _pair(a.meet(b)) == _pair(b.meet(a))


@_FAST
@given(_intervals())
def test_meet_is_idempotent(a):
    assert _pair(a.meet(a)) == _pair(a)


@_FAST
@given(_intervals(), _intervals(), _intervals())
def test_meet_is_associative(a, b, c):
    """Associativity is not a formality here.

    `propagate`'s docstring rests the determinism guarantee on the *order*
    intervals are combined in — "interval arithmetic is not associative in
    floating point" is the stated reason its worklist is sorted. That is true
    of the *arithmetic*; `meet` is min and max, which are exact, so the
    intersection specifically must be associative. If it were not, sorting the
    worklist would not be enough to make the result reproducible.
    """
    assert _pair(a.meet(b).meet(c)) == _pair(a.meet(b.meet(c)))


@_FAST
@given(_intervals(empty_allowed=False))
def test_admits_is_reflexive(a):
    """Every interval admits itself.

    The tolerance in `admits` exists to stop a float artefact reading as a
    widened question, and a tolerance that made an interval refuse *itself*
    would refuse the answer that restates the bound it was handed — which is
    the most ordinary answer there is.
    """
    accepted, why = a.admits(a)
    assert accepted, why


@_FAST
@given(_intervals(empty_allowed=False), _intervals(empty_allowed=False))
def test_a_refusal_from_admits_always_says_what_broke(a, b):
    """A rejection a model cannot read is a rejection it cannot act on — the
    argument `admits`' own docstring makes about printing `[0.35, 0.45]` twice."""
    accepted, why = a.admits(b)
    assert accepted or why.strip(), (a, b)


@_FAST
@given(_intervals(empty_allowed=False), _intervals(empty_allowed=False))
def test_interval_arithmetic_never_produces_a_nan_bound(a, b):
    """A nan bound compares False against everything.

    That is worse than an error: it does not raise, it does not print as
    obviously wrong, and it *silently disables* every narrowing decision
    downstream, because `<`, `>` and `<=` are all False against it. `__mul__`
    guards the `0 * inf` case explicitly and returns the whole line; this says
    there is no second route to one.
    """
    for out in (a * b, a / b):
        assert not math.isnan(out.low), (a, b, out)
        assert not math.isnan(out.high), (a, b, out)


@_FAST
@given(_intervals(empty_allowed=False))
def test_width_is_never_nan(a):
    """The defect this file found.

    `[∞, ∞]` is reachable — a `scales` factor big enough to overflow sends
    every corner product to one sign of infinity — and `inf - inf` is `nan`.
    `narrowed_by` then reads `isinf(nan)` as False, takes the subtraction
    branch, and compares `nan > slack`, which is False for every other interval
    there is: the node stops narrowing and nothing says so. Same failure the
    test above refuses for the bounds, arriving through the derived quantity.
    """
    assert not math.isnan(a.width), a
    assert a.width >= 0.0


@_FAST
@given(_intervals(empty_allowed=False))
def test_every_relation_maps_a_real_interval_to_a_real_one(a):
    """Both directions of every relation in the closed set.

    `Relation`'s docstring rests the whole design on invertibility — evidence
    at a leaf must travel back up — so `backward` is as load-bearing as
    `forward` and gets the same guarantee.
    """
    factors = [
        probe.WHOLE,
        probe.Interval(0.0, 0.0),
        probe.Interval(0.0, 2.0),
        probe.Interval(-1.0, 1.0),
        probe.Interval(0.5, 0.5),
        probe.Interval(-math.inf, 1.0),
    ]
    for kind in probe.KINDS:
        for factor in factors if kind == "scales" else [probe.WHOLE]:
            relation = probe.Relation(kind, factor)
            for out in (relation.forward(a), relation.backward(a)):
                assert not math.isnan(out.low), (kind, factor, a, out)
                assert not math.isnan(out.high), (kind, factor, a, out)


# -- the constraint graph ---------------------------------------------------

_graph_bounds = st.floats(
    min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False
)


@st.composite
def _graph_interval(draw):
    low = draw(st.one_of(st.just(-math.inf), _graph_bounds))
    high = draw(st.one_of(st.just(math.inf), _graph_bounds))
    return probe.Interval(min(low, high), max(low, high))


@st.composite
def _relations(draw):
    kind = draw(st.sampled_from(probe.KINDS))
    if kind != "scales":
        return probe.Relation(kind)
    # Factors a model would plausibly argue for, including the ones just either
    # side of 1 — "this is about a tenth of a per cent more than that" is an
    # ordinary claim, and it is the one that made propagation diverge.
    low = draw(st.sampled_from([0.0, 0.1, 0.5, 0.9, 0.999, 1.0, 1.001, 1.5]))
    high = low + draw(st.sampled_from([0.0, 0.001, 0.1, 1.0]))
    return probe.Relation("scales", probe.Interval(low, high))


@st.composite
def _graphs(draw):
    """Small graphs, because the property is termination and not scale.

    Every question after the root takes an existing one as parent, so the tree
    is well-formed by construction; the cycles — which is where propagation can
    fail to settle — come from the links, exactly as they do in a real probe.
    """
    count = draw(st.integers(min_value=2, max_value=6))
    keys = [f"q{index}" for index in range(count)]
    questions = {}
    for index, key in enumerate(keys):
        parent = draw(st.sampled_from(keys[:index])) if index else None
        questions[key] = probe.Question(
            key=key,
            asks="what?",
            unit="unit",
            domain=draw(_graph_interval()),
            depth=index,
            parent=parent,
            via=draw(_relations()) if parent else probe.Relation("free"),
        )
    links = []
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        subject = draw(st.sampled_from(keys))
        object_ = draw(st.sampled_from(keys))
        if subject != object_:
            links.append(
                probe.Link(subject=subject, object=object_, via=draw(_relations()))
            )
    return probe.Graph("a generated premise", questions, links=tuple(links))


@settings(max_examples=300, deadline=1000)
@given(_graphs())
def test_propagate_terminates_on_any_graph(graph):
    """The defect this file found, and the reason `deadline` is set.

    Hypothesis's deadline is checked after the call returns, so it cannot
    interrupt a true infinite loop — but slow convergence is what actually
    happens here, and a deadline is exactly the instrument for it. It found a
    graph taking 18.5 seconds, which shrank to two nodes and one link (pinned
    in the test below). One second is three orders of magnitude above what any
    settling graph needs.
    """
    result = probe.propagate(graph)
    assert set(result.domains) == set(graph.questions)


@settings(max_examples=300, deadline=1000)
@given(_graphs())
def test_propagate_never_leaves_a_nan_bound_in_a_domain(graph):
    for key, domain in probe.propagate(graph).domains.items():
        assert not math.isnan(domain.low), (key, domain)
        assert not math.isnan(domain.high), (key, domain)


@settings(max_examples=200, deadline=2000)
@given(_graphs())
def test_propagate_is_deterministic(graph):
    """Two runs over one graph narrow identically.

    The claim `propagate`'s docstring makes about its sorted worklist, checked
    rather than argued. The revision budget does not weaken it: the budget cuts
    a *prefix* of a deterministic sequence, so a capped run is as reproducible
    as an uncapped one.
    """
    first = probe.propagate(graph)
    second = probe.propagate(graph)
    assert {k: _pair(v) for k, v in first.domains.items()} == {
        k: _pair(v) for k, v in second.domains.items()
    }
    assert [str(c) for c in first.contradictions] == [
        str(c) for c in second.contradictions
    ]


@settings(max_examples=200, deadline=1000)
@given(_graphs())
def test_propagation_only_ever_narrows(graph):
    """Arc consistency removes possibilities; it never adds one.

    `Question.domain`'s own docstring — "narrows as answers arrive; never
    widens" — is a claim about the whole mechanism, and this is where the
    mechanism could break it. A relation whose inverse was slightly wrong would
    show up here as a domain that grew, and nowhere else until a model was
    handed bounds looser than the ones its earlier answers established.
    """
    for key, domain in probe.propagate(graph).domains.items():
        declared = graph.questions[key].domain
        if domain.empty or declared.empty:
            continue
        assert declared.low <= domain.low and domain.high <= declared.high, (
            key,
            declared,
            domain,
        )


def test_a_divergent_cycle_settles_instead_of_grinding_to_infinity():
    """The minimal example behind `_REVISION_BUDGET`, pinned.

    `b` is at most `a`; `a` is `b` scaled by `[1.001, 1.002]`. Each lap walks
    the shared upper bound a further tenth of a per cent away from zero — a
    narrowing every time, and one that clears `_MEANINGFUL` easily, so the
    floor never fires. Uncapped it ran about seven hundred thousand revisions,
    took eleven seconds, and ended on `[-∞, -∞]`: not empty by `Interval.empty`
    (which asks `low > high`), so no contradiction was reported either. Two
    nodes. Inside `probe accept`, which runs this on every answer.

    What the budget must preserve is soundness in the one direction that
    matters: stopping early leaves domains *wider*, so it can only fail to
    refuse — never refuse an answer that holds. Asserted here as the finite
    bound the model's own declared domain still contains.
    """
    questions = {
        "a": probe.Question(
            key="a", asks="?", unit="u", domain=probe.Interval(-math.inf, -1.0), depth=0
        ),
        "b": probe.Question(
            key="b",
            asks="?",
            unit="u",
            domain=probe.WHOLE,
            depth=1,
            parent="a",
            via=probe.Relation("at_most"),
        ),
    }
    graph = probe.Graph(
        "a divergent cycle",
        questions,
        links=(
            probe.Link(
                subject="b",
                object="a",
                via=probe.Relation("scales", probe.Interval(1.001, 1.002)),
            ),
        ),
    )
    result = probe.propagate(graph)
    for key in ("a", "b"):
        domain = result.domains[key]
        assert not math.isinf(domain.high), (key, domain)
        assert domain.high <= questions[key].domain.high, "still a narrowing"


# ---------------------------------------------------------------------------
# 3. Per-unit role keys — roles.unit_role_key / roles.parse_unit_role
# ---------------------------------------------------------------------------
#
# These two functions are the whole of a key format that used to live in ~10
# call sites as f-strings and `role[:-3]` slices. The bug that motivated them —
# a renamed suffix detaching everybody in a unit from their business unit — is
# a round-trip failure, so a round-trip is what to quantify.

#: Unit keys as the generators actually mint them, plus the shapes that could
#: confuse a suffix parser: a key *containing* a suffix (`food_mdx`), a key
#: *ending* in one (`food_md`), and a key that is a suffix with something in
#: front of it. The alphabet includes `_`, so the strategy reaches all three
#: without anybody having to enumerate them.
_unit_keys = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=24
)
_suffixes = st.sampled_from(roles.UNIT_ROLE_SUFFIXES)


@_FAST
@given(_unit_keys, _suffixes)
def test_a_minted_unit_role_key_parses_back_to_what_minted_it(unit_key, suffix):
    key = roles.unit_role_key(unit_key, suffix)
    assert roles.parse_unit_role(key) == (unit_key, suffix)


@_FAST
@given(_unit_keys, _suffixes, st.lists(_suffixes, min_size=1, unique=True))
def test_the_round_trip_holds_for_any_engines_own_suffix_set(unit_key, suffix, subset):
    """Every engine passes its own suffixes — banking and insurance mint only
    `_md`, retail all three — so the round trip has to hold per set, not only
    against the union. A suffix outside the set given must not resolve, which
    is the point of passing one: a banking role ending in `_bp` is not a unit
    post the banking generator ever minted."""
    key = roles.unit_role_key(unit_key, suffix)
    parsed = roles.parse_unit_role(key, subset)
    if suffix in subset:
        assert parsed == (unit_key, suffix)
    else:
        # A key minted with a suffix the engine was not given may still parse
        # under one it *was* — `unit_role_key("gm_md", "_bp")` is `gm_md_bp`,
        # which an engine holding only `("_md",)` reads as nothing, but a unit
        # key can itself end in another engine's suffix. So the guarantee is
        # the narrow one, and it is the one that matters: the parser never
        # claims a suffix that is not in the set it was handed.
        assert parsed is None or parsed[1] in subset


@_FAST
@given(_unit_keys)
def test_a_key_that_is_not_a_unit_role_parses_to_none(key):
    """The negative half. Without it the property above is satisfied by a parser
    that returns `(key, suffix)` for everything."""
    assume(
        not any(
            key.endswith(suffix) and len(key) > len(suffix)
            for suffix in roles.UNIT_ROLE_SUFFIXES
        )
    )
    assert roles.parse_unit_role(key) is None


@_FAST
@given(_suffixes)
def test_a_bare_suffix_is_not_a_unit_role(suffix):
    """`_md` on its own names no unit, and the guard that says so is a `>`
    rather than a `>=` — one character apart from returning `("", "_md")` and
    attaching a person to a business unit whose key is the empty string."""
    assert roles.parse_unit_role(suffix) is None


def test_no_registered_suffix_set_can_shadow_its_own_members():
    """Why the round trip above holds at all, stated as the condition for it.

    `parse_unit_role` takes the first match in the order given, so the round
    trip survives only while no suffix is a suffix of another: register `_bp`
    and `_sub_bp` together and `gm_sub_bp` reads as unit `gm_sub`, silently,
    for whichever of the two is checked first. Checked over the registry rather
    than asserted about today's three, so the day a fourth engine registers a
    colliding pair this fails instead of the corpus doing.
    """
    from worldloom import domains

    sets = [roles.UNIT_ROLE_SUFFIXES] + [
        tuple(getattr(domains.by_name(name), "unit_role_suffixes", ()))
        for name in domains.names()
    ]
    for suffixes in sets:
        for suffix in suffixes:
            for other in suffixes:
                assert other == suffix or not suffix.endswith(other), (
                    f"{suffix!r} ends with {other!r}; whichever is checked first"
                    " swallows keys belonging to the other"
                )


# ---------------------------------------------------------------------------
# 4. The cascade lints
# ---------------------------------------------------------------------------
#
# Every lint in the cascade has the same contract — a list of strings naming
# divergences, nothing raises — and the same three obligations follow from it:
# an unregistered fact kind is always refused, a valid proposal never is, and
# every finding a model is handed is something it can act on.

def _narrated_kinds() -> frozenset[str]:
    """The prefixes `doctypes.lint` reads — what some declared outline is
    actually written about, which is narrower than the fact-kind registry."""
    from worldloom import documents

    return frozenset(documents.narrated_kinds())


def _all_known_prefixes() -> frozenset[str]:
    """Both vocabularies at once, for the *unregistered* filter only: a name
    has to miss every registry for "always refused" to hold across every lint
    below."""
    return frozenset(factkinds.names()) | _narrated_kinds()


#: A name no registry holds, and provably so rather than by hope. `factkinds`
#: resolves on a dot boundary and `doctypes` matches prefixes in *both*
#: directions (`kind.startswith(known) or known.startswith(kind)`), so a
#: one-letter draw like "f" would legitimately match `financial.revenue.actual`
#: and the "always refused" property would then be false for a reason that has
#: nothing to do with the rule. Filtering here keeps every property below about
#: the lint and not about the alphabet.
_unregistered_kinds = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz.", min_size=4, max_size=24
).filter(
    lambda name: name
    and not name.startswith(".")
    and not name.endswith(".")
    and ".." not in name
    and not factkinds.resolvable(name)
    and not any(
        name.startswith(known) or known.startswith(name)
        for known in _all_known_prefixes()
    )
)


def _findings_are_actionable(findings) -> None:
    """The obligation every one of these lints carries.

    A finding is what a model reads instead of the source, so an empty string,
    a bare `None`, or a repr of an exception object is a refusal it cannot act
    on — and the cascade's whole design is that a refusal teaches. Checked on
    every property below rather than once, because each lint builds its own.
    """
    assert isinstance(findings, list)
    for finding in findings:
        assert isinstance(finding, str), finding
        assert finding.strip(), "a blank finding refuses without saying why"


# -- lob.lint_responsibilities ---------------------------------------------


@_SLOW
@given(_unregistered_kinds)
def test_a_responsibility_naming_an_unregistered_kind_is_always_refused(kind):
    """The accountability edge that can never fire.

    Nothing mints the kind, so the person the edge makes answerable is
    answerable for nothing, and the corpus reports the edge as though it were
    load-bearing. Quantified over the name because the rule is about the
    registry and not about any particular typo.
    """
    findings = lob.lint_responsibilities(
        [lob.Responsibility(role_key="ceo", fact_kinds=[kind])], roles=["ceo"]
    )
    _findings_are_actionable(findings)
    assert any(kind in finding for finding in findings), findings


@_SLOW
@given(st.sampled_from(sorted(factkinds.names())))
def test_a_responsibility_naming_a_registered_kind_is_never_refused(kind):
    """The other half, and the one that catches an over-eager rule. A lint that
    refused everything would satisfy the property above."""
    findings = lob.lint_responsibilities(
        [lob.Responsibility(role_key="ceo", fact_kinds=[kind])], roles=["ceo"]
    )
    assert findings == [], findings


@_SLOW
@given(st.sampled_from(sorted(factkinds.names())))
def test_a_prefix_of_a_registered_kind_resolves_only_at_a_dot_boundary(kind):
    """Prefix semantics are the registry's, and the boundary is a dot.

    "The controller answers for `financial.revenue`" is one honest edge over
    `.actual`, `.budget` and `.variance`, so the family name has to resolve.
    `financial.rev` is a typo, so the truncation must not — a rule that
    accepted it would turn every misspelling into a silent no-op edge that
    reads, in `worldloom pack targets`, exactly like a real one.

    Both directions, over every kind the registry holds, because the whole
    point of a prefix rule is that it is generous, and a generous rule is the
    kind that quietly stops discriminating.
    """
    head, dot, _ = kind.rpartition(".")
    if dot:
        assert factkinds.resolvable(head), f"{head!r} is a family, not a typo"
    assert not factkinds.resolvable(kind[:-1]), (
        f"{kind[:-1]!r} is {kind!r} with a character missing — a typo, not a family"
    )


# -- lob.lint_roles ---------------------------------------------------------


@st.composite
def _role_trees(draw, *, valid: bool):
    """A reporting tree rooted at `ceo`, or one deliberately broken."""
    size = draw(st.integers(min_value=1, max_value=6))
    keys = ["ceo"] + [f"role_{index}" for index in range(size)]
    specs = [
        lob.RoleSpec(key="ceo", title="Chief Executive", function="Executive")
    ]
    for index, key in enumerate(keys[1:]):
        parent = draw(st.sampled_from(keys[: index + 1]))
        specs.append(
            lob.RoleSpec(
                key=key,
                title=f"Head of {index}",
                function="Finance",
                reports_to=parent if valid else key,  # self-report is the cycle
            )
        )
    return specs


@_SLOW
@given(_role_trees(valid=True))
def test_a_well_formed_reporting_tree_is_never_refused(specs):
    findings = lob.lint_roles(specs)
    _findings_are_actionable(findings)
    assert findings == [], findings


@_SLOW
@given(_role_trees(valid=False))
def test_a_reporting_cycle_is_always_refused(specs):
    """A role reporting to itself, at any position in any tree.

    `validate` treats a cycling reporting line as a defect rather than a
    warning, and this lint is the layer that stops one being authored — so the
    claim is about *every* such tree, not the one in `test_process.py`.
    """
    assume(len(specs) > 1)
    findings = lob.lint_roles(specs)
    _findings_are_actionable(findings)
    assert any("cycle" in finding for finding in findings), findings


# -- process.lint_steps / episodes.lint -------------------------------------

_KNOWN_KIND = st.sampled_from(sorted(factkinds.names()))


def _session() -> process.Session:
    return process.open(
        process.ProcessSeed(
            name="GeneratedProcess",
            purpose="A process generated to be linted.",
            engine="retail",
            lob="finance",
            period="month",
        )
    )


def _kind_spec(kind: str) -> FactKindSpec:
    """A declaration whose invariants are *derived* from the registry.

    The same fill `process._filled` performs on the way into a provisional
    spec, through the same public `factkinds.parse_invariant`, and it carries
    the **operands** rather than only the head — writing this helper without
    them was the first thing this file got wrong, and the lint caught it:
    `reconciles-against` and `sums-to` are meaningless without the kinds they
    reconcile against, so a fill that dropped them produced a spec the grammar
    rightly refused. The registry is the one source that documents what the
    validators actually enforce; restating it by hand here would be the drift
    `_filled` exists to prevent, one file over.
    """
    registered = factkinds.get(kind)
    invariants = [
        Invariant(kind=head, operands=list(operands))  # type: ignore[arg-type]
        for head, operands in (
            factkinds.parse_invariant(inv)
            for inv in (registered.invariants if registered else ())
        )
    ]
    return FactKindSpec(
        kind=kind,
        value_type="text",
        text="Recorded for {period}.",
        invariants=invariants or [Invariant(kind="holds-at")],
    )


@_SLOW
@given(_unregistered_kinds)
def test_a_step_minting_an_undeclared_kind_is_always_refused(kind):
    """The cascade's own rule, before the grammar's.

    A step may mint whatever the answer *declares*; what it may never do is
    mint a name the same answer says nothing about. Refused with the kind named
    so the model can see which of its steps and which of its declarations
    disagree.
    """
    findings = process.lint_steps(
        _session(),
        [
            EventSpec(
                kind="generated.step",
                when="start",
                summary="A step for {period}.",
                fact_keys=[kind],
            )
        ],
        [],
    )
    _findings_are_actionable(findings)
    assert any(kind in finding for finding in findings), findings


@_SLOW
@given(_unregistered_kinds)
def test_an_unknown_kind_without_invariants_is_always_refused(kind):
    """A kind nothing validates may not enter a spec.

    The kind is declared this time, so the rule above is satisfied — what is
    refused is that neither the registry nor the answer says what the kind has
    to satisfy, which would put a fact in the corpus that no check ever reads.
    """
    findings = process.lint_steps(
        _session(),
        [
            EventSpec(
                kind="generated.step",
                when="start",
                summary="A step for {period}.",
                fact_keys=[kind],
            )
        ],
        [FactKindSpec(kind=kind, value_type="text", text="Recorded.")],
    )
    _findings_are_actionable(findings)
    assert any("neither registry-known nor declared" in f for f in findings), findings


@_SLOW
@given(_KNOWN_KIND)
def test_a_step_minting_a_registered_kind_is_never_refused(kind):
    """The valid case, over every kind the registry holds — 97 of them, so this
    is the property that would have caught a rule keyed to one engine's naming."""
    findings = process.lint_steps(
        _session(),
        [
            EventSpec(
                kind="generated.step",
                when="start",
                summary="A step for {period}.",
                fact_keys=[kind],
            )
        ],
        [_kind_spec(kind)],
    )
    assert findings == [], (kind, findings)


@_SLOW
@given(_KNOWN_KIND)
def test_a_spec_claiming_an_invariant_the_registry_does_not_hold_is_refused(kind):
    """The spec and the registry may not disagree about what a kind means.

    Both derive checks a validator runs, and only one of them can be right — so
    the divergence is refused where it is authored rather than resolved by
    whichever happens to run first.
    """
    registered = factkinds.get(kind)
    assume(registered is not None)
    heads = {factkinds.parse_invariant(inv)[0] for inv in registered.invariants}
    invented = next(
        head
        for head in ("standing", "never-superseded", "supersedes-prior", "holds-at")
        if head not in heads
    )
    spec = EpisodeSpec(
        name="GeneratedProcess",
        domain="retail",
        period="month",
        fact_kinds=[
            _kind_spec(kind).model_copy(
                update={
                    "invariants": [
                        *_kind_spec(kind).invariants,
                        Invariant(kind=invented),  # type: ignore[arg-type]
                    ]
                }
            )
        ],
        events=[
            EventSpec(
                kind="generated.step",
                when="start",
                summary="A step for {period}.",
                fact_keys=[kind],
            )
        ],
    )
    findings = episodes.lint([spec])
    _findings_are_actionable(findings)
    assert any("registry does not hold" in finding for finding in findings), findings


@_SLOW
@given(_KNOWN_KIND, st.sampled_from(["month", "quarter", "year"]))
def test_a_registry_derived_episode_spec_is_never_refused(kind, period):
    spec = EpisodeSpec(
        name="GeneratedProcess",
        domain="retail",
        period=period,  # type: ignore[arg-type]
        fact_kinds=[_kind_spec(kind)],
        events=[
            EventSpec(
                kind="generated.step",
                when="start",
                summary="A step for {period}.",
                fact_keys=[kind],
            )
        ],
    )
    findings = episodes.lint([spec])
    assert findings == [], (kind, findings)


#: `RoleSlotSpec.slot` is `^[a-z][a-z0-9_]*$`, and drawing from the pattern
#: rather than a loose alphabet keeps this a property about the *lint* — a
#: string the model itself rejects tests pydantic, not `lint_slots`. A small
#: pool, because duplicates are the interesting case and a wide alphabet would
#: draw them once in a thousand.
_slot_names = st.sampled_from(["preparer", "reviewer", "approver", "challenger"])


@_SLOW
@given(st.lists(_slot_names, min_size=1, max_size=6))
def test_a_duplicated_role_slot_is_always_refused(slots):
    """Declaration order *is* the ordering, so one seat cannot hold two places
    in it. Stated over any slot vocabulary, because the vocabulary is the
    proposal's own and deliberately not a fixed list."""
    specs = [episodes.RoleSlotSpec(slot=slot, purpose="does the thing") for slot in slots]
    findings = process.lint_slots(specs)
    _findings_are_actionable(findings)
    if len(set(slots)) == len(slots):
        assert findings == [], findings
    else:
        assert any("duplicates" in finding for finding in findings), findings


# -- doctypes.lint ----------------------------------------------------------


def _document_type(kinds: list[str], **overrides) -> doctypes.DocumentType:
    """A type that is well-formed in every respect except the one under test.

    Modelled on `examples/artifact-types/franchise-network.json` — a type whose
    only defect is the generated one, so a finding can be attributed to the
    rule being quantified rather than to the fixture.
    """
    payload = {
        "key": "generated_statement",
        "authority": "approved_report",
        "lifecycle": "published",
        "sections": [
            {
                "heading": "Position",
                "kinds": kinds,
                "scope": "any",
                "purpose": "State the position the facts establish.",
            }
        ],
        "word": True,
        "filing": {
            "author_role": "controller",
            "fallback_role": "cfo",
            "domain": "finance",
            "audience": "all_staff",
            "size": "medium",
            "facts": ["headline"],
            "rationale": "A generated type, filed so the lint has something to read.",
        },
    }
    payload.update(overrides)
    return doctypes.DocumentType.model_validate(payload)


@_SLOW
@given(_unregistered_kinds)
def test_a_section_about_facts_nothing_produces_is_always_refused(kind):
    """The failure that does not raise.

    A section whose prefixes match no fact is dropped rather than left empty,
    so the type compiles, renders to Word, reaches the manifest, and comes back
    from retrieval as an empty answer. Nothing fails — which is exactly why the
    lint has to be the thing that catches it.
    """
    findings = doctypes.lint([_document_type([kind])])
    _findings_are_actionable(findings)
    assert any(repr(kind) in finding for finding in findings), findings


@_SLOW
@given(st.sampled_from(sorted(_narrated_kinds())))
def test_a_section_about_a_narrated_kind_is_not_refused_for_its_kinds(kind):
    """The other half, over the vocabulary this lint actually reads.

    `doctypes.lint` checks against `documents.narrated_kinds()` and not the
    fact-kind registry, and the two are not the same set — `capital.affected_book`
    is registered and is narrated by no declared outline, so a type citing it
    is *correctly* refused. Quantifying over the wrong vocabulary is how a
    property test ends up asserting the code is broken; the fix is to name the
    set the rule is about, which is this one.

    Other findings are allowed — a generated type may trip the outline or
    filing rules — but never the unknown-kind one, which is the claim.
    """
    findings = doctypes.lint([_document_type([kind])])
    _findings_are_actionable(findings)
    assert not any("is written about anything" in finding for finding in findings), (
        findings
    )


@_SLOW
@given(st.sampled_from(sorted(_narrated_kinds())))
def test_a_type_with_no_filing_is_always_reported_as_inert(kind):
    """Declared, renderable, and planned by nothing — the
    carried-and-cited-and-nothing-happens failure, one layer up from the one
    `packs.lint` catches."""
    findings = doctypes.lint([_document_type([kind], filing=None)])
    _findings_are_actionable(findings)
    assert any("declares no `filing`" in finding for finding in findings), findings


# ---------------------------------------------------------------------------
# 5. Span round-trip, shingle symmetry, prefix-stable dispersion
# ---------------------------------------------------------------------------


@st.composite
def _spans(draw):
    low = draw(
        st.one_of(
            st.integers(min_value=-10**6, max_value=10**6),
            st.floats(
                min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
            ),
        )
    )
    high = draw(
        st.one_of(
            st.integers(min_value=-10**6, max_value=10**6),
            st.floats(
                min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
            ),
        )
    )
    return parameters.Span(
        min(low, high),
        max(low, high),
        about=draw(st.text(max_size=20)),
        source=draw(st.text(max_size=20)),
    )


@_FAST
@given(_spans())
def test_a_span_survives_the_recipe_round_trip_unchanged(span):
    """`as_dict` is what a recipe stores and `overrides_from` is what reads it
    back, and the round trip is where the int/float asymmetry bit: `Span(10, 34)`
    recorded `34`, the rebuild recorded `34.0`, and a mosaic world stopped
    replaying byte-for-byte from its own recipe. The `__post_init__` coercion
    is the fix; this is the claim it was made to satisfy, over any bounds and
    over both types.
    """
    recovered = parameters.overrides_from({"p": span.as_dict()})["p"]
    assert (recovered.low, recovered.high) == (span.low, span.high)
    assert isinstance(recovered.low, float) and isinstance(recovered.high, float)
    assert recovered.as_dict() == span.as_dict(), "and the second trip is a fixed point"


@_FAST
@given(
    st.integers(min_value=-10**6, max_value=10**6),
    st.integers(min_value=-10**6, max_value=10**6),
)
def test_an_integer_span_records_and_rebuilds_identically(low, high):
    """The exact shape that broke: bounds written as Python ints."""
    span = parameters.Span(min(low, high), max(low, high), "integer")
    assert span.as_dict()["low"] == float(min(low, high))
    recovered = parameters.overrides_from({"p": span.as_dict()})["p"]
    assert recovered.as_dict()["low"] == span.as_dict()["low"]
    assert recovered.as_dict()["high"] == span.as_dict()["high"]


_words = st.lists(
    st.text(alphabet="abcdefg", min_size=1, max_size=4), min_size=0, max_size=30
)


@_FAST
@given(_words, _words, st.integers(min_value=1, max_value=5))
def test_jaccard_over_shingles_is_symmetric(left, right, size):
    """Near-duplication is a relation between two documents and not a property
    of one, so the measure has to agree with itself whichever way round the
    join reads it — the near-duplicate join emits `(i, j)` with `i < j` and
    would otherwise report a different set depending on input order."""
    a = similarity.shingles(left, size)
    b = similarity.shingles(right, size)
    assert similarity.jaccard(a, b) == similarity.jaccard(b, a)


@_FAST
@given(_words, st.integers(min_value=1, max_value=5))
def test_shingling_covers_the_text_and_nothing_else(words, size):
    """What a shingle set is, quantified: every window of *size* consecutive
    tokens, once each, and no window that is not in the text.

    The two ends are where an off-by-one lives. Dropping the last window makes
    two documents differing only in their final sentence look identical; a
    window past the end would mint a shingle out of tokens nobody wrote. The
    short-input branch is its own case — a text shorter than the window has one
    shingle, which is the whole text — and it is asserted rather than skipped
    because that branch decides what happens to every one-line document.
    """
    shingled = similarity.shingles(words, size)
    if not words:
        assert shingled == frozenset()
    elif len(words) < size:
        assert shingled == frozenset({tuple(words)})
    else:
        assert shingled == frozenset(
            tuple(words[index : index + size])
            for index in range(len(words) - size + 1)
        )
        assert all(len(shingle) == size for shingle in shingled)
    assert similarity.jaccard(shingled, shingled) == (1.0 if shingled else 0.0)


@st.composite
def _points_and_count(draw):
    """*count* drawn after the points, so it is always selectable.

    A separate `integers()` plus an `assume` would throw most draws away and
    spend the budget on the filter rather than on the property.
    """
    points = draw(
        st.lists(
            st.tuples(
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            ),
            min_size=1,
            max_size=20,
        )
    )
    return points, draw(st.integers(min_value=0, max_value=len(points)))


@_FAST
@given(_points_and_count())
def test_farthest_first_is_prefix_stable(points_and_count):
    """A mosaic of three worlds is the first three of a mosaic of five.

    `AGENTS.md` promises exactly this — "a smaller mosaic is a prefix of a
    larger one" — and it is a property of the *traversal*, not of the seed: a
    greedy max-min selection extends its own answer rather than recomputing it.
    A tie broken by set iteration order, or a first pick chosen by anything but
    index 0, would break it while every existing example still passed.
    """
    points, count = points_and_count
    whole = dispersion.farthest_first(points, dispersion.manhattan, count)
    for prefix in range(count + 1):
        assert dispersion.farthest_first(points, dispersion.manhattan, prefix) == (
            whole[:prefix]
        )


@_FAST
@given(st.integers(min_value=1, max_value=8), st.integers(min_value=0, max_value=60))
def test_halton_points_are_a_prefix_of_a_longer_sequence(dimensions, count):
    """The same claim one layer down, where the mosaic's coverage comes from."""
    longer = dispersion.halton(dimensions, count + 7)
    assert dispersion.halton(dimensions, count) == longer[:count]
    for point in longer:
        assert len(point) == dimensions
        assert all(0.0 <= coordinate < 1.0 for coordinate in point)


# The ported block's own two names, kept as that suite defined them rather than
# remapped onto `_FAST`/`_SLOW` above: `derandomize=True` and `database=None`
# are a deliberate choice there (CI derives the same examples every run), and
# silently re-pointing them at settings with different semantics would make the
# ported properties test something other than what they were written to test.
PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    database=None,
    derandomize=True,
)

IDENTIFIER_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_"
IDENTIFIERS = st.text(
    alphabet=IDENTIFIER_ALPHABET,
    min_size=1,
    max_size=20,
).filter(lambda value: value[0].isalpha())


# ---------------------------------------------------------------------------
# Ported from the parallel suite that landed on `main` (PR #6)
#
# Two independent efforts wrote property tests for this repository in the same
# week and, between them, found the same calendar defect in
# `generators/regulatory.py`. Where the two suites overlapped the properties
# agreed; these three are the ones only that suite had, kept verbatim rather
# than paraphrased so the union is auditable against either parent.
#
# `finite_intervals` is its strategy, and the reason the enclosure law below
# can be stated at all: over infinities a corner product can be `nan`, which
# `Interval.__mul__` deliberately widens to WHOLE rather than propagating —
# so the exact min/max claim holds on finite inputs and the NaN case is the
# separate property above.
# ---------------------------------------------------------------------------

@st.composite
def finite_intervals(draw: st.DrawFn) -> probe.Interval:
    left, right = draw(st.tuples(
        st.floats(
            min_value=-1e100,
            max_value=1e100,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        ),
        st.floats(
            min_value=-1e100,
            max_value=1e100,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        ),
    ))
    return probe.Interval(min(left, right), max(left, right))

@PROPERTY_SETTINGS
@given(finite_intervals(), finite_intervals())
def test_interval_product_encloses_every_extreme_corner(
    left: probe.Interval,
    right: probe.Interval,
) -> None:
    product = left * right
    corners = (
        left.low * right.low,
        left.low * right.high,
        left.high * right.low,
        left.high * right.high,
    )

    assert product == right * left
    assert product.low == min(corners)
    assert product.high == max(corners)
    assert all(product.low <= corner <= product.high for corner in corners)

@PROPERTY_SETTINGS
@given(
    engine=st.sampled_from(domains.names()),
    owning_lob=st.sampled_from(sorted(lob.publish())),
)
def test_process_seed_lint_accepts_registered_engines_and_lobs(
    engine: str,
    owning_lob: str,
) -> None:
    seed = process.ProcessSeed(
        name="PropertyProcess",
        purpose="Exercise the process cascade.",
        engine=engine,
        lob=owning_lob,
    )

    assert process.lint_seed(seed) == []

@PROPERTY_SETTINGS
@given(engine_tail=IDENTIFIERS, lob_tail=IDENTIFIERS)
def test_process_seed_lint_refuses_unknown_engines_and_lobs(
    engine_tail: str,
    lob_tail: str,
) -> None:
    engine = f"property_unknown_{engine_tail}"
    owning_lob = f"property_unknown_{lob_tail}"
    seed = process.ProcessSeed(
        name="PropertyProcess",
        purpose="Exercise the process cascade.",
        engine=engine,
        lob=owning_lob,
    )

    findings = process.lint_seed(seed)

    assert any(engine in finding and "not a registered domain" in finding for finding in findings)
    assert any(owning_lob in finding and "no LOB named" in finding for finding in findings)
