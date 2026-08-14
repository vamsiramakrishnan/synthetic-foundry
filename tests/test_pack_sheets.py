"""The workbook, authored in a pack.

`columns.py` made the month-end model's eight columns one declaration with a
lint that catches a defect nothing else in this repository can — a summable
margin percentage, where Word prints 24.52, Excel computes 75.15 and
`worldloom validate` passes clean across twenty-one thousand checks. It had one
instance, written in Python, and a pack could not author a workbook: the
shipped `regional-insurer` pack names its company, its books, its voices and
its backstory, and files a month-end model that calls its written premium
"Revenue actual".

These tests hold four things about the seam that now exists.

**It is authorable.** A pack declares `sheets`, `packs.archetype_of` installs
them under the archetype key it is about to mint, and `columns.for_world`
resolves them from a world that was actually built — which is the only claim
that matters, because the archetype key is the one thing a built world still
carries about where its shape came from.

**A bad sheet does not build.** Every other authored layer lints advisory,
because its findings describe something thinner than intended. A sheet's
describe a workbook that disagrees with itself across formats, so
`install_sheets` refuses on them — and the headline case, the summable
percentage, is refused with the finding text rather than warned about.

**The default is untouched.** A world with no pack resolves `columns.PNL`, and
a pack's sheet cannot reach the next world built in the same process. The
registry is keyed by *owner* precisely so that is true by construction rather
than by argument: an authored document type adds a name to the engine's
vocabulary, an authored sheet **replaces** `pnl`.

**It replays.** The sheets ride the pack, the pack rides the recipe verbatim,
so a corpus carrying an authored workbook rebuilds with it in any process with
no pack file on hand.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from worldloom import RetailWorld, columns, doctypes, packs

PACKS = pathlib.Path(__file__).resolve().parents[1] / "examples" / "packs"
INSURER = PACKS / "regional-insurer.json"


@pytest.fixture(autouse=True)
def _isolate_the_registry() -> Any:
    """`columns._INSTALLED` is process-global, like every other install seam.

    Snapshotted and restored around each test so a pack installed here cannot
    decide what a later test in this session resolves — which is the same
    contamination the owner key exists to prevent between *worlds*, applied to
    the test file that keeps installing things.
    """
    before = columns.installed()
    yield
    columns._INSTALLED.clear()
    columns._INSTALLED.update(before)


# ---------------------------------------------------------------------------
# Fixtures: the insurer's own workbook
# ---------------------------------------------------------------------------


#: The shipped P&L, re-headed the way a general insurer would head it.
#:
#: A relabel and nothing more, deliberately: the retail engine mints
#: `financial.*` whatever the pack says the company is, so re-pointing a column
#: at `premium.written.actual` would be a column reading a kind nothing
#: generates — which `columns.lint` refuses, correctly. What a pack can change
#: today is what the reader sees, and for an insurer whose month-end model said
#: "Revenue actual" over its written premium that is the whole complaint.
INSURER_LABELS = {
    "revenue_budget": "Written premium budget",
    "revenue_actual": "Written premium actual",
    "revenue_variance": "Written premium variance",
    "gp_budget": "Underwriting result budget",
    "gp_actual": "Underwriting result actual",
    "gp_variance": "Underwriting result variance",
    "gm_pct_budget": "Underwriting margin budget",
    "gm_pct_actual": "Underwriting margin actual",
}


def _column_document(column: columns.ColumnSpec, **changes: Any) -> dict[str, Any]:
    """One column of the shipped P&L as the JSON a pack would carry."""
    document: dict[str, Any] = {
        "key": column.key,
        "label": INSURER_LABELS[column.key],
        "kind": column.kind,
        "unit": column.unit,
        "summable": column.summable,
    }
    if column.derive is not None:
        document["derive"] = {
            "formula": column.derive.kind.value,
            "operands": list(column.derive.operands),
        }
    document.update(changes)
    return document


def _sheet_document(**broken: dict[str, Any]) -> dict[str, Any]:
    """The insurer's sheet, optionally broken one column at a time."""
    return {
        "name": "pnl",
        "columns": [
            _column_document(column, **broken.get(column.key, {}))
            for column in columns.PNL.columns
        ],
    }


def _pack_document(**broken: dict[str, Any]) -> dict[str, Any]:
    document = json.loads(INSURER.read_text(encoding="utf-8"))
    document["sheets"] = [_sheet_document(**broken)]
    return document


def _pack(**broken: dict[str, Any]) -> packs.Pack:
    return packs.load(_pack_document(**broken))


# ---------------------------------------------------------------------------
# A pack declaring its own sheet installs, and the resolver returns it
# ---------------------------------------------------------------------------


def test_a_pack_sheet_installs_and_the_resolver_returns_it() -> None:
    pack = _pack()
    archetype = packs.archetype_of(pack)

    resolved = columns.for_archetype(archetype.key)
    assert resolved.name == "pnl"
    assert [column.label for column in resolved.columns] == list(INSURER_LABELS.values())
    # Everything a check reads is still the engine's: only what the reader sees
    # moved. A relabel that quietly re-pointed a fact kind would be a workbook
    # reconciling against figures nobody asked for.
    assert resolved.kinds() == columns.PNL.kinds()
    assert resolved.not_summable() == columns.PNL.not_summable()


def test_the_resolver_reads_a_world_that_was_actually_built() -> None:
    """The one integration claim: the archetype key survives pack → world.

    `columns.for_world` has nothing else to go on. `World._archetype` is
    generator state — present on a world built from a seed — and its `key` is
    what `packs.archetype_key` minted. If a locale rebind, a vocabulary
    qualifier or the org builder replaced that key on the way through, the
    resolver would hand a pack-built world the engine's sheet and report
    success, which is the silent fallback this wave exists to stop.
    """
    world = RetailWorld.from_pack(_pack(), seed=8128).build()
    resolved = columns.for_world(world)
    assert resolved.get("revenue_actual").label == "Written premium actual"


def test_the_cuts_are_taken_from_the_authored_sheet() -> None:
    """A pack declares one sheet and gets three.

    The estate sheet and the memo's divisional table are narrowings of the P&L,
    and the whole reason `columns.py` exists is that they were once three
    hand-written lists that had to agree. An author who renames a column renames
    it everywhere without declaring anything twice.
    """
    packs.archetype_of(_pack())
    key = packs.archetype_key(_pack())

    stores = columns.for_archetype(key, "stores")
    assert [c.label for c in stores.columns] == [
        "Written premium budget", "Written premium actual", "Written premium variance",
    ]
    divisions = columns.for_archetype(key, "divisions")
    # The memo's own heading for its variance column survives the authoring:
    # the cut is data (`columns._CUTS`), not two `select` calls in this module.
    assert [c.label for c in divisions.columns] == [
        "Written premium budget", "Written premium actual", "Variance",
        "Underwriting margin actual",
    ]


def test_a_composed_archetype_key_still_resolves() -> None:
    """`divisions.widen` mints `pack:<name>+8div`.

    An exact-match lookup would hand an eight-division pack world the engine's
    sheet and report success — the same silent fallback, arrived at by a route
    nobody would think to test for.
    """
    pack = _pack()
    packs.archetype_of(pack)
    widened = f"{packs.archetype_key(pack)}+8div"
    assert columns.for_archetype(widened).get("revenue_actual").label == (
        "Written premium actual"
    )


# ---------------------------------------------------------------------------
# A pack declaring a bad sheet is refused at install
# ---------------------------------------------------------------------------


def test_a_summable_percentage_is_refused_at_install() -> None:
    """The defect the whole module was written for, made unauthorable.

    `tests/test_columns.py` measured it on a real corpus: with the actual-margin
    column summable, the group row of the Business Unit P&L declares itself the
    sum of the three divisions' margin *rates*. Markdown, Word and PDF print the
    ledger's 24.52, `worldloom validate` passes every check, and Excel reads the
    declaration and computes 75.15. There is no reader of that corpus who could
    tell which number was meant — so a pack that declares one must not build.
    """
    pack = _pack(gm_pct_actual={"summable": True})
    with pytest.raises(ValueError, match="is a percentage and is summable"):
        packs.archetype_of(pack)


@pytest.mark.parametrize(
    ("what", "broken", "signature"),
    [
        (
            "a fact kind no generator declares",
            {"gp_budget": {"kind": "financial.gross_profit.plan"}},
            "no generator in this process declares",
        ),
        (
            "an operand naming no column",
            {"gm_pct_actual": {"derive": {"formula": "ratio_pct",
                                          "operands": ["underwriting_result", "revenue_actual"]}}},
            "which this sheet does not carry",
        ),
        (
            "a formula given the wrong number of operands",
            {"revenue_variance": {"derive": {"formula": "difference",
                                             "operands": ["revenue_actual"]}}},
            "takes 2 operands and was given 1",
        ),
        (
            "a derivation cycle",
            {"gp_actual": {"derive": {"formula": "difference",
                                      "operands": ["gp_variance", "gp_budget"]}}},
            "derives from itself",
        ),
    ],
    ids=["unknown_kind", "unknown_operand", "wrong_arity", "cycle"],
)
def test_every_lint_rule_refuses_the_pack(
    what: str, broken: dict[str, Any], signature: str
) -> None:
    """Refused, not reported — and the finding text is what the author reads.

    A pack author never sees `columns.lint`'s return value; they see whatever
    the build raised. So the refusal carries the finding verbatim, which is the
    only way the sentence explaining *what the engine will actually do* reaches
    the person who has to fix it.
    """
    with pytest.raises(ValueError, match=signature):
        packs.archetype_of(_pack(**broken))


def test_a_sheet_that_drops_a_hand_named_column_is_refused() -> None:
    """`columns.BOUND_KEYS`: the honest boundary of "a pack may author it".

    Five column keys are written into the month-end model's Summary table and
    five into its charts. A sheet without `gp_actual` does not make a smaller
    workbook — it makes `summary_row("gp_actual", …)` raise `KeyError` inside
    the compiler, a long way from the declaration. Refused where it was
    declared instead.
    """
    document = _pack_document()
    document["sheets"][0]["columns"] = [
        column for column in document["sheets"][0]["columns"]
        if column["key"] != "gp_actual"
    ]
    with pytest.raises(ValueError, match="does not carry 'gp_actual'"):
        packs.archetype_of(packs.load(document))


def test_a_sheet_that_is_not_the_pnl_is_refused() -> None:
    """The estate sheet is a cut, not a sheet.

    Declaring it separately puts back exactly the disagreement `columns.py` was
    extracted to end: `documents._MEASURES` is the P&L's kind table, so a
    `stores` sheet naming a different fact kind for `revenue_actual` is read
    from the P&L anyway and the declaration is silently inert.
    """
    document = _pack_document()
    document["sheets"][0]["name"] = "stores"
    with pytest.raises(ValueError, match="is not authorable"):
        packs.archetype_of(packs.load(document))


def test_a_duplicated_column_is_refused_rather_than_silently_narrowing() -> None:
    document = _pack_document()
    document["sheets"][0]["columns"].append(document["sheets"][0]["columns"][0])
    with pytest.raises(ValueError, match="twice"):
        packs.archetype_of(packs.load(document))


def test_nothing_is_installed_when_a_sheet_is_refused() -> None:
    """All-or-nothing, so a refused pack leaves the process holding neither.

    A half-installed workbook is worse than none: the next build from that
    archetype key would compile against a sheet whose own pack failed to load.
    """
    pack = _pack(gm_pct_budget={"summable": True})
    with pytest.raises(ValueError):
        packs.archetype_of(pack)
    assert columns.for_archetype(packs.archetype_key(pack)) == columns.PNL


# ---------------------------------------------------------------------------
# The default is untouched
# ---------------------------------------------------------------------------


def test_a_world_with_no_pack_resolves_the_shipped_sheet() -> None:
    world = RetailWorld(seed=8128).build()
    assert columns.for_world(world) == columns.PNL
    assert columns.for_world(world, "stores") == columns.STORES
    assert columns.for_world(world, "divisions") == columns.DIVISIONAL


def test_an_authored_sheet_does_not_reach_the_next_world_built() -> None:
    """The contamination an owner-keyed registry makes impossible.

    Built in this order deliberately — a stock world, then a pack world that
    installs a sheet, then a stock world again. A registry keyed by sheet *name*
    would hand the third build the insurer's workbook, in the same process, with
    nothing in either corpus to notice by. This is the guard
    `tests/test_doctypes.py::test_an_authored_type_does_not_reach_the_next_world_built`
    had to establish by construction; here it is structural, because a stock
    archetype key is never `pack:`-prefixed.
    """
    before = columns.for_world(RetailWorld(seed=8128).build())
    RetailWorld.from_pack(_pack(), seed=8128).build()
    assert columns.for_world(RetailWorld(seed=8128).build()) == before == columns.PNL


def test_a_pack_with_no_sheets_installs_nothing() -> None:
    """Every pack in `examples/` predates this field. None of them may move."""
    for source in sorted(PACKS.glob("*.json")):
        pack = packs.load(source)
        assert pack.sheets == []
        packs.archetype_of(pack)
        assert columns.for_archetype(packs.archetype_key(pack)) == columns.PNL


def test_the_default_workbook_is_the_one_documents_still_compiles() -> None:
    """The off path is the path the engine already took.

    `documents` binds its four tables from `columns.PNL` at import. Until the
    compiler calls the resolver, that is the whole default build — and the
    resolver's answer for a world with no pack has to be the same object, or
    wiring it would change a corpus nobody asked to change.
    """
    from worldloom import documents

    assert columns.for_archetype("omnichannel_retailer").kinds() == documents._MEASURES
    assert columns.for_archetype("omnichannel_retailer").derivations() == documents._DERIVED
    assert columns.for_archetype("").not_summable() == documents._NOT_ADDITIVE
    assert columns.for_archetype("").rate_kinds() == documents._RATE_KINDS


# ---------------------------------------------------------------------------
# Installing twice, and replay
# ---------------------------------------------------------------------------


def test_installing_the_same_sheet_twice_is_not_a_conflict() -> None:
    """A pack loaded twice, or a corpus rebuilt in the process that built it."""
    pack = _pack()
    packs.archetype_of(pack)
    packs.archetype_of(pack)
    assert columns.for_archetype(packs.archetype_key(pack)).get("gp_actual").label == (
        "Underwriting result actual"
    )


def test_a_different_sheet_under_one_owner_is_refused() -> None:
    """Two declarations disagreeing about what a column reads would make a
    workbook depend on load order — `episodes.install`'s rule, and its reason."""
    packs.archetype_of(_pack())
    other = _pack()
    with pytest.raises(ValueError, match="already installed"):
        columns.install(
            packs.archetype_key(other),
            [columns.PNL],  # the engine's labels, under the insurer's owner key
        )


def test_the_sheet_rides_the_recipe_embedding() -> None:
    """The determinism argument, which is why this is not a `--sheet` flag.

    The sheets travel inside the pack, `to_recipe` embeds the pack verbatim, and
    the recipe travels with the corpus — so a process holding only the corpus
    installs the same workbook before compiling it.
    """
    pack = _pack()
    rebuilt = packs.load(packs.to_recipe(pack))
    assert rebuilt == pack
    assert [c.label for c in rebuilt.sheets[0].columns] == list(INSURER_LABELS.values())

    packs.archetype_of(rebuilt)
    assert columns.for_archetype(packs.archetype_key(pack)).get("gm_pct_budget").label == (
        "Underwriting margin budget"
    )


# ---------------------------------------------------------------------------
# The lint an author reads before they get that far
# ---------------------------------------------------------------------------


def test_pack_check_names_what_the_build_would_refuse() -> None:
    """`worldloom pack check` reports every rule `install_sheets` raises on.

    The argument `doctypes.lint` already makes about the rules
    `register_artifact_types` refuses: the difference between an author reading
    their mistake and hitting it half-way through a build.
    """
    findings = packs.lint(_pack(gm_pct_actual={"summable": True}))
    sheet_findings = [f for f in findings if f.startswith("sheets[0]")]
    assert len(sheet_findings) == 1, sheet_findings
    assert "is a percentage and is summable" in sheet_findings[0]


def test_the_lint_does_not_raise_on_a_sheet_so_broken_it_cannot_be_built() -> None:
    """A duplicated column key raises in `Sheet.__post_init__`.

    A lint that tracebacks is a lint nobody runs on the pack that needs it most,
    so the construction refusal comes back as a finding like the rest.
    """
    document = _sheet_document()
    document["columns"].append(document["columns"][0])
    findings = doctypes.lint_sheets([doctypes.SheetSpec.model_validate(document)])
    assert len(findings) == 1 and "twice" in findings[0], findings


def test_a_sheet_may_read_a_fact_kind_this_packs_own_process_mints() -> None:
    """`extra_kinds`, and the reason `doctypes.lint` needed the same hatch.

    `episodes.install` puts a spec in the episode grammar and does *not*
    register its fact kinds with `factkinds` — only a vertical module registers
    there. Without being told, the sheet lint would refuse a pack for reading a
    kind its own company genuinely produces.
    """
    document = _sheet_document(revenue_actual={"kind": "underwriting.premium.written"})
    spec = doctypes.SheetSpec.model_validate(document)

    assert any(
        "no generator in this process declares" in finding
        for finding in doctypes.lint_sheets([spec])
    )
    assert doctypes.lint_sheets(
        [spec], extra_kinds=frozenset({"underwriting.premium.written"})
    ) == []


# ---------------------------------------------------------------------------
# The schema is the engine's value, ported
# ---------------------------------------------------------------------------


def test_the_shipped_sheet_round_trips_through_the_schema() -> None:
    """A schema that cannot express what the engine already ships describes a
    different engine — `test_doctypes.py`'s argument, applied one layer over."""
    document = {
        "name": columns.PNL.name,
        "columns": [
            {
                "key": column.key,
                "label": column.label,
                "kind": column.kind,
                "unit": column.unit,
                "summable": column.summable,
                **(
                    {}
                    if column.derive is None
                    else {"derive": {"formula": column.derive.kind.value,
                                     "operands": list(column.derive.operands)}}
                ),
            }
            for column in columns.PNL.columns
        ],
    }
    assert doctypes.SheetSpec.model_validate(document).as_sheet() == columns.PNL
