"""Universal checks for the small primitives that carry grammar invariants.

These are deliberately bounded properties, not a second exhaustive suite.  The
inputs include uneven magnitudes, zero weights, interval sign changes, suffix
lookalikes, and arbitrary declaration order while keeping the CI budget fixed.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import example, given, settings, strategies as st

import worldloom  # noqa: F401 -- importing the package populates its registries
from worldloom import detail, domains, lob, process, roles
from worldloom.episodes import EventSpec, FactKindSpec, Invariant, RoleSlotSpec
from worldloom.probe import Interval


PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    database=None,
    derandomize=True,
)


@st.composite
def allocations(draw: st.DrawFn) -> tuple[float, list[float], int]:
    """A valid allocation with both tiny and dominant finite weights."""
    count = draw(st.integers(min_value=1, max_value=128))
    weights = draw(st.lists(
        st.floats(
            min_value=0.0,
            max_value=1e12,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        ),
        min_size=count,
        max_size=count,
    ))
    if not any(weights):
        weights[draw(st.integers(min_value=0, max_value=count - 1))] = 1.0
    total = draw(st.floats(
        min_value=0.0,
        max_value=1e9,
        allow_nan=False,
        allow_infinity=False,
        width=64,
    ))
    decimals = draw(st.integers(min_value=0, max_value=4))
    return total, weights, decimals


@PROPERTY_SETTINGS
@given(allocations())
def test_allocate_scaled_is_exact_for_any_nonnegative_total_and_weights(
    case: tuple[float, list[float], int],
) -> None:
    total, weights, decimals = case
    scale = 10 ** decimals

    parts = detail.allocate_scaled(total, weights, decimals=decimals)

    assert len(parts) == len(weights)
    assert all(math.isfinite(part) and part >= 0.0 for part in parts)
    assert sum(round(part * scale) for part in parts) == round(total * scale)


@PROPERTY_SETTINGS
@example(total_units=10, weights=[1, 1, 4], decimals=0)
@given(
    total_units=st.integers(min_value=0, max_value=1_000_000),
    weights=st.lists(
        st.integers(min_value=0, max_value=1_000_000),
        min_size=1,
        max_size=64,
    ).filter(any),
    decimals=st.integers(min_value=0, max_value=4),
)
def test_allocate_scaled_matches_exact_largest_remainder(
    total_units: int,
    weights: list[int],
    decimals: int,
) -> None:
    """The exact apportionment, including mathematical ties by row index.

    The oracle uses integer ratios, so a floating-point ranking swap cannot
    agree with it merely because both paths rounded the same way.
    """
    scale = 10 ** decimals
    actual = [
        round(part * scale)
        for part in detail.allocate_scaled(total_units / scale, weights, decimals=decimals)
    ]

    pool = sum(weights)
    numerators = [total_units * weight for weight in weights]
    expected = [numerator // pool for numerator in numerators]
    remainder = total_units - sum(expected)
    order = sorted(
        range(len(weights)),
        key=lambda index: (-(numerators[index] % pool), index),
    )
    for index in order[:remainder]:
        expected[index] += 1

    assert actual == expected


@st.composite
def finite_intervals(draw: st.DrawFn) -> Interval:
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
    return Interval(min(left, right), max(left, right))


@PROPERTY_SETTINGS
@given(finite_intervals(), finite_intervals())
def test_interval_meet_is_commutative_and_never_widens(
    left: Interval,
    right: Interval,
) -> None:
    met = left.meet(right)

    assert met == right.meet(left)
    assert met.low == max(left.low, right.low)
    assert met.high == min(left.high, right.high)
    if not met.empty:
        assert left.contains(met)
        assert right.contains(met)


@PROPERTY_SETTINGS
@given(finite_intervals(), finite_intervals())
def test_interval_product_encloses_every_extreme_corner(
    left: Interval,
    right: Interval,
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


ROLE_KEY_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_"


@PROPERTY_SETTINGS
@given(
    unit_key=st.text(alphabet=ROLE_KEY_ALPHABET, min_size=1, max_size=40),
    suffix_order=st.permutations(roles.UNIT_ROLE_SUFFIXES),
    suffix_index=st.integers(min_value=0, max_value=len(roles.UNIT_ROLE_SUFFIXES) - 1),
)
def test_unit_role_keys_round_trip_for_every_supported_suffix(
    unit_key: str,
    suffix_order: tuple[str, ...],
    suffix_index: int,
) -> None:
    suffix = suffix_order[suffix_index]
    key = roles.unit_role_key(unit_key, suffix)

    assert roles.parse_unit_role(key, suffix_order) == (unit_key, suffix)
    assert roles.parse_unit_role(suffix, suffix_order) is None


IDENTIFIER_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_"
IDENTIFIERS = st.text(
    alphabet=IDENTIFIER_ALPHABET,
    min_size=1,
    max_size=20,
).filter(lambda value: value[0].isalpha())


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


@st.composite
def kind_declarations(
    draw: st.DrawFn,
) -> tuple[list[str], list[str]]:
    tails = draw(st.lists(IDENTIFIERS, min_size=1, max_size=10, unique=True))
    minted = [f"property.{tail}" for tail in tails]
    declared_flags = draw(st.lists(
        st.booleans(), min_size=len(minted), max_size=len(minted)
    ))
    declared = [kind for kind, keep in zip(minted, declared_flags) if keep]
    return minted, declared


@PROPERTY_SETTINGS
@given(kind_declarations())
def test_process_step_lint_refuses_exactly_the_undeclared_minted_kinds(
    case: tuple[list[str], list[str]],
) -> None:
    minted, declared = case
    session = process.Session(
        name="PropertyProcess",
        purpose="Exercise the process cascade.",
        engine="retail",
        lob="hr",
        period="month",
    )
    steps = [EventSpec(
        kind="property.step",
        when="start",
        summary="Exercise every declared kind.",
        fact_keys=minted,
    )]
    kinds = [FactKindSpec(
        kind=kind,
        value_type="text",
        text="A generated property value.",
        invariants=[Invariant(kind="holds-at")],
    ) for kind in declared]

    findings = process.lint_steps(session, steps, kinds)
    missing = [kind for kind in minted if kind not in declared]

    if not missing:
        assert findings == []
    else:
        assert len(findings) == len(missing)
        for kind in missing:
            assert any(f"mints {kind!r}" in finding for finding in findings)


@st.composite
def slot_declarations(
    draw: st.DrawFn,
) -> tuple[list[RoleSlotSpec], int]:
    names = draw(st.lists(IDENTIFIERS, min_size=1, max_size=12, unique=True))
    duplicate_of = draw(st.integers(min_value=0, max_value=len(names) - 1))
    slots = [RoleSlotSpec(slot=name) for name in names]
    return slots, duplicate_of


@PROPERTY_SETTINGS
@given(slot_declarations())
def test_process_slot_lint_accepts_unique_slots_and_refuses_any_duplicate(
    case: tuple[list[RoleSlotSpec], int],
) -> None:
    slots, duplicate_of = case
    assert process.lint_slots(slots) == []

    duplicated = [*slots, slots[duplicate_of]]
    findings = process.lint_slots(duplicated)

    assert findings == [
        f"slots[{len(slots)}] ({slots[duplicate_of].slot}): duplicates"
        f" slots[{duplicate_of}] — declaration order is the ordering, and one"
        " seat cannot hold two places in it."
    ]


@PROPERTY_SETTINGS
@given(total=st.floats(
    min_value=-1e9,
    max_value=-math.ulp(0.0),
    allow_nan=False,
    allow_infinity=False,
    width=64,
))
def test_allocate_scaled_refuses_every_negative_total(total: float) -> None:
    with pytest.raises(ValueError, match="negative total"):
        detail.allocate_scaled(total, [1.0], decimals=4)
