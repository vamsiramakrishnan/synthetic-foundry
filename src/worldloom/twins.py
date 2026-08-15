"""Counterfactual twins: one world, one declared intervention, a measured delta.

A corpus can already prove *coherence* (validate) and *reproducibility* (the
recipe and ledger rebuild it byte-for-byte). What it could not do is answer a
causal question: *what in this corpus is the way it is because of that one
parameter?* Two seeds differ everywhere at once, so comparing them attributes
nothing. A twin is a rebuild of the same recipe with exactly one recorded value
replaced — the source of variation is known by construction, because
``recipe.rebuild`` is a pure function of ``(recipe, ledger)``, so every row that
differs between the two worlds differs *because of the intervention* and every
row that is byte-identical was untouched by it.

The delta is **measured, never predicted**. Nothing here models a dependency
graph; the two worlds are rebuilt and diffed at the same representation the
corpus ships in — ``json.dumps(model.model_dump(mode="json"), sort_keys=True)``,
the exact line ``corpus.write_jsonl`` writes — so "unchanged" means the jsonl
line is the same bytes, not that a count matched.

**Why cardinality changes are refused rather than diffed.** Ids are minted
sequentially (``ids.Minter`` counts per prefix), so an intervention that changes
*how many* facts, documents or questions exist — a policy level that adds five
standing documents, an incident switched off — reshuffles every later id. After
a reshuffle, aligning FACT-0400 with FACT-0400 compares two unrelated rows, and
a diff computed anyway would label unrelated changes as caused. Measured on
seed 8128: ``policies`` ``core → full`` moves facts 631 → 652 and every
artifact id after the insertion point names a different document. So ``twin``
detects the reshuffle (id sequences compared per stream, before any row diff)
and refuses with the cause on the manifest. A refusal with a reason is the v1
contract for that intervention class; an id-matching layer that could survive
insertion is the recorded next increment, not something to half-build here.

Two measured surprises worth knowing before writing an intervention:

* **An intervention can be absorbed.** Widening the *high* endpoint of an
  integer range changed nothing at seed 8128: ``ops.incident.affected_records``
  high 27,000 → 30,000 left all 615 facts byte-identical, because
  ``random.Random.randint`` rejection-samples at the range's bit width (both
  widths need 15 bits) and the accepted draw was the same. The manifest honestly
  reports zero changes — a twin can measure that an intervention did nothing,
  which is itself the answer to a causal question. Continuous (``number``)
  parameters scale the draw by ``high - low`` and are moved by any endpoint
  change.
* **The engine's own invariants still apply to the patched recipe.** A single
  seasonality month cannot be intervened on: the trading year must average one
  (``profiles.Seasonality``), so the patched recipe fails to load and
  ``recipe.rebuild`` raises ``RecipeError`` before any world exists. That is an
  error, not a refusal — the intervention did not produce a buildable world, so
  there is nothing to measure. The twinnable unit is the whole ``index``
  mapping, re-normalised by the caller.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .ids import content_key
from .recipe import rebuild

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


class TwinError(Exception):
    """Raised when an intervention cannot even be *stated* against this recipe.

    Distinct from a refusal on purpose. A refusal (``DeltaManifest.refused``) is
    a measurement: both worlds were built and the intervention turned out to
    change what exists. A ``TwinError`` means no second world was built at all —
    the path does not resolve, or the segment grammar is wrong — which is a
    caller error, not a finding about the intervention class.
    """


@dataclass(frozen=True)
class Intervention:
    """One replacement value at one path into a recorded recipe.

    ``path`` is slash-separated, **not** dot-separated, and that is load-bearing
    rather than taste: physics parameter names are themselves dotted
    (``retail.margin.erosion`` is one key of the recipe's ``physics`` mapping),
    so a dotted path grammar could not address them at all. Segments index
    mappings by key and lists by integer::

        physics/retail.margin.erosion/high      a recorded physics endpoint
        steps/0/trend_pct                       a recorded scenario argument
        policies                                the recorded policy level
        seasonality/index                       the whole recorded trading year

    Only ``value`` (the *after*) is supplied. The *before* is read off the
    recipe by ``twin`` rather than accepted from the caller, because the record
    is the authority on what the base world was built with — a caller-supplied
    "before" that disagreed with the recipe would make the manifest lie about
    its own baseline. The identity control (before == after) therefore needs no
    special casing: patch the recorded value with itself and measure zero.
    """

    path: str
    value: Any


#: The streams a corpus persists, grouped as the manifest reports them. Each
#: entry is (manifest group, World attribute). Exhaustive over what ``export``
#: writes on purpose: a stream left out of this table would be a place a twin
#: could differ from its base silently, and "everything outside the intervention
#: is identical" is only a claim if everything was actually compared.
#: ``artifacts`` appears three times because one ART id has three persisted
#: rows — the planned intent, the compiled IR, and the manifest entry — and a
#: change in any of them is a change to that document.
_STREAMS: tuple[tuple[str, str], ...] = (
    ("facts", "_facts"),
    ("events", "_events"),
    ("artifacts", "_artifact_intents"),
    ("artifacts", "_artifact_irs"),
    ("artifacts", "_artifacts"),
    ("evaluations", "_evaluations"),
    ("entities", "_business_units"),
    ("entities", "_people"),
    ("entities", "_systems"),
    ("entities", "_services"),
    ("entities", "_cost_centres"),
    ("entities", "_categories"),
    ("entities", "_sites"),
    ("entities", "_personas"),
    ("entities", "_access_policies"),
    ("entities", "_lore"),
    # Everything else a corpus writes: transaction detail, labelled
    # imperfections, the knowledge ledgers. Usually empty, diffed anyway —
    # see the comment above the table.
    ("records", "_detail_tables"),
    ("records", "_intentional_errors"),
    ("records", "_observations"),
    ("records", "_messages"),
    ("records", "_tasks"),
    ("records", "_actor_ledger"),
)


@dataclass(frozen=True)
class DeltaManifest:
    """What the intervention changed, measured jsonl-row by jsonl-row.

    ``changed_*_ids`` are in stream order — the order the rows sit in the
    corpus files — not sorted-set order, so the manifest is deterministic
    without ever iterating a set into output. ``unchanged_counts`` is the
    denominator that makes a locality claim checkable: "38 facts changed" means
    nothing until "577 did not" sits beside it.

    ``changed_entity_ids`` and the ``records`` group extend the four streams
    the twin contract names, and the extension is the honest direction: entity
    rows and the auxiliary ledgers are persisted corpus content too, and a
    manifest that did not compare them would leave places a twin could differ
    silently.
    """

    base_recipe_digest: str
    intervention: dict[str, Any]
    changed_fact_ids: tuple[str, ...] = ()
    changed_event_ids: tuple[str, ...] = ()
    changed_artifact_ids: tuple[str, ...] = ()
    changed_evaluation_ids: tuple[str, ...] = ()
    changed_entity_ids: tuple[str, ...] = ()
    changed_record_ids: tuple[str, ...] = ()
    unchanged_counts: Mapping[str, int] = field(default_factory=dict)
    refused: str | None = None

    @property
    def is_null(self) -> bool:
        """True when the intervention changed nothing at all.

        Named because it is a *finding*, not a degenerate case: an absorbed
        intervention (see the module docstring) and the identity control both
        land here, and "this parameter did not reach anything" is an answer.
        """
        return self.refused is None and not (
            self.changed_fact_ids or self.changed_event_ids
            or self.changed_artifact_ids or self.changed_evaluation_ids
            or self.changed_entity_ids or self.changed_record_ids
        )

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON, stable key order, for a sidecar or a CLI ``--json``."""
        return {
            "base_recipe_digest": self.base_recipe_digest,
            "intervention": dict(self.intervention),
            "changed_fact_ids": list(self.changed_fact_ids),
            "changed_event_ids": list(self.changed_event_ids),
            "changed_artifact_ids": list(self.changed_artifact_ids),
            "changed_evaluation_ids": list(self.changed_evaluation_ids),
            "changed_entity_ids": list(self.changed_entity_ids),
            "changed_record_ids": list(self.changed_record_ids),
            "unchanged_counts": {k: self.unchanged_counts[k]
                                 for k in sorted(self.unchanged_counts)},
            "refused": self.refused,
        }


@dataclass(frozen=True)
class TwinResult:
    """A counterfactual world beside the base it varies from, and the delta.

    ``base`` rides along even though the caller supplied the recipe that built
    it, because the manifest's claims are only checkable against the exact
    world they were measured on — a caller re-deriving the base separately and
    comparing against *that* would be trusting two rebuilds to agree, which is
    precisely the thing this module exists to measure rather than assume.

    ``world`` is present even on a refusal: the counterfactual is a real,
    coherent world either way. What a refusal withdraws is the *causal
    labelling* — which rows changed because of the intervention — not the
    world itself.
    """

    base: World
    world: World
    manifest: DeltaManifest


def _row(model: Any) -> str:
    """One persisted line, exactly as ``corpus.write_jsonl`` spells it.

    The diff must happen at the corpus's own representation, not at Python
    equality: two models could compare equal while serialising differently (a
    float that prints two ways), and the promise being measured is about the
    bytes a reader of the corpus gets.
    """
    return json.dumps(model.model_dump(mode="json"), sort_keys=True)


def _patched(recipe: dict[str, Any], intervention: Intervention) -> tuple[Any, dict[str, Any]]:
    """The recorded *before* at the intervention's path, and the patched recipe.

    Strict: every segment must resolve and the final key must already exist.
    An intervention is a claim about a value the base world was built with; a
    path that *creates* a key would be a claim about a value the record never
    held, and its "before" would be an invention. (The engine's defaults are
    real values too, but they are the registry's, not this recipe's — record
    them at build time if you want to intervene on them.)
    """
    patched = copy.deepcopy(recipe)
    segments = intervention.path.split("/")
    if not all(segments):
        raise TwinError(f"malformed intervention path {intervention.path!r}:"
                        " empty segment")

    def _key(node: Any, segment: str) -> Any:
        if isinstance(node, list):
            try:
                index = int(segment)
            except ValueError:
                raise TwinError(
                    f"path {intervention.path!r}: segment {segment!r} indexes a"
                    " list and must be an integer"
                ) from None
            if not 0 <= index < len(node):
                raise TwinError(
                    f"path {intervention.path!r}: index {index} is outside this"
                    f" list of {len(node)}"
                )
            return index
        if isinstance(node, dict):
            if segment not in node:
                raise TwinError(
                    f"path {intervention.path!r}: {segment!r} is not recorded"
                    f" here — recorded keys: {', '.join(sorted(node)) or '(none)'}"
                )
            return segment
        raise TwinError(
            f"path {intervention.path!r}: segment {segment!r} descends into a"
            f" {type(node).__name__}, which has no children"
        )

    node: Any = patched
    for segment in segments[:-1]:
        node = node[_key(node, segment)]
    leaf = _key(node, segments[-1])
    before = copy.deepcopy(node[leaf])
    node[leaf] = copy.deepcopy(intervention.value)
    return before, patched


def _grouped(world: World) -> dict[str, list[tuple[str, str]]]:
    """Every persisted row of *world*, grouped and in stream order: (id, line)."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for group, attribute in _STREAMS:
        rows = grouped.setdefault(group, [])
        rows.extend((model.id, _row(model)) for model in getattr(world, attribute))
    # The company is one row of world.json, not a stream, but it is persisted
    # corpus content like any other entity — a twin that renamed the company
    # while every list matched would otherwise measure as identical.
    grouped["entities"].append((world.company.id, _row(world.company)))
    return grouped


def twin(
    recipe: dict[str, Any],
    ledger: tuple,
    intervention: Intervention,
) -> TwinResult:
    """Build the counterfactual world one intervention away, and measure the delta.

    Both worlds — base and counterfactual — go through ``recipe.rebuild`` with
    nothing but the recipe and the ledger. The base is *not* accepted as a
    prebuilt ``World`` from the caller, and that is the P1 lesson from
    ``tests/test_recipe_structure.py`` applied here: a caller-supplied base was
    built by some path that may have re-supplied flags the recipe never
    recorded, and a delta measured against it would attribute the recording
    gap to the intervention. Rebuilding both sides from the record is what
    makes "the only source of variation is the intervention" true by
    construction rather than by hope.

    Raises ``TwinError`` for a path that does not resolve, and lets
    ``recipe.RecipeError`` propagate when the patched recipe is one the engine
    itself refuses to load — an unbuildable counterfactual is an error, not a
    measurement. A cardinality change is neither: both worlds built, the
    measurement happened, and its result is the refusal on the manifest.
    """
    digest = content_key(json.dumps(recipe, sort_keys=True))
    before, patched = _patched(recipe, intervention)
    stated = {"path": intervention.path, "before": before, "after": intervention.value}

    base = rebuild(recipe, ledger=ledger).compile()
    counterfactual = rebuild(patched, ledger=ledger).compile()

    base_rows = _grouped(base)
    twin_rows = _grouped(counterfactual)

    # The cardinality gate, before any row is diffed. Sequences, not sets and
    # not counts: an equal count with reordered ids is still a reshuffle, and a
    # diff over it would compare unrelated rows under matching ids.
    reshuffled = [
        f"{group} {len(base_rows[group])} -> {len(twin_rows[group])}"
        for group in ("facts", "events", "artifacts", "evaluations", "entities", "records")
        if [row_id for row_id, _ in base_rows[group]]
        != [row_id for row_id, _ in twin_rows[group]]
    ]
    if reshuffled:
        return TwinResult(
            base=base,
            world=counterfactual,
            manifest=DeltaManifest(
                base_recipe_digest=digest,
                intervention=stated,
                refused=(
                    "this intervention changes what exists, not what is true"
                    f" about it ({'; '.join(reshuffled)}). Ids are minted"
                    " sequentially, so locality cannot hold: a twin that"
                    " silently realigned the reshuffled ids would label"
                    " unrelated changes as caused. Refusing is the v1 contract"
                    " for this intervention class."
                ),
            ),
        )

    changed: dict[str, tuple[str, ...]] = {}
    unchanged: dict[str, int] = {}
    for group in ("facts", "events", "artifacts", "evaluations", "entities", "records"):
        # One ART id carries up to three rows (intent, IR, manifest); a dict
        # keyed by id collapses them so a document changed in any of its rows
        # is named once, in first-appearance order.
        differs: dict[str, bool] = {}
        for (row_id, base_line), (_, twin_line) in zip(
            base_rows[group], twin_rows[group], strict=True
        ):
            differs[row_id] = differs.get(row_id, False) or base_line != twin_line
        changed[group] = tuple(row_id for row_id, moved in differs.items() if moved)
        unchanged[group] = sum(1 for moved in differs.values() if not moved)

    return TwinResult(
        base=base,
        world=counterfactual,
        manifest=DeltaManifest(
            base_recipe_digest=digest,
            intervention=stated,
            changed_fact_ids=changed["facts"],
            changed_event_ids=changed["events"],
            changed_artifact_ids=changed["artifacts"],
            changed_evaluation_ids=changed["evaluations"],
            changed_entity_ids=changed["entities"],
            changed_record_ids=changed["records"],
            unchanged_counts=unchanged,
        ),
    )


__all__ = ["DeltaManifest", "Intervention", "TwinError", "TwinResult", "twin"]
