"""Which sections are optional, and the invariants that annotation has to hold.

`structure.py` derives a document's shape from a genome; this file is about the
*input* to that derivation. A genome can only reach as many shapes as the fleet
declares optional sections, so `required=False` is where the diversity actually
comes from — and it is a judgement about documents rather than a knob, which is
why the assertions here are about what a reader would find strange rather than
about arithmetic.

Written over the **installed** outlines — ``documents._OUTLINES`` after every
vertical module has registered into it, which importing `worldloom` is what
does — rather than over the literals in any one module. Three of the four files
that carry annotations are vertical document modules, and a test that read only
`documents.py` would pass while banking's outlines said anything at all.
"""

from __future__ import annotations

import worldloom  # noqa: F401  — imports every vertical, which is what installs them
from worldloom import doctypes, documents, structure
from worldloom.structure import StructuralGenome

#: The genome the wave was measured at, and the one the shipped
#: ``--section-omission 400`` corpus was built with.
OMISSION = StructuralGenome(omission=400)


def installed() -> list[tuple[str, tuple[documents.SectionPlan, ...]]]:
    """Every outline a document can actually be built from, variants included.

    A type with variants is *not* also reachable through ``_OUTLINES`` —
    `_variant_for` reads the variant table first — but its first variant is the
    same tuple object as its ``_OUTLINES`` entry, so listing variants when they
    exist and the plain outline otherwise enumerates each reachable outline
    exactly once. That is also the enumeration the headline space figure is
    summed over, so the two cannot drift apart.

    Authored types are excluded, and finding out why cost a full-suite run: the
    registry is process-global and `doctypes.install` deliberately never
    un-installs, so a pack fixture anywhere in the suite leaves its type in
    ``_OUTLINES`` for every test that runs afterwards. Passing alone and failing
    in the suite (49 outlines against 50, on `franchisee_trading_statement`
    from the doctypes fixtures) is the signature. The figures here are a claim
    about *the fleet this repository ships*, so the fleet is what they are
    counted over; a pack's own annotation is the pack author's judgement and
    `doctypes.lint` is where it answers for it.
    """
    authored = set(doctypes.installed())
    return [
        (artifact_type, variant)
        for artifact_type, plans in documents._OUTLINES.items()
        if artifact_type not in authored
        for variant in documents._OUTLINE_VARIANTS.get(artifact_type, (plans,))
    ]


def optional_sections() -> list[tuple[str, documents.SectionPlan]]:
    return [
        (artifact_type, section)
        for artifact_type, outline in installed()
        for section in outline
        if not section.required
    ]


def test_no_outline_opens_on_an_optional_section() -> None:
    """A document that opens on its second thought is a different failure.

    The hard rule of the annotation wave, and the one worth a test rather than a
    convention: omission makes a document *shorter*, and a reader forgives that.
    A memo whose first heading is sometimes "Drivers" and sometimes "Position"
    is a memo that changed its argument, which is a claim about the company
    nobody made — and the retriever learns the wrong thing from it either way.
    """
    for artifact_type, outline in installed():
        assert outline[0].required, (
            f"{artifact_type}: {outline[0].heading!r} is the first section of its"
            " outline and may not be optional — omission shortens a document, it"
            " does not let it open somewhere else"
        )


def test_an_optional_section_never_sits_in_a_one_section_type() -> None:
    """A one-section type with an optional section can produce nothing.

    ``StructuralGenome.floor`` would restore it — so the document is unchanged
    and the annotation buys nothing at all except a shape in the space count
    that no corpus ever renders. Noise in the headline figure is worse than a
    missing annotation, because a figure nobody can reproduce is one nobody
    trusts.
    """
    for artifact_type, outline in installed():
        if any(not section.required for section in outline):
            assert len(outline) >= 2, (
                f"{artifact_type} has one section and it is optional; the floor"
                " would restore it, so this annotation reaches no document"
            )


def test_every_optional_purpose_still_reads_as_a_complete_instruction() -> None:
    """The purpose is what a writer is handed, whether or not the section fires.

    A smoke assertion by design. Nothing here can tell a good instruction from a
    bad one, and the point is that a future annotator finds a test at the place
    they are about to edit — several purposes in this fleet name their own
    conditionality ("skip gracefully if nothing does") and that sentence is the
    strongest evidence the annotation is right. It is also prose the narration
    handshake ships verbatim, so a truncated one reaches a model.
    """
    for artifact_type, section in optional_sections():
        purpose = section.purpose.strip()
        assert purpose, f"{artifact_type}/{section.heading} has no purpose"
        assert purpose.endswith("."), (
            f"{artifact_type}/{section.heading}: purpose does not end in a full"
            f" stop, so it is probably truncated: …{purpose[-40:]!r}"
        )


def test_the_reachable_space_is_what_the_wave_claims() -> None:
    """The headline figure, pinned so it cannot rot silently.

    50 classic, 73 under ``omission=400``: 21 optional sections across 17 types.
    The twentieth is `workforce`'s ``onboarding_checklist/Access and security``,
    annotated when the policy vocabulary was authored: a corpus built without
    ``--policies`` has no security clauses for it to cite and already ships the
    start-date-only checklist, so the shorter document is one this repository
    produces rather than one this annotation invents.

    The twenty-first is insurance's ``underwriting_result_commentary/The book
    and the claims behind it``, which arrived with that vertical's own estate.
    An investment function has no policy book and notifies no claims, so its
    managing director's page genuinely has nothing to put under that heading —
    the annotation says the absence is intended rather than a section somebody
    lost, which is the same judgement every other one here is.

    The classic half is the more important assertion of the two — it is the
    byte-identity guarantee stated as a number, because every corpus in this
    repository is built without a genome and CI diffs them. If classic ever
    exceeds the count of installed outlines, some outline has become
    genome-sensitive at ``omission=0`` and every checked-in corpus is a diff.
    """
    outlines = installed()
    classic = sum(structure.space(outline) for _, outline in outlines)
    assert classic == len(outlines) == 50

    reachable = sum(structure.space(outline, OMISSION) for _, outline in outlines)
    assert reachable == 73, (
        f"reachable heading sequences is {reachable}, not 73 — if you have"
        " annotated a section, say so here and in the module's own comment"
    )
    assert len(optional_sections()) == 21


def test_the_policy_family_is_deliberately_not_annotated() -> None:
    """Ten types, two sections each, and both of every pair stay required.

    Marking either optional across that family produces ten policies that are
    sometimes half a policy: a policy with no duties names nobody who has to do
    anything, and one that never says what it governs is a list of duties that
    does not say who it binds. Neither absence is one a reader would fail to
    notice, so neither clears the rule.

    This test used to identify the family by the pair of headings all ten
    shared — ``Purpose and scope | Responsibilities`` — and to say that the
    answer for it was *more* sections. That was half right and the half it got
    wrong was measured afterwards: the sharing cost the fleet 8.7 of its 32.9
    effective heading sequences, and the fix was ten *vocabularies* rather than
    a third section, because the two-section argument in `policies._outline`
    was never the problem. So the family is now found through
    ``policies.by_artifact_type()``, which is what it always was, and the
    surviving assertion is the one about annotation. Their distinctness is
    `tests/test_policy_vocabulary.py`'s to hold, since that is now a claim
    about ten documents rather than about one shared tuple.
    """
    from worldloom import policies as policy_library

    family = set(policy_library.by_artifact_type())
    outlines = [
        (artifact_type, outline)
        for artifact_type, outline in installed()
        if artifact_type in family
    ]
    assert len(outlines) == 10
    for artifact_type, outline in outlines:
        assert len(outline) == 2, (
            f"{artifact_type} no longer has two sections; `policies._outline`"
            " argues for exactly two and this is where that is pinned"
        )
        for section in outline:
            assert section.required, (
                f"{artifact_type}/{section.heading}: half a policy is not a"
                " shorter policy — vary the words, not the count"
            )
