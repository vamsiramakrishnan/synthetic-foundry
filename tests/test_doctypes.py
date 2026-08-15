"""Artifact types as authored data: the schema, the loader, and the lint.

Thirty artifact types are declared in this repository and nearly all of what
defines each one is data sitting in a Python dict. A model could give a company
a name, divisions, books, voices, a trading year and a backstory as authored
JSON, and could not give it a single document of its own — for no reason except
that nobody had written the loader.

These tests hold three things about the loader that now exists.

**The schema describes *this* engine.** `test_every_declared_type_round_trips_through_the_schema`
describes every type the registry holds, dumps it to JSON, loads it back, and
compares it against the tables field by field.
A schema that cannot express what the engine already ships is a schema that
describes a different engine, so the port is the specification's own proof, and
`test_the_ported_tables_build_a_byte_identical_corpus` runs a build with the
tables *replaced* by the ones the JSON produces rather than trusting equality of
dictionaries.

**It cannot make another world different.** The compiler's tables are
process-global — deliberately, since `documents.written_at` is called from
`generators/distractors.py` with no world in scope — so the hazard an authored
type introduces is not "my corpus is wrong", it is "the corpus somebody built
after mine, in the same process, is wrong".
`test_an_authored_type_does_not_reach_the_next_world_built` verifies that by
construction rather than by argument.

**The lint refuses what compiles.** The failure worth catching here does not
raise: a type whose outline cites fact kinds nothing produces compiles into a
document with one hidden appendix, is carried into the manifest, is rendered to
Word, and comes back from retrieval as an empty answer. Every rule fires against
`examples/artifact-types/franchise-network-broken.json`, which exists to be
wrong in every way at once.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter
from datetime import timedelta

import pytest

from worldloom import (
    MonthEndClose, RetailWorld, World, doctypes, documents, packs, registries,
)
from worldloom.generators import planning
from worldloom.render import docx as docx_render, markdown as markdown_render

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples" / "artifact-types"
CORE = EXAMPLES / "core.json"
AUTHORED = EXAMPLES / "franchise-network.json"
BROKEN = EXAMPLES / "franchise-network-broken.json"

PERIOD = "2026-03"

#: The one authored type the shipped example declares.
STATEMENT = "franchisee_trading_statement"


@pytest.fixture(autouse=True)
def _restore_the_registries():
    """This file installs authored types; nothing here may outlive its test.

    It had no cleanup at all, and that is the leak this repository has hit four
    times. `doctypes.install` writes five tables it does not own —
    `documents._STANDING`, `_LAG`, `_OUTLINES`, `_FILINGS` and
    `render.docx.HANDLES` — so a type installed here was declared for every test
    that ran afterwards. Measured consequence, on a pack whose LOB names
    document types nothing declares: `packs.lint` reports 5 findings in a cold
    process and **0** once anything has installed a type, so the lint that
    exists to catch "an edge to a document that will never be planned" goes
    quiet because a different company's paperwork is loaded.

    `registries.scoped()` rather than a hand-rolled snapshot, and the difference
    is not style. The six other files that hand-roll one restore between three
    and five registries each, and every one of those lists is a copy of what an
    installer writes rather than the installer's own account of it — which is
    how `validate._pack_registries` came to omit `columns._INSTALLED`, and how
    restoring `doctypes._INSTALLED` alone came to leave `documents` still
    holding the types while `doctypes.installed()` reported none.

    Per test rather than per module, `tests/test_cohorts.py`'s reason verbatim:
    a type installed by one test is not visible to the next, so no test in this
    file can come to depend on another having run first.
    """
    with registries.scoped():
        yield


def _pack_world(source: pathlib.Path = AUTHORED) -> World:
    pack = packs.load(source)
    return RetailWorld.from_pack(pack, seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


def _stock_world() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


#: Reads every artifact type name a planner passes, across the modules
#: ``import worldloom`` actually loads. Run in a subprocess — see its one caller.
_SCAN_FOR_PLANNED_TYPES = """
import json, pathlib, re, sys
import worldloom
pattern = re.compile(r'(?:artifact_type=|intent\\(\\s*)"([a-z][a-z0-9_]*)"')
found = set()
for name, module in sorted(sys.modules.items()):
    if not name.startswith("worldloom"):
        continue
    source = getattr(module, "__file__", None)
    if source and source.endswith(".py"):
        found |= set(pattern.findall(pathlib.Path(source).read_text(encoding="utf-8")))
print(json.dumps(sorted(found)))
"""


def _in_a_fresh_interpreter(program: str) -> str:
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-c", program], check=True, capture_output=True, text=True
    ).stdout


def _manifest(world: World) -> list[tuple]:
    """A world's document set, reduced to what the four tables decide.

    Compiled rather than planned, because three of the four only take effect at
    compile time: the outline decides the sections, ``standing`` the authority,
    and ``written_at`` the date.
    """
    return [
        (entry.id, entry.artifact_type, entry.authority.value, entry.lifecycle.value,
         entry.created_at.isoformat(), entry.title, tuple(entry.supporting_fact_ids))
        for entry in world.compile().artifacts
    ]


# ---------------------------------------------------------------------------
# Where the data/code line falls
# ---------------------------------------------------------------------------


def test_the_data_code_line_falls_at_the_compilers_and_nowhere_else() -> None:
    """The measurement the module docstring quotes, re-taken on every run.

    An outline is the sort of thing that reaches for a callable the moment one
    section wants a computed heading, and if any of the seventy-one had, the
    honest schema would have had to carry an escape hatch. None has, and the
    reason is structural — `outline()` resolves a section by testing fact
    *kinds* against prefixes and filtering on subject scope, and both are
    string comparisons by construction.
    """
    for key, (authority, lifecycle) in documents._STANDING.items():
        assert isinstance(authority.value, str) and isinstance(lifecycle.value, str), key
    for key, lag in documents._LAG.items():
        assert isinstance(lag, timedelta), key
        # Whole minutes, which is what lets `Lag` be three integers rather than
        # a duration string with a parser in it.
        assert lag.total_seconds() % 60 == 0, key

    for key, plans in documents._OUTLINES.items():
        for plan in plans:
            assert isinstance(plan, documents.SectionPlan), key
            assert isinstance(plan.heading, str) and isinstance(plan.purpose, str), key
            assert plan.scope in {"group", "unit", "any"}, key
            assert all(isinstance(kind, str) for kind in plan.kinds), key

    assert all(callable(builder) for builder in documents._COMPILERS.values())
    # The five this change was measured against are still compiled, stated as a
    # subset rather than an equality: a vertical registering a sixth is adding
    # to the engine, not contradicting the measurement, and a test that pinned
    # the count would fail on somebody else's correct work. What the *shape*
    # claim needs is the line below.
    assert {
        "finance_workbook", "meeting_minutes", "email_thread",
        "capital_return", "reserve_triangle_workbook",
    } <= set(documents._COMPILERS)
    # A type with both would have two accounts of its structure and nothing to
    # say which wins — `compile_intent` reaches the compiler and the outline is
    # never read, silently. Unless the compiler is one that *composes* the
    # outline (`documents.extends_outline`), in which case there is one account
    # and the compiler is how its last block gets resolved. The exemption is
    # per-compiler and marked on the function, so a from-scratch compiler that
    # grew an outline by accident still fails here — which is the defect this
    # line exists to catch.
    assert not {
        key for key in set(documents._COMPILERS) & set(documents._OUTLINES)
        if not documents.extends_outline(documents._COMPILERS[key])
    }


# ---------------------------------------------------------------------------
# The port: thirty types, expressed
# ---------------------------------------------------------------------------


def test_every_declared_type_round_trips_through_the_schema() -> None:
    """The port's real claim, taken against the registry rather than a file.

    Every type the process has declared is described as a `DocumentType`,
    dumped to JSON, loaded back, and required to equal the tables it came from
    — field by field, not by count. A schema that expressed twenty-eight of
    thirty would be a schema for a smaller engine, and the two it dropped would
    be exactly the two whose shape somebody found inconvenient.

    Stated over the live registry so it keeps holding as verticals land: a
    fourth engine's types have to be expressible too, and a checked-in snapshot
    could only ever prove it about the types that existed when it was written.
    """
    declared = sorted(documents.declared_types())
    assert len(declared) >= 30

    reloaded = {
        spec.key: spec
        for spec in doctypes.load(doctypes.to_document(
            doctypes.describe(key) for key in declared
        ))
    }
    assert sorted(reloaded) == declared

    for key in declared:
        spec = reloaded[key]
        assert (spec.authority, spec.lifecycle) == documents.standing(key), key
        assert spec.lag.as_timedelta() == documents._LAG[key], key
        assert spec.word == (key in docx_render.HANDLES), key
        assert tuple(s.as_plan() for s in spec.sections) == documents._OUTLINES.get(
            key, ()
        ), key


def test_the_checked_in_port_still_matches_the_registry() -> None:
    """`examples/artifact-types/core.json`, the thirty this change was written against.

    It is an example an author copies from, so it has to stay true. Checked as a
    subset of what is declared rather than as an equality: a vertical landing
    afterwards adds types the file does not carry, and that is not the file
    being wrong.
    """
    ported = doctypes.load(CORE)
    assert len(ported) >= 30
    assert {spec.key for spec in ported} <= documents.declared_types()
    for spec in ported:
        assert spec == doctypes.describe(spec.key), spec.key


def test_the_types_the_schema_cannot_express_are_exactly_the_compiled_ones() -> None:
    """What still requires Python, stated as a set rather than as a caveat.

    A type with a dedicated compiler builds its IR in code — a workbook that
    declares formulas, a thread with one message per moment — and no outline
    can stand in for that. The port carries their standing and their lag,
    because those are data whoever builds the IR; it cannot carry the compiler,
    and pretending otherwise would let somebody author a
    `reserve_triangle_workbook` that came out as an empty outline.

    A third case arrived with standing documents and the distinction is worth
    the branch: a compiler that *composes* the outline — calls `outline` and
    inserts one resolved block into what comes back, as `policies._provisions`
    does with its provisions table — has an outline that is live data rather
    than dead. Marked on the compiler rather than inferred, because the two
    kinds are the same callable shape (`documents.extends_outline`).
    """
    for key in sorted(documents.declared_types()):
        described = doctypes.describe(key)
        compiler = documents._COMPILERS.get(key)
        if compiler is not None and not documents.extends_outline(compiler):
            assert not described.sections, (
                f"{key} has a compiler; an outline beside it would be dead data"
            )
        else:
            # Everything else is fully expressed: its IR comes from `outline()`,
            # which reads nothing but the sections the schema carries.
            assert tuple(s.as_plan() for s in described.sections) == \
                documents._OUTLINES.get(key, ())


def test_the_ported_tables_build_a_byte_identical_corpus(monkeypatch) -> None:
    """Not equality of dictionaries — equality of the corpus they produce.

    The tables are rebuilt from the JSON document (parsed strings, parsed enum
    values, integers turned into `timedelta`s) and installed over the Python
    literals; then a world is built and every document's identity, authority,
    date, title and cited facts are compared against the same world built the
    ordinary way. Two dicts that compare equal and a corpus that comes out the
    same are different claims, and only the second one is the specification.
    """
    before = _manifest(_stock_world())

    ported = doctypes.load(doctypes.to_document(
        doctypes.describe(key) for key in sorted(documents.declared_types())
    ))
    monkeypatch.setattr(documents, "_STANDING", {
        spec.key: (spec.authority, spec.lifecycle) for spec in ported
    })
    monkeypatch.setattr(documents, "_LAG", {
        spec.key: spec.lag.as_timedelta() for spec in ported
    })
    monkeypatch.setattr(documents, "_OUTLINES", {
        spec.key: tuple(section.as_plan() for section in spec.sections)
        for spec in ported if spec.sections
    })

    assert _manifest(_stock_world()) == before


# ---------------------------------------------------------------------------
# Determinism, and the hazard a loader reintroduces
# ---------------------------------------------------------------------------


def test_a_planned_type_is_either_declared_or_reserved() -> None:
    """Nothing plans a document under a name the tables have never heard of.

    `documents.reserved_types()` is the list of names a scenario mints and no
    module declares, and its whole purpose is to stop a pack from claiming one
    — which would give somebody else's document an authority nobody chose, in a
    process that had built both corpora. A hand-kept list goes stale silently,
    so it is checked against the source: every artifact type name any planner
    passes must be declared or reserved, and a name that becomes declared drops
    out of the reserved set on its own.
    """
    # Only the modules the package itself imports, and read in a fresh
    # interpreter so the answer does not depend on what another test file
    # imported first. A domain module that is *not* imported at package import
    # cannot make any corpus differ — that is exactly the contract
    # `register_artifact_types` states — so a vertical still being written,
    # whose planner exists and whose registration is not wired in yet, is out of
    # scope here rather than a failure. It comes into scope on the line that
    # imports it, which is the line that makes its types real.
    planned = set(json.loads(_in_a_fresh_interpreter(_SCAN_FOR_PLANNED_TYPES)))

    # `intent(` also matches a few non-type first arguments in other modules;
    # what matters is that nothing *unknown* survives the filter below, so the
    # test is stated as a subset rather than as an equality.
    unknown = {
        name for name in planned
        if name not in documents.declared_types()
        and name not in documents.reserved_types()
        and "_" in name  # snake_case names only; single words are not type keys
    }
    assert not unknown, (
        f"{sorted(unknown)} are planned somewhere and neither declared nor reserved"
    )
    assert documents.reserved_types().isdisjoint(documents.declared_types())


def test_an_authored_type_does_not_reach_the_next_world_built() -> None:
    """The contamination a process-global table makes possible, verified away.

    Built in this order deliberately: a stock world, then a pack world that
    installs a type, then a stock world again. If installation could reach a
    world that did not ask for it — through `standing`'s fallback, through
    `written_at`'s lag, through the planner — the third build would differ from
    the first, in the same process, with nothing in either corpus to notice by.
    """
    before = _manifest(_stock_world())
    _pack_world()
    assert STATEMENT in documents.declared_types()
    assert _manifest(_stock_world()) == before


def test_installing_the_same_type_twice_is_not_a_conflict() -> None:
    """A pack loaded twice, or a corpus rebuilt in the process that built it."""
    pack = packs.load(AUTHORED)
    doctypes.install(pack.artifact_types)
    doctypes.install(pack.artifact_types)
    assert doctypes.installed()[STATEMENT] == pack.artifact_types[0]


def test_a_type_that_redefines_an_engine_type_is_refused() -> None:
    """What `register_artifact_types` refuses, refused a line earlier and by name."""
    spec = doctypes.load([{
        "key": "cfo_variance_memo",
        "authority": "unofficial_note",
        "lifecycle": "draft",
    }])
    with pytest.raises(ValueError, match="already declared by a module"):
        doctypes.install(spec)


def test_a_reserved_name_is_refused() -> None:
    """The case the seam cannot catch, because nothing registered the name.

    `personnel_notice` is minted by `scenarios._personnel_notice` and declared
    by nobody, so there is no registered value for `register_artifact_types` to
    disagree with — a pack claiming it would set the standing of a succession
    announcement in a *different* corpus.
    """
    spec = doctypes.load([{
        "key": "personnel_notice",
        "authority": "approved_report",
        "lifecycle": "published",
    }])
    with pytest.raises(ValueError, match="reserved"):
        doctypes.install(spec)


def test_the_authored_filing_block_is_off_for_every_type_the_engine_declares() -> None:
    """Why the generic block in `planning` is a no-op on every shipped build.

    It iterates the lore's filing asks and skips every type that plans itself
    in code. All thirty do, so the loop's body is never entered unless a pack
    put a type in the tables.
    """
    for artifact_type in sorted(documents.declared_types()):
        if artifact_type in doctypes.installed():
            continue
        assert documents.filing_plan(artifact_type) is None, artifact_type


def test_two_builds_of_an_authored_type_agree_exactly() -> None:
    """No clock, no `random`, no set iteration deciding an id."""
    assert _manifest(_pack_world()) == _manifest(_pack_world())


def test_an_authored_type_rebuilds_from_the_recipe_with_no_pack_file() -> None:
    """The determinism argument, end to end.

    The types travel inside the pack, the pack is embedded verbatim in the
    recipe, and the recipe travels with the corpus — so a process holding only
    the corpus registers the same types before compiling it. This is the whole
    reason they are not a `--doctypes` flag.
    """
    from worldloom import recipe as recipe_module

    world = _pack_world()
    document = json.loads(json.dumps(world.recipe))
    assert STATEMENT in {
        spec["key"] for spec in document["pack"]["artifact_types"]
    }

    rebuilt = recipe_module.rebuild(document)
    assert [i.artifact_type for i in rebuilt.artifact_intents] == [
        i.artifact_type for i in world.artifact_intents
    ]


# ---------------------------------------------------------------------------
# The authored type, end to end
# ---------------------------------------------------------------------------


def test_an_authored_type_reaches_a_plan_a_document_and_word() -> None:
    """Every seam between "a model wrote JSON" and "a reader has the file".

    Each assertion below is a different seam, and each was a place the path
    could have stopped: lore has to reach the planner, the planner has to mint
    an intent for a type it does not name, the compiler has to find an outline,
    `standing` has to carry the authored authority rather than its fallback,
    `written_at` has to carry the authored lag, and the renderer has to have
    been told this is a document.
    """
    world = _pack_world().compile()
    planned = [i for i in world.artifact_intents if i.artifact_type == STATEMENT]
    assert len(planned) == 1
    intent = planned[0]

    ir = next(ir for ir in world.artifact_irs if ir.intent_id == intent.id)
    assert [section.heading for section in ir.sections if not section.hidden] == [
        "Network position", "By trading division", "Basis of this statement",
    ]
    assert ir.title == "Franchisee Trading Statement"

    entry = next(e for e in world.artifacts if e.id == intent.id)
    assert (entry.authority.value, entry.lifecycle.value) == ("approved_report", "published")
    newest = max(
        world.facts.by_id(f).valid_from for f in intent.required_fact_ids
    )
    assert entry.created_at == newest + timedelta(hours=20)

    assert STATEMENT in docx_render.HANDLES
    assert STATEMENT not in markdown_render._OWNED_ELSEWHERE

    report = world.validate()
    assert report.ok, report.violations


def test_the_lore_gate_is_what_decides_it_is_filed() -> None:
    """An authored type is declared always and planned only when asked for.

    The filing block reads the same summed `artifact_density` adjustment the
    four owner reports read (`scenarios.filings`), so a company that authors a
    document type and never claims to file it gets no documents — which is what
    makes the type a *vocabulary* rather than a template every world runs.
    """
    document = json.loads(AUTHORED.read_text(encoding="utf-8"))
    document["lore"] = [
        commitment for commitment in document["lore"]
        if not any(
            c["target"].startswith("filing/") for c in commitment["constrains"]
        )
    ]
    pack = packs.load(document)
    world = RetailWorld.from_pack(pack, seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    assert STATEMENT in documents.declared_types()
    assert STATEMENT not in Counter(i.artifact_type for i in world.artifact_intents)


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def test_the_shipped_authored_example_lints_clean() -> None:
    """The example an author copies has to be the one the lint approves of."""
    assert packs.lint(packs.load(AUTHORED)) == []


#: One phrase per rule, and the phrase is the part of the finding that names the
#: mistake rather than the part that explains it. Stated here rather than derived
#: from `doctypes.lint` for the reason `test_filings.FILING_TYPES` is: a test
#: that read the answer out of the thing it tests would pass on a lint that
#: checked nothing.
LINT_RULES = {
    "reserved_key": "is reserved",
    "redeclares_engine_type": "already declared by a module",
    "duplicate_key": "was already declared at index",
    "no_sections": "declares no sections",
    "duplicate_heading": "repeats the heading of section",
    "reserved_heading": "appends a section of its own under this heading",
    "unknown_fact_kind": "no document this engine declares is written about",
    "unscoped_kinds": "over kinds that no declared outline scopes by subject",
    "restates_itself": "the document restates itself",
    "not_a_word_document": "`word` is false",
    "no_filing": "declares no `filing`",
    "unknown_fact_bundle": "the planner computes a closed set",
    "unknown_audience": "is not one of the access classes core maps by name",
    "unknown_role": "names no retail role",
    "no_fallback_role": "no `fallback_role`",
    "lag_past_the_ceiling": "is later than every filing the engine plans",
    "filing_names_no_type": "names no artifact type",
}


@pytest.mark.parametrize("rule", sorted(LINT_RULES))
def test_every_lint_rule_fires_on_the_broken_example(rule: str) -> None:
    """One test per rule, so a regression names the rule it lost.

    `franchise-network-broken.json` is wrong in every way the lint knows about,
    at once, and that is deliberate: the rules interact — a type with no
    sections is also a type with no filing — and a fixture per rule would never
    have exercised the interaction.
    """
    findings = packs.lint(packs.load(BROKEN))
    phrase = LINT_RULES[rule]
    assert any(phrase in finding for finding in findings), (
        f"no finding matched {phrase!r}; got:\n" + "\n".join(findings)
    )


def test_the_broken_example_still_loads() -> None:
    """A lint that cannot be run on a wrong document is not a lint.

    Everything above is a *semantic* finding, so it belongs in `lint` and not in
    a model validator: `worldloom pack check` has to be able to read a pack that
    is wrong and say how, which it cannot do if the schema refused it first.
    """
    pack = packs.load(BROKEN)
    assert len(pack.artifact_types) == 5


def test_installing_the_broken_example_is_refused() -> None:
    """Advisory findings, and two that are not.

    A lint is advisory here for the same reason it is in `packs.lint` — an
    inert constraint is legal and an author may know something the tool does
    not. Name collision is the exception, because its consequence lands on
    somebody else's corpus.
    """
    with pytest.raises(ValueError):
        doctypes.install(packs.load(BROKEN).artifact_types)


# ---------------------------------------------------------------------------
# The registry, audited
# ---------------------------------------------------------------------------


def test_the_registry_audit_names_only_the_types_that_have_no_word_form() -> None:
    """The rule the seven conditional filings shipped without.

    They were declared, planned, compiled, and absent from
    `render.docx.HANDLES`, so Word and PDF skipped them silently —
    `docx.py`'s own comment records the fix and nothing recorded the rule. This
    is the rule, pinned to the set that legitimately has no Word form, so that
    the thirty-first type cannot join it quietly.

    Four of the five are records of a conversation or a page whose native form
    is markup, which is the honest answer for them. `unit_close_commentary` is
    not: it is a memo a finance business partner writes and forwards to a
    divisional MD, and it has no Word form because nobody registered it. That
    is a real gap in a renderer this change does not own, recorded here rather
    than papered over.
    """
    ported = {spec.key for spec in doctypes.load(CORE)}
    reported = {finding.split(":")[0] for finding in doctypes.audit()}
    # Restricted to the thirty this change ported, so a vertical landing
    # afterwards is neither pinned by this test nor able to hide behind it —
    # its own types are its own module's business, and `audit()` names them.
    assert reported & ported == {
        "confluence_page", "email_thread", "meeting_minutes",
        "routine_notice", "unit_close_commentary",
    }


def test_the_access_classes_the_lint_knows_are_ones_a_world_actually_resolves() -> None:
    """The audience rule's own evidence, taken from a world rather than asserted.

    Read out of `_policy_for`'s own table rather than probed against a built
    world, because probing cannot tell a *mapped* audience from one that landed
    on the fallback and happened to want that policy anyway — and it is exactly
    the audiences that fall to the fallback the rule exists to warn about. A
    class this list carries and the table has dropped would make the lint
    approve an audience that locks an author out of their own document.
    """
    from worldloom import world as world_module

    source = pathlib.Path(world_module.__file__).read_text(encoding="utf-8")
    table = source.partition("    def _policy_for(")[2].partition("\n    def ")[0]
    for audience in sorted(doctypes.ACCESS_CLASSES):
        assert f'"{audience}":' in table, audience


def test_the_filing_bundles_the_lint_knows_are_the_ones_the_planner_computes() -> None:
    """The two halves of a closed vocabulary, checked against each other.

    `doctypes` lints a filing's `facts` against `planning.FILING_BUNDLES`, and
    the planner resolves them from a dict written twenty lines away from it. A
    bundle in one and not the other is a filing that lints clean and cites
    nothing, which raises in `written_at` — at build time, in somebody else's
    corpus.
    """
    source = pathlib.Path(planning.__file__).read_text(encoding="utf-8")
    resolved = source.partition("    bundles = {")[2].partition("}")[0]
    named = {line.split('"')[1] for line in resolved.splitlines() if '"' in line}
    assert named == set(planning.FILING_BUNDLES)
