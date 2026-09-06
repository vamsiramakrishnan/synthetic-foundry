"""Ten policies, ten vocabularies — the largest measured shape defect, pinned.

`policies._outline`'s argument that a policy has *two* sections is about the
count and it holds. What did not hold is that all ten shipped policies said it
in one pair of words. Measured over `documents._OUTLINES` with the reading
`vendi.py` itself publishes — bigram-Jaccard over padded heading sequences,
Rényi order 1 — the fleet's 42 authored outlines were **33 distinct sequences
worth 24.19 effective ones**, where the 33 distinct scored on their own come to
**32.86**. Near-repeats among genuinely different documents cost 0.14; the
shared pair cost the other 8.7.

So the assertions here are about *usage* rather than about vocabulary size: it
is not enough that headings exist, they have to be spent on different
documents. The Vendi reading is asserted inside a tolerance rather than to the
last bit, for the reason `vendi.py`'s docstring gives — ``eigvalsh`` is a LAPACK call and
its last bits are a property of whichever BLAS the machine linked, so a score
is something to gate with a tolerance and never something to build from.

Written over the **installed** outlines, like `test_optional_sections.py`, and
for the same reason: the claim is about the fleet this repository ships, and a
pack fixture elsewhere in the suite leaves its authored types in the
process-global registry for everything that runs afterwards.
"""

from __future__ import annotations

import itertools
from collections import Counter

import pytest

import worldloom  # noqa: F401  — imports every vertical, which is what installs them
from worldloom import doctypes, documents, policies
from worldloom.vendi import vendi_of

#: The score's tolerance. Three decimal places is far tighter than any BLAS
#: disagreement (`test_vendi` measures that dust at 1e-16) and far looser than
#: the 0.14 a single near-repeat is worth, so this catches a regression in the
#: vocabulary and never a regression in the machine.
TOLERANCE = 1e-3


def bigram_jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """The outline kernel, restated from `tests/test_vendi.py`.

    Restated rather than imported so this file's claim is legible without
    reading another: the padding is what makes a heading's *position* count, so
    two outlines that share a heading in first place are more alike than two
    that share it in the middle, and a one-heading outline still has bigrams.
    """
    def grams(sequence: tuple[str, ...]) -> frozenset[tuple[str, str]]:
        padded = ("\x02", *sequence, "\x03")
        return frozenset(itertools.pairwise(padded))

    left, right = grams(a), grams(b)
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def fleet() -> list[tuple[str, tuple[str, ...]]]:
    """Every shipped type and its heading sequence, authored packs excluded."""
    authored = set(doctypes.installed())
    return [
        (artifact_type, tuple(plan.heading for plan in plans))
        for artifact_type, plans in documents._OUTLINES.items()
        if artifact_type not in authored
    ]


def family() -> list[tuple[str, tuple[str, ...]]]:
    installed = set(policies.by_artifact_type())
    return [(key, headings) for key, headings in fleet() if key in installed]


def test_no_two_policies_open_on_the_same_words() -> None:
    """The defect itself, stated as an invariant rather than as a score.

    A score moves for many reasons and a reader cannot tell which; this cannot.
    Every heading as well as every sequence, because two policies sharing one
    of their two headings is most of the way back to sharing both.
    """
    outlines = family()
    assert len(outlines) == 10
    repeated = Counter(headings for _, headings in outlines)
    assert not [seq for seq, n in repeated.items() if n > 1], (
        "policies sharing a heading sequence: "
        f"{sorted(key for key, headings in outlines if repeated[headings] > 1)}"
    )
    seen: dict[str, str] = {}
    for key, headings in outlines:
        for heading in headings:
            assert heading not in seen, (
                f"{key} and {seen[heading]} both use the heading {heading!r};"
                " a policy's sections come from what it governs, and no two of"
                " these govern the same thing"
            )
            seen[heading] = key


def test_a_policy_still_has_exactly_two_sections() -> None:
    """The half of `_outline`'s docstring that was right and stays.

    A policy is short, its content is a table, and four sections of padding
    around one grid is what makes real policy documents unreadable. The answer
    to ten identical outlines was ten vocabularies, not a third section, and
    that is a decision worth being unable to drift out of.
    """
    for key, headings in family():
        assert len(headings) == 2, f"{key} has {len(headings)} sections, not two"


def test_the_shared_rules_are_appended_rather_than_retyped() -> None:
    """Vocabulary varies; the rules that hold for any policy do not.

    Three of them, and each exists because a policy without it is a worse
    document: who it binds, that the figures are stated once in the provisions
    table, and that a rule with no consequence is guidance. They live in
    `_outline` so an area registered tomorrow inherits them — ten copies of a
    rule are ten chances for nine of them to go stale.
    """
    authored = set(doctypes.installed())
    for key in sorted(set(policies.by_artifact_type()) - authored):
        covers, requires = documents._OUTLINES[key]
        assert "who this binds" in covers.purpose, key
        assert "provisions table below states them" in covers.purpose, key
        assert "a policy with no consequence is guidance" in requires.purpose, key
        # And the part that is this policy's own. The purpose opens with the
        # spec's own sentence about what the document is for, so a writer is
        # never handed the shared scaffolding alone.
        spec = policies.by_artifact_type()[key]
        assert covers.purpose.startswith(spec.purpose), key


def test_an_area_that_authors_no_vocabulary_still_gets_its_own_words() -> None:
    """The fallback derives from the policy's own title, and is checked here.

    `policies.register` is the seam a vertical with genuinely its own paperwork
    uses, and a pack author has no obligation to write four sentences of
    section vocabulary. What they must not get is the shared pair back: a
    default constant would leave this fix applying only to the ten documents
    that happened to be measured, which is the shape of a fix that passes its
    own test and changes nothing.

    Exercised through `_outline` directly, and the reason is worth recording
    rather than hiding behind a fixture: ``policies.register`` today adds an
    area to ``LIBRARY`` and does *not* install its artifact types, because
    registration into `documents` happens once at import. So a late-registered
    area reaches no document yet, and this is where the derivation is held
    until it does.
    """
    spec = policies.PolicySpec(
        name="clinical_governance",
        artifact_type="clinical_governance_policy",
        title="Clinical Governance Policy",
        area="clinical", domain="governance", audience="all_staff",
        owner="ceo", approver="ceo",
        purpose="How clinical quality is assured, and who answers for it.",
        clauses=(policies.Clause("review_months", "Months between reviews",
                                 unit="months", amount=6),),
    )
    headings = tuple(plan.heading for plan in policies._outline(spec))
    assert headings == ("What the Clinical Governance Policy covers",
                        "What the Clinical Governance Policy requires")
    assert headings not in {sequence for _, sequence in fleet()}


def test_the_fleet_is_forty_three_distinct_outlines() -> None:
    """What the count says, before the effective count is allowed to speak.

    33 before, 42 after, which is the whole of the repeated pair being spent on
    ten documents instead of one. The count is the generous reading — it prices
    a one-heading difference as a whole new document — so it has to be checked
    first: a change that moved the score without moving this would be one that
    made the near-repeats slightly less near, which is not what was asked for.

    43 now: insurance's ``underwriting_result_commentary`` arrived with that
    vertical's estate, and its two headings are its own rather than a
    re-spelling of the divisional close commentary's — which is why the count
    and the effective count moved together by very nearly one whole document
    (42.855 of a possible 43) instead of the count moving alone.
    """
    outlines = fleet()
    assert len(outlines) == 43
    assert len({sequence for _, sequence in outlines}) == 43


def test_the_effective_count_is_off_twenty_four() -> None:
    """The deliverable. 24.19 before, 42.86 after, out of a possible 43.

    Read three ways, because quoting a bracket rather than a point is the
    honest reading of this family and `vendi.py` says so: ``q = 0`` is the rank
    and agrees with the distinct count at 43, ``q = 1`` is the Vendi score
    proper, and ``q = inf`` — the sample judged entirely by its most dominant
    mode — went from **4.20** to **33.86**, which is the reading the defect was
    loudest in. Ten of forty-two documents being one document put the dominant
    mode at four; nothing dominates the fleet now.

    The residual 0.14 between the score and the count is the near-repeats
    *among genuinely different documents* — a close commentary and its own
    variant share four of five headings — and it is not a defect. Driving it to
    the count would mean no two documents in this company's archive resemble
    each other, which is not true of any archive.
    """
    outlines = [sequence for _, sequence in fleet()]
    assert vendi_of(outlines, bigram_jaccard) == pytest.approx(42.8553, abs=TOLERANCE)
    assert vendi_of(outlines, bigram_jaccard, order=0.0) == pytest.approx(43.0)
    assert vendi_of(outlines, bigram_jaccard, order=float("inf")) == pytest.approx(
        33.8585, abs=TOLERANCE
    )
