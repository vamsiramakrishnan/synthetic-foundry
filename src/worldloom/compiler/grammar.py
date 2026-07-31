"""Artifact grammars.

A component sequence can satisfy every local constraint and still be a document
no company would issue. A close pack that opens with the remediation table, or a
memo that requests a decision before establishing what the decision is about, is
locally valid at every step and globally absurd. Local compatibility cannot catch
that, because the defect is in the shape of the whole.

So each artifact type declares an expected shape, and a sequence is checked
against it. The rules are deliberately weak — required roles, forbidden openings,
ordering between roles, and a cap — rather than a full context-free grammar with
a parser. A CFG would be more expressive and would mostly be used to express
things the component registry already says, and the failure mode of an
over-specified grammar is that every new artifact needs a grammar change before
it can exist.

The check reports *every* violation rather than the first. Same reason the
narrative handshake reviews the whole response set: an author who fixes one
ordering problem, resubmits, and is told about the next one learns the rules one
round trip at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .components import component


@dataclass(frozen=True)
class GrammarViolation:
    """One way a component sequence fails its artifact type."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.detail}"


@dataclass(frozen=True)
class Grammar:
    """The expected shape of one artifact type."""

    artifact_type: str
    opens_with: frozenset[str] = frozenset()
    """Roles any of which may open. Empty means unconstrained."""
    requires_roles: frozenset[str] = frozenset()
    """Roles that must appear. A close pack without evidence is not a close pack."""
    forbids_roles: frozenset[str] = frozenset()
    ordered_roles: tuple[tuple[str, str], ...] = ()
    """``(earlier, later)`` pairs. If both appear, the first must come first."""
    max_components: int | None = None
    min_components: int = 1

    def check(
        self,
        component_ids: list[str],
        selected_roles: list[str] | None = None,
    ) -> list[GrammarViolation]:
        """Every way this sequence fails to be a valid artifact of this type.

        ``selected_roles`` is the role each component was actually chosen to
        play, parallel to *component_ids*. Supply it whenever it is known —
        which the composer always does, because a beat names the role it needs.

        Without it, a component is treated as filling every role it declares,
        and that reads violations that are not there. ``core.schedule`` fills
        both ``chronology`` and ``management``; an RCA that opens its timeline
        with one is playing chronology, but a check over declared roles sees
        ``management`` appear before ``explanation`` and reports the document
        out of order. The sequence was right and the grammar was wrong.

        The permissive fallback is still the correct default: a caller holding
        only a list of component ids genuinely does not know which role each was
        for, and guessing one would be worse than considering all of them.
        """
        violations: list[GrammarViolation] = []
        specs = [component(cid) for cid in component_ids]
        if selected_roles is not None and len(selected_roles) != len(specs):
            raise ValueError(
                f"selected_roles has {len(selected_roles)} entries for"
                f" {len(specs)} components; they must be parallel"
            )
        roles: list[frozenset[str]] = (
            [frozenset({role}) for role in selected_roles]
            if selected_roles is not None
            else [spec.semantic_roles for spec in specs]
        )
        present: set[str] = set().union(*roles) if roles else set()

        if len(specs) < self.min_components:
            violations.append(GrammarViolation(
                "too_few_components",
                f"{self.artifact_type} needs at least {self.min_components}, got {len(specs)}",
            ))
        if self.max_components is not None and len(specs) > self.max_components:
            violations.append(GrammarViolation(
                "too_many_components",
                f"{self.artifact_type} allows at most {self.max_components}, got {len(specs)}",
            ))

        if self.opens_with and specs and not (roles[0] & self.opens_with):
            violations.append(GrammarViolation(
                "wrong_opening",
                f"{specs[0].component_id} opens the artifact but fills none of"
                f" {sorted(self.opens_with)}",
            ))

        for role in sorted(self.requires_roles - present):
            violations.append(GrammarViolation(
                "missing_role", f"{self.artifact_type} requires a component filling {role!r}"
            ))
        for role in sorted(self.forbids_roles & present):
            violations.append(GrammarViolation(
                "forbidden_role", f"{self.artifact_type} may not contain {role!r}"
            ))

        # Ordering is checked on *first* appearance of each role. A role that
        # recurs later is normal — evidence appears throughout — and requiring
        # every occurrence to follow would forbid the ordinary shape where a
        # decision is argued, then supported by more evidence.
        def first(role: str) -> int | None:
            for index, owned in enumerate(roles):
                if role in owned:
                    return index
            return None

        for earlier, later in self.ordered_roles:
            head, tail = first(earlier), first(later)
            if head is not None and tail is not None and tail < head:
                violations.append(GrammarViolation(
                    "out_of_order",
                    f"{later!r} appears at position {tail} before {earlier!r} at {head}",
                ))

        # The per-component precondition from the registry. Checked here rather
        # than in `components` because it is a statement about a sequence, and a
        # component on its own has no position.
        for index, spec in enumerate(specs):
            needed = spec.requires_predecessor_role
            if needed is None:
                continue
            if not any(needed in earlier for earlier in roles[:index]):
                violations.append(GrammarViolation(
                    "missing_precondition",
                    f"{spec.component_id} at position {index} needs a {needed!r}"
                    " component before it",
                ))

        return violations


#: The grammars, one per artifact type that has an opinion. An artifact type with
#: no entry is unconstrained beyond its components' own compatibility — which is
#: the honest default, because inventing a shape for an artifact nobody has built
#: yet is how a grammar becomes a straitjacket.
GRAMMARS: dict[str, Grammar] = {
    "cfo_variance_memo": Grammar(
        artifact_type="cfo_variance_memo",
        opens_with=frozenset({"position", "summary"}),
        requires_roles=frozenset({"position", "evidence"}),
        ordered_roles=(("position", "explain_change"), ("evidence", "decision")),
        min_components=2,
    ),
    "executive_summary": Grammar(
        artifact_type="executive_summary",
        opens_with=frozenset({"position", "summary"}),
        requires_roles=frozenset({"summary"}),
        # An executive summary that carries the control detail is not a summary.
        forbids_roles=frozenset({"control", "provenance"}),
        max_components=4,
    ),
    "incident_rca": Grammar(
        artifact_type="incident_rca",
        opens_with=frozenset({"summary", "chronology"}),
        requires_roles=frozenset({"chronology", "explanation", "management"}),
        ordered_roles=(
            ("chronology", "explanation"),
            ("explanation", "management"),
        ),
        min_components=3,
    ),
    "finance_workbook": Grammar(
        artifact_type="finance_workbook",
        requires_roles=frozenset({"evidence", "control"}),
        # A workbook whose totals nobody checks is a spreadsheet, not a model.
        ordered_roles=(("evidence", "control"),),
        min_components=2,
    ),
    "working_note": Grammar(
        artifact_type="working_note",
        # A controller's own note is always dated in its thinking: it opens
        # from wherever the close stands, never from an already-drawn
        # conclusion.
        opens_with=frozenset({"chronology"}),
        requires_roles=frozenset({"chronology", "evidence"}),
        # "Not a report" (its own purpose text, in `documents._OUTLINES`) is a
        # real constraint, not colour: a working note is never the place a
        # decision gets made or a control gets signed off, because it is
        # provisional and personal, not an artifact anyone downstream relies
        # on.
        forbids_roles=frozenset({"decision", "control"}),
        min_components=2,
    ),
    "close_calendar": Grammar(
        artifact_type="close_calendar",
        opens_with=frozenset({"chronology"}),
        # Only `chronology` is required, not `management` — a close calendar's
        # "Commitment" section is guaranteed every period; its "Escalation"
        # section exists only when the date actually moved
        # (`documents._OUTLINES["close_calendar"]`), and a period that closed
        # on time is not a defective calendar entry for lacking one. The
        # ordering below is still stated outright: *if* an escalation is
        # reported, it is reported after the commitment it revises, in every
        # period that has one.
        requires_roles=frozenset({"chronology"}),
        ordered_roles=(("chronology", "management"),),
        min_components=1,
    ),
    "confluence_page": Grammar(
        artifact_type="confluence_page",
        opens_with=frozenset({"position"}),
        requires_roles=frozenset({"position", "management"}),
        ordered_roles=(("position", "management"),),
        # The defining property of this artifact type, stated in its own
        # purpose text: "it knows the symptom and the first guess and nothing
        # more... this page is never updated". A triage page that stated a
        # confirmed root cause would be a page someone forgot to retire, not
        # a status update — `explanation` is what the incident RCA is for.
        forbids_roles=frozenset({"explanation"}),
        min_components=2,
    ),
    # `knowledge_article`, `servicenow_incident`, and `jira_issues` are
    # deliberately left without a grammar entry here — see this module's own
    # docstring on why an ungrammared type is the honest default rather than
    # an oversight, and the specific reasoning for each below.
    #
    # `servicenow_incident` and `jira_issues` both compose today from
    # `documents._DEFAULT_OUTLINE` — a single generic "Summary" section
    # (`documents._OUTLINES` has no entry for either). That is not a shape;
    # it is the *absence* of one, identical to what any other unlisted
    # artifact type would get. Stating a grammar would mean inventing a
    # structure neither type's outline actually has.
    #
    # `knowledge_article` does have a genuine, statable shape — symptom
    # (`evidence`), then cause (`explanation`), then procedure (`management`)
    # — but stating it here would trip a real defect rather than describe a
    # real rule. `ops.causal_chain` is the only component that fills
    # `explanation` at the row counts a knowledge article's "Cause" section
    # actually carries, in every non-xlsx format, and it declares
    # `requires_predecessor_role="chronology"` — a constraint that is true for
    # an incident RCA (which always has a preceding Timeline) and not true for
    # a knowledge article (whose outline has no chronology section at all).
    # `compose.compose` selects a component by format/density/row fit alone,
    # with no view of which artifact type is asking, so it cannot prefer a
    # different `explanation` component for a knowledge article than it picks
    # for an RCA — the same atom is selected either way, and only a grammar
    # entry would notice the precondition it fails to meet
    # (`Grammar.check`'s per-component precondition scan runs whenever an
    # artifact type has a `Grammar` at all, independent of what that grammar
    # otherwise requires). Adding the grammar without also fixing that would
    # freeze a `missing_precondition` violation into every knowledge article
    # this corpus ever produces. The honest fix is upstream of this file —
    # either a context-aware composer or a second, precondition-free
    # `explanation` atom that does not collide with `ops.causal_chain`'s own
    # coverage — and neither belongs to a grammar declaration. Left
    # unconstrained until one of those lands.
}


def check(
    artifact_type: str,
    component_ids: list[str],
    selected_roles: list[str] | None = None,
) -> list[GrammarViolation]:
    """Every way *component_ids* fails to be a valid *artifact_type*.

    An unknown artifact type is not a violation. Artifact types are added by
    scenarios and grammars are added when a type has a shape worth stating, and
    coupling the two would mean no new artifact could exist without one.
    """
    grammar = GRAMMARS.get(artifact_type)
    if grammar is None:
        return []
    return grammar.check(component_ids, selected_roles)


__all__ = ["GRAMMARS", "Grammar", "GrammarViolation", "check"]
