"""Choosing the values the catalogue deliberately threw away.

A phrasing is a real request with every value removed::

    "Create epics in {project} from the action items in the {meeting_title} notes"

The holes are :class:`~.catalogue.Slot`\\ s, each naming the step and the
argument its value was bound to. The value itself never left the customer's
environment, so the importer has to supply one.

Two properties matter more than the value being good.

**Determinism.** Every choice is seeded from a digest of fixed inputs, never
from a random number or the clock::

    seed = digest(["telemetry-bind/v1", catalogue digest, cuj id,
                   connector, entity, field])

Same catalogue in, same question text out, forever. A corpus whose questions
drift between runs cannot be compared with itself.

**No giveaways.** Four rules, in order::

    an id or a key     never — see below
    a person           don't name one; write the role, "the assignee"
    a closed list      pick by seed from the sorted options
    a container        a key-shaped name, "store ops" -> "STOREOPS"
    anything else      the journey's own vocabulary, from domain_terms

The first rule is the one with teeth. A question that says "comment on
OPS-412" has handed the agent the answer: the search step it was supposed to
perform is now pointless, while still sitting in the graph being graded. The
case scores work that never happened. Ids are also per-world — a question
naming OPS-412 only means anything against the one corpus that minted it.

So an id is never *written*. It is still *referred to*: the hole becomes
"the page", which is how a person asks for something they have not found
yet. The question survives and the search step stays worth performing.

Only the most-used phrasing is used. The rest are reported as
``phrasing_variant_unused``, because using them needs core change C4 (W9).
A journey with no usable phrasing at all is not a failure either — the
caller supplies a built-in workflow's template instead, recorded as
``phrasing_default_used``.

Where the options come from
---------------------------

Shipped connector definitions carry no field manifests — ``resolve_field``
returns ``None`` for every field of every shipped entity. So a type-driven
binder would have nothing to read. Four sources are tried in order, and only
the first exists when a connector pack supplies richer data::

    field manifest     resolve_field(...).options       packs only, today
    connector options  definition.options[name]         priority, severity
    workflow states    entity.workflow.states           status
    name heuristics    the four rules above             always available

Slots always point at real steps
--------------------------------

W2 matches a journey exactly as recorded or refuses it; it never removes a
step. So a slot's step exists, as ``inv3`` promised when the file was read,
and binding never has to redirect one.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..connector_definition import load_connector_definition
from ..models import Model
from ..providers import digest
from .report import Finding, info

if TYPE_CHECKING:

    from ..connector_definition import ConnectorDefinition
    from .catalogue import Cuj, Phrasing, Slot, Step


BIND_VERSION = "telemetry-bind/v1"
"""Namespace for every seed this module derives. Changing it rewrites every
question in every corpus, so it changes only when the rules do."""

PHRASING_DEFAULT_USED = "phrasing_default_used"
"""No phrasing could be used, so the caller must supply a built-in template.
Not a failure: ``text_policy: none`` and "every wording was too rare to be
safe to publish" both land here, and neither is the catalogue's fault."""

PHRASING_VARIANT_UNUSED = "phrasing_variant_unused"
"""A real wording the importer threw away. Only the most-used one is kept
until core change C4 (W9) can use the rest."""

#: Argument names that identify a record rather than describe one. Matched on
#: the whole name or as a suffix, so ``page_id`` and ``id`` both count but
#: ``identity`` does not.
_ID_WORDS = ("id", "ids", "key", "keys", "uuid", "guid", "arn", "urn")

#: Argument names that name a human. The value is a role, never a person: the
#: catalogue carries no names, and inventing one would read as evidence.
_PERSON_WORDS = ("assignee", "owner", "reporter", "user", "author", "creator",
                 "requester", "approver", "manager", "mentions")

#: What to write instead of naming somebody.
_PERSON_PHRASES = {
    "assignee": "the assignee",
    "owner": "the owner",
    "reporter": "the reporter",
    "author": "the author",
    "creator": "whoever created it",
    "requester": "the requester",
    "approver": "the approver",
    "manager": "their manager",
}

#: Slot names that hold a *container* a record lives in, rather than prose.
#: "Create epics in store ops" does not read like English; "in STOREOPS"
#: does, because a reader recognises the shape of a project key.
_CONTAINER_WORDS = ("project", "space", "board", "queue", "folder",
                    "workspace", "channel", "team", "repository", "repo")

#: How wide a derived container name may be. Not arbitrary: ``jira.json``
#: builds its own project values as ``{stream|upper|first:10}``, so this is
#: Worldloom's existing key shape rather than a new convention.
_KEY_WIDTH = 10

#: Last resort when a journey publishes no ``domain_terms``. Deliberately
#: bland: a reader should notice the catalogue said nothing, not be soothed.
_FALLBACK_TEXT = "the usual"

#: And for a container, when there is nothing to derive a name from.
_FALLBACK_KEY = "GENERAL"


class BindRule(StrEnum):
    """Which rule produced a value. Carried into the report, so a reader can
    see *why* a question says what it says."""

    OPTION = "option"
    """Chosen by seed from a closed list the connector declares."""

    PERSON = "person"
    """A role was described. Nobody was named."""

    REFERENCE = "reference"
    """An id was referred to rather than written — "the page". The record is
    identified by what it is, so the search for it is still worth doing."""

    KEY = "key"
    """A container's name, derived from the journey's vocabulary in the
    connector's own key shape."""

    TEXT = "text"
    """The journey's own vocabulary, chosen by seed."""


class Binding(Model):
    """One filled hole."""

    slot: str
    value: str
    rule: BindRule
    source: str = ""
    """Where a closed list came from, when one did."""

    connector: str = ""
    entity: str = ""
    field: str = ""
    """The step this value belongs to, *after* following any fold. The caller
    needs it to put the value in the right construction requirement — the
    question and the world have to agree on what exists."""


class BoundQuestion(Model):
    """A phrasing with every hole filled."""

    text: str
    template: str
    """The phrasing as the catalogue delivered it, holes and all."""
    support: int
    """Distinct sessions that phrasing was seen in. Why this one was picked."""
    bindings: tuple[Binding, ...] = ()


# --------------------------------------------------------------------------
# Seeding.
# --------------------------------------------------------------------------


def seed_for(catalogue_digest: str, cuj_id: str, connector: str, entity: str,
             field: str) -> int:
    """A stable seed for one field of one step of one journey.

    Everything that identifies the choice is in the digest, and nothing else
    is. Two catalogues that differ anywhere produce different values; the same
    catalogue produces the same ones on any machine, in any year.
    """
    return int(digest([BIND_VERSION, catalogue_digest, cuj_id, connector,
                       entity, field])[:16], 16)


def _pick(options: tuple[str, ...], seed: int) -> str:
    """One of *options*, chosen by *seed*. Sorted first, because the order a
    connector happens to declare its values in is not a decision anyone made,
    and relying on it would make the choice fragile."""
    return sorted(options)[seed % len(options)]


# --------------------------------------------------------------------------
# Classifying one argument name.
# --------------------------------------------------------------------------


def _words(name: str) -> tuple[str, ...]:
    return tuple(part for part in name.casefold().split("_") if part)


def names_an_id(name: str) -> bool:
    """Whether *name* identifies a record rather than describing one."""
    parts = _words(name)
    if not parts:
        return False
    return parts[-1] in _ID_WORDS or parts[0] in _ID_WORDS


def names_a_person(name: str) -> bool:
    """Whether *name* refers to a human."""
    return any(word in _words(name) for word in _PERSON_WORDS)


def _person_phrase(name: str) -> str:
    for word in _words(name):
        if word in _PERSON_PHRASES:
            return _PERSON_PHRASES[word]
    return "the assignee"


def names_a_container(name: str) -> bool:
    """Whether *name* holds something records live in, not prose."""
    return any(word in _words(name) for word in _CONTAINER_WORDS)


def _as_key(term: str) -> str:
    """*term* in the shape of a container name: ``store ops`` → ``STOREOPS``."""
    cleaned = "".join(character for character in term if character.isalnum())
    return cleaned.upper()[:_KEY_WIDTH] or _FALLBACK_KEY


def _container_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """The terms worth turning into a container name.

    Multi-word terms are preferred when any exist. A single word out of a
    journey's vocabulary tends to be jargon for the *work* — "epic",
    "sprint" — while a phrase tends to name the thing the work is about,
    which is what a project is usually called after.
    """
    phrases = tuple(term for term in terms if len(term.split()) > 1)
    return phrases or terms


# --------------------------------------------------------------------------
# Finding a closed list.
# --------------------------------------------------------------------------


def _definition(connector: str) -> ConnectorDefinition | None:
    try:
        return load_connector_definition(connector)
    except ValueError:
        return None


def _closed_list(connector: str, entity: str,
                 field: str) -> tuple[tuple[str, ...], str] | None:
    """The options *field* may take, and where they came from.

    Returns ``None`` when the field is not a closed list, which — with the
    connectors shipped today — is almost always.
    """
    definition = _definition(connector)
    if definition is None:
        return None

    try:
        declared = definition.resolve_field(entity, field)
    except KeyError:
        # An entity the connector does not know. W2 would have refused the
        # journey, so this is a slot pointing at a step from before a fold.
        return None
    if declared is not None and declared.options:
        return declared.options, "field manifest"

    folded = field.casefold()
    for name, options in definition.options.items():
        if name.casefold() == folded and options:
            return tuple(options), f"{connector}.options[{name!r}]"

    for member in _members(definition, entity):
        workflow = definition.entities[member].workflow
        if workflow is not None and workflow.field.casefold() == folded:
            return tuple(workflow.states), f"{connector}.{member} workflow"
    return None


def _members(definition: ConnectorDefinition, entity: str) -> tuple[str, ...]:
    try:
        return definition.entity_members(entity)
    except KeyError:
        return ()


# --------------------------------------------------------------------------
# Binding one slot.
# --------------------------------------------------------------------------


def _step_for(cuj: Cuj, step_id: str) -> Step | None:
    return next((step for step in cuj.steps if step.id == step_id), None)


def _reference(slot: Slot, step: Step | None) -> str:
    """What to say instead of writing an id: "the page", "the issue".

    A person asking for something they have not found yet names the *kind* of
    thing, not its key. So does the question.
    """
    noun = (step.entity if step is not None and step.entity else slot.name)
    for suffix in ("_id", "_ids", "_key", "_keys", "_uuid", "_guid"):
        noun = noun.removesuffix(suffix)
    return f"the {noun.replace('_', ' ')}" if noun else "the record"


def bind_slot(slot: Slot, cuj: Cuj, catalogue_digest: str) -> Binding:
    """A value for one hole. Never ``None``: every hole gets something.

    An id is the interesting case. It is never written, because a question
    naming OPS-412 grades a search the agent did not have to perform — but it
    is still *referred to*, so the question survives and the search stays
    worth doing.
    """
    field = slot.field
    step = _step_for(cuj, slot.step_id)
    connector = step.connector if step is not None and step.connector else ""
    entity = step.entity if step is not None and step.entity else ""
    seed = seed_for(catalogue_digest, cuj.id, connector, entity, field)

    where = {"connector": connector, "entity": entity, "field": field}

    if names_an_id(field):
        return Binding(slot=slot.name, value=_reference(slot, step),
                       rule=BindRule.REFERENCE, **where)

    if names_a_person(field):
        return Binding(slot=slot.name, value=_person_phrase(field),
                       rule=BindRule.PERSON, **where)

    if connector and entity:
        found = _closed_list(connector, entity, field)
        if found is not None:
            options, source = found
            return Binding(slot=slot.name, value=_pick(options, seed),
                           rule=BindRule.OPTION, source=source, **where)

    if names_a_container(slot.name) or names_a_container(field):
        terms = cuj.domain_terms or (_FALLBACK_KEY,)
        term = _pick(_container_terms(terms), seed)
        return Binding(slot=slot.name, value=_as_key(term), rule=BindRule.KEY,
                       source=f"derived from {term!r}", **where)

    terms = cuj.domain_terms or (_FALLBACK_TEXT,)
    return Binding(slot=slot.name, value=_pick(terms, seed),
                   rule=BindRule.TEXT, **where)


# --------------------------------------------------------------------------
# Binding a whole question.
# --------------------------------------------------------------------------


def _ordered(phrasings: tuple[Phrasing, ...]) -> list[Phrasing]:
    """Most-used first, ties broken by the template itself so the order never
    depends on how the file happened to be written."""
    return sorted(phrasings, key=lambda p: (-p.support, p.template))


def bind_question(cuj: Cuj, catalogue_digest: str,
                  ) -> tuple[BoundQuestion | None, tuple[Finding, ...]]:
    """Fill the most-used phrasing that can be filled completely.

    A partly-filled template is never returned. A question with a visible
    ``{slot}`` in it would be put to an agent as if it were English.

    ``None`` means no phrasing was usable and the caller should supply a
    built-in workflow's template instead. That is reported, not refused:
    ``text_policy: none`` and "every wording was too rare to publish safely"
    both end here, and neither is anybody's fault.
    """
    findings: list[Finding] = []
    chosen: BoundQuestion | None = None

    for phrasing in _ordered(cuj.phrasings):
        if chosen is not None:
            # A real wording we are not using. C4 (W9) is what uses them.
            findings.append(info(
                PHRASING_VARIANT_UNUSED,
                f"{cuj.id} also phrased this {phrasing.support} ways as "
                f"{phrasing.template!r}; only the most-used phrasing is "
                "written until core change C4",
                cuj_id=cuj.id,
                detail={"template": phrasing.template,
                        "support": str(phrasing.support)}))
            continue

        bindings = tuple(bind_slot(slot, cuj, catalogue_digest)
                         for slot in phrasing.slots)
        text = phrasing.template
        for binding in bindings:
            text = text.replace("{" + binding.slot + "}", binding.value)
        if "{" in text:
            # A template naming a slot it did not declare. ``inv3`` checks the
            # other direction, so this one is ours to catch.
            findings.append(info(
                PHRASING_VARIANT_UNUSED,
                f"{cuj.id} phrasing {phrasing.template!r} names a slot it "
                "does not declare, so it cannot be filled",
                cuj_id=cuj.id,
                detail={"template": phrasing.template, "reason": "undeclared"}))
            continue
        chosen = BoundQuestion(text=text, template=phrasing.template,
                               support=phrasing.support, bindings=bindings)

    if chosen is not None:
        return chosen, tuple(findings)

    return None, (*findings, info(
        PHRASING_DEFAULT_USED,
        f"{cuj.id} has no usable phrasing, so the question comes from the "
        "closest built-in workflow instead of from real wording",
        cuj_id=cuj.id,
        detail={"phrasings": str(len(cuj.phrasings))}))


# --------------------------------------------------------------------------
# From a question to a template Worldloom can fill.
# --------------------------------------------------------------------------
#
# The bound question is not the end of it. Worldloom generates every question
# a case is worth from one template, by calling Python's ``str.format`` on it
# with ten values of its own (``enterprise_queries._render``):
#
#     "For {company}: Create epics in ACTIONITEM ...{failure_instruction}"
#          └ filled ┘                                └ filled per question ┘
#
# ``str.format`` reads every brace as a hole. So the design document asks for
# four things, all done here:
#
#     escape braces in values     a value containing "{" would crash it
#     append {failure_instruction} so designed failures reach the question
#     prefix "For {company}: "    unless the text already names the company
#     check it                    by filling it the way Worldloom will


#: Exactly the keys ``enterprise_queries._render`` passes to ``str.format``.
#: A template may use any of them and must use no others. A test renders a
#: real template through ``_render`` itself, so if that function ever changes
#: its keys this list fails loudly rather than drifting.
RENDER_KEYS = ("period", "purpose", "company", "audience", "sources",
               "action_instruction", "output_label", "destination",
               "verification_instruction", "failure_instruction")


def _escape(value: str) -> str:
    """*value* as literal text inside a ``str.format`` template."""
    return value.replace("{", "{{").replace("}", "}}")


def check_template(template: str) -> str:
    """*template*, unchanged, if Worldloom can fill it; ``ValueError`` if not.

    Fills it with the same ten keys ``_render`` uses. A template that fails
    here would fail for every generated question, in a later command, with
    no catalogue in sight — so it fails here instead.
    """
    try:
        template.format(**dict.fromkeys(RENDER_KEYS, ""))
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError(f"template cannot be filled by Worldloom: {error!r}: "
                         f"{template!r}") from error
    return template


def _finish(template: str, company_name: str) -> str:
    """The two additions every template gets, then the check."""
    names_company = "{company}" in template or (
        bool(company_name) and company_name.casefold() in template.casefold())
    if not names_company:
        template = "For {company}: " + template
    if "{failure_instruction}" not in template:
        # The instruction carries its own leading space, so it is appended
        # straight onto the last sentence — the same way _render's built-in
        # templates end.
        template = template + "{failure_instruction}"
    return check_template(template)


def prompt_template(question: BoundQuestion, *, company_name: str = "") -> str:
    """The question as a template Worldloom's generator can fill.

    Rebuilt from the catalogue's template and the chosen values, rather than
    from ``question.text``, because the values must be escaped *before* they
    go in: a value is literal text, while the rest of the template may hold
    keys Worldloom fills later.
    """
    template = _escape(question.template)
    for binding in question.bindings:
        template = template.replace("{{" + binding.slot + "}}",
                                    _escape(binding.value))
    return _finish(template, company_name)


def fallback_template(cuj: Cuj) -> tuple[str, str]:
    """The closest built-in workflow's template, and that workflow's name.

    For a journey with no usable phrasing. "Closest" is the one sharing the
    most (connector, entity) pairs with the journey, ties broken by name. The
    built-in templates are written in terms of ``{sources}`` and
    ``{destination}``, which Worldloom fills from the journey's own roles, so
    even a weak overlap produces a question about the right systems.
    """
    from ..enterprise_specs import builtin_registry

    pairs = {(step.connector, step.entity) for step in cuj.steps
             if step.connector and step.entity}

    def overlap(workflow: Any) -> int:
        roles = (*workflow.sources, *workflow.destinations)
        return len(pairs & {(role.connector, entity)
                            for role in roles for entity in role.entities})

    workflows = builtin_registry().workflows
    name = min(workflows, key=lambda key: (-overlap(workflows[key]), key))
    return _finish(workflows[name].prompt_template, ""), name
