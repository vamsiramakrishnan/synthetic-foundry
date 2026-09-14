"""Hero use cases: a corpus that needs tidying, and the cases that grade the tidying.

"Organise my drive", "organise my inbox", "organise my chats" are the tasks
people actually hand an agent, and the one shape of work this repository's
evaluations could not pose: every planned query wrote *one* record, and a
reorganisation is hundreds of small, checkable moves whose whole point is
the count. This module builds both halves of such an evaluation from a
world and a spec:

* **The corpus.** A folder tree, a mailbox or a channel list in the
  company's own words — its business units, its periods, its people —
  populated with ``records`` items of which a stated share are misfiled,
  mislabelled or stale, and a stated share duplicated. Every item carries
  the fields the rule is stated in (its unit, its period, its subject tag,
  its last activity), so the request can say the rule and an agent can
  search by it. Nothing on a record says where it *should* be: that is the
  row's ground truth, not the corpus's.
* **The cases.** One ``PlannedEnterpriseQuery`` per group of records that
  share a destination, in the executable DAG grammar: a search bound to the
  group's own predicate (``SourceRequirement.bind = "predicate"``), a mapped
  write per record (a move, a label, an archive, a delete) and a mapped
  readback. Compiled through ``compile_dag_row`` like every other row, so the
  served surface, the reference agent and the three graders need nothing
  special; the per-record expectations (``per_record_state``) are what makes
  a three-hundred-file move score by how many landed.

Deterministic throughout: the corpus and the cases are a function of the
world's seed and the spec, so a housekeeping corpus rebuilds byte for byte
and two runs against it are comparable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, model_validator

from .connector_data import (
    ConnectorProjectionRegistry,
    ConnectorRecord,
    builtin_projections,
)
from .enterprise_dag import EnterpriseDagNode, ResultIteration, ResultReference
from .enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from .ids import content_key
from .models import Model
from .predicates import FieldPredicate, Predicate, PredicateOp
from .rng import Rng
from .world import World

Kind = Literal["drive", "inbox", "chats"]

#: Which connectors serve which kind of housekeeping. A kind names the
#: shape of the corpus (folders, a mailbox, channels); the connector names
#: whose tools tidy it.
CONNECTORS: dict[str, tuple[str, ...]] = {
    "drive": ("drive", "sharepoint", "onedrive"),
    "inbox": ("email", "outlook"),
    "chats": ("slack", "teams"),
}

#: The process name every housekeeping query is planned under.
PROCESS = "housekeeping"

#: How far back a period is before it counts as stale, in months, and how
#: long a channel may sit silent, in days. Rules an agent is told in the
#: request, so they are constants of the corpus rather than knobs.
STALE_AFTER_MONTHS = 3
SILENT_AFTER_DAYS = 90

#: The subject tags a mailbox is labelled by. Tag, label, and how often the
#: tag appears; the rest of the messages are conversation and stay untagged.
INBOX_CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("[Invoice]", "invoices", 4),
    ("[Approval]", "approvals", 3),
    ("[Newsletter]", "newsletters", 3),
    ("[Incident]", "incidents", 2),
    ("[Recruiting]", "recruiting", 2),
)


class HousekeepingSpec(Model):
    """What to build: which kind of mess, on which connector, how much of it."""

    kind: Kind
    connector: str
    records: int = Field(default=120, ge=4, le=5000)
    """How many items the corpus holds: files, messages or channels."""
    mess: float = Field(default=0.35, ge=0.0, le=1.0)
    """The share of items in the wrong place: misfiled, unlabelled, or a
    channel the rule says should not be active."""
    stale: float = Field(default=0.15, ge=0.0, le=1.0)
    """The share of items that are stale: a file from a period past the
    archive rule, an unread message older than the rule, a silent channel."""
    duplicates: float = Field(default=0.1, ge=0.0, le=1.0)
    """Drive only: the share of files that also exist as a stray copy."""
    salt: str = ""
    """Varies the draw without changing the seed, for a second corpus of
    the same shape from the same world."""

    @model_validator(mode="after")
    def _connector_serves_kind(self) -> HousekeepingSpec:
        if self.connector not in CONNECTORS[self.kind]:
            raise ValueError(
                f"{self.connector!r} does not serve a {self.kind} corpus;"
                f" one of {', '.join(CONNECTORS[self.kind])} does"
            )
        if self.mess + self.stale > 1.0:
            raise ValueError("mess and stale are shares of the same items and may not exceed 1.0 together")
        return self

    def tag(self, world: World) -> str:
        """The value every record of this corpus carries under ``housekeeping``.

        The predicates every case searches by include it, so a housekeeping
        corpus never claims a record the world's own projections put on the
        same connector, whatever fields the two happen to share.
        """
        return content_key("housekeeping", world.seed, self.model_dump(mode="json"))[:16]


@dataclass(frozen=True)
class HousekeepingPlan:
    """A built corpus and its cases, before materialisation."""

    spec: HousekeepingSpec
    tag: str
    records: tuple[ConnectorRecord, ...]
    queries: tuple[PlannedEnterpriseQuery, ...]
    expected: dict[str, dict[str, Any]]
    """Per record id, the fields it should end with (or ``{"deleted": True}``)
    once every case has run — the ground truth, kept off the records."""

    @property
    def moves(self) -> int:
        return sum(1 for fields in self.expected.values() if not fields.get("deleted"))

    @property
    def deletions(self) -> int:
        return sum(1 for fields in self.expected.values() if fields.get("deleted"))

    def projections(self) -> ConnectorProjectionRegistry:
        """The builtin projections with this corpus appended on its connector."""
        return builtin_projections().extended(self.spec.connector, self.records)


# ---------------------------------------------------------------------------
# Building the corpus
# ---------------------------------------------------------------------------


def _periods(world: World, count: int) -> list[str]:
    """The world's period and the ones before it, newest first."""
    period = world.period or "2026-03"
    year, month = int(period[:4]), int(period[5:7])
    out = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def _record(spec: HousekeepingSpec, tag: str, entity: str, key: str, title: str, fields: dict[str, Any]) -> ConnectorRecord:
    ident = content_key("housekeeping-record", tag, key)
    return ConnectorRecord(
        id=f"CONN-{spec.connector.upper()}-HK-{ident[:12].upper()}",
        connector=spec.connector, entity=entity, external_id=ident[:24], title=title,
        fields={**fields, "housekeeping": tag},
    )


def _unit_names(world: World) -> list[tuple[str, str]]:
    units = [(unit.id, unit.name) for unit in world.business_units]
    return units or [("BU-0", world.company.name)]


def _file_entity(spec: HousekeepingSpec, fmt: str) -> str:
    from .connector_definition import load_connector_definition

    definition = load_connector_definition(spec.connector)
    # OneDrive's `file` is a concrete entity beside its typed ones, and the
    # `file` alias the cases search by resolves to it alone; Drive's and
    # SharePoint's `file` is an alias over the typed entities.
    if "file" in definition.entities:
        return "file"
    if fmt in definition.entities:
        return fmt
    return "file"


def _build_drive(world: World, spec: HousekeepingSpec, rng: Rng, tag: str) -> tuple[list[ConnectorRecord], dict[str, dict[str, Any]]]:
    units = _unit_names(world)
    periods = _periods(world, STALE_AFTER_MONTHS + 2)
    current, stale_periods = periods[:STALE_AFTER_MONTHS], periods[STALE_AFTER_MONTHS:]
    people = [person.id for person in world.people] or ["P-0"]
    kinds = sorted({intent.artifact_type for intent in world.artifact_intents}) or ["close_pack", "board_paper", "variance_memo"]
    formats = ("docx", "xlsx", "pptx", "pdf")

    records: list[ConnectorRecord] = []
    expected: dict[str, dict[str, Any]] = {}
    folders: dict[tuple[str, str], str] = {}
    archive = _record(spec, tag, "folder", "folder:archive", "Archive", {"name": "Archive", "path": "/Archive", "parent": None})
    records.append(archive)
    for unit_id, unit_name in units:
        root = _record(spec, tag, "folder", f"folder:{unit_id}", unit_name, {"name": unit_name, "path": f"/{unit_name}", "parent": None, "unit_id": unit_id})
        records.append(root)
        for period in current:
            folder = _record(spec, tag, "folder", f"folder:{unit_id}:{period}", f"{unit_name}/{period}",
                             {"name": period, "path": f"/{unit_name}/{period}", "parent": root.id, "unit_id": unit_id, "period": period})
            records.append(folder)
            folders[(unit_id, period)] = folder.id
    folder_ids = [record.id for record in records]

    misfiled = round(spec.records * spec.mess)
    stale = round(spec.records * spec.stale)
    duplicated = round(spec.records * spec.duplicates)
    for index in range(spec.records):
        unit_id, unit_name = units[index % len(units)]
        kind = kinds[index % len(kinds)]
        fmt = formats[index % len(formats)]
        is_stale = index < stale
        period = rng.choice(stale_periods) if is_stale else current[index % len(current)]
        home = archive.id if is_stale else folders[(unit_id, period)]
        # The stale files sit where they were filed; the misfiled current
        # ones sit in another unit's or period's folder, never their own.
        if is_stale:
            parent = folders[(unit_id, current[index % len(current)])]
        elif stale <= index < stale + misfiled:
            parent = rng.choice([fid for fid in folder_ids if fid != home])
        else:
            parent = home
        title = f"{kind.replace('_', ' ').title()} {period} {unit_name}"
        fields = {
            "name": f"{title}.{fmt}", "format": fmt, "unit_id": unit_id, "unit": unit_name,
            "artifact_type": kind, "reporting_period": period, "parent": parent,
            "author_id": people[index % len(people)],
            "sha256": content_key("housekeeping-body", tag, index)[:64],
            "modified_at": f"{period}-{1 + index % 27:02d}T09:00:00",
            "size_bytes": 4096 + (index * 977) % 90000,
            "is_copy": False,
        }
        record = _record(spec, tag, _file_entity(spec, fmt), f"file:{index}", fields["name"], fields)
        records.append(record)
        if parent != home:
            expected[record.id] = {"parent": home}
        if index < duplicated:
            # A stray copy of the same bytes under the copy's name, in a
            # folder that is not the original's home; the rule says delete it.
            elsewhere = rng.choice([fid for fid in folder_ids if fid != home])
            copy = _record(spec, tag, record.entity, f"copy:{index}", f"{title} (1).{fmt}", {
                **fields, "name": f"{title} (1).{fmt}", "parent": elsewhere, "duplicate_of": record.id,
                "is_copy": True,
            })
            records.append(copy)
            expected[copy.id] = {"deleted": True}
    return records, expected


def _build_inbox(world: World, spec: HousekeepingSpec, rng: Rng, tag: str) -> tuple[list[ConnectorRecord], dict[str, dict[str, Any]]]:
    people = [(person.id, person.name) for person in world.people] or [("P-0", "Programme Office")]
    domain = world.company.name.lower().replace(" ", "-").replace(".", "")[:24] or "company"
    periods = _periods(world, STALE_AFTER_MONTHS + 2)
    records: list[ConnectorRecord] = []
    expected: dict[str, dict[str, Any]] = {}
    folders: dict[str, str] = {}
    if spec.connector == "outlook":
        inbox = _record(spec, tag, "mail_folder", "folder:inbox", "Inbox", {"name": "Inbox", "parent": None})
        records.append(inbox)
        for _, label, _ in INBOX_CATEGORIES:
            folder = _record(spec, tag, "mail_folder", f"folder:{label}", label.title(), {"name": label.title(), "parent": inbox.id})
            records.append(folder)
            folders[label] = folder.id
    weights = [weight for _, _, weight in INBOX_CATEGORIES]
    tagged = round(spec.records * (spec.mess + spec.stale))
    misfiled = round(spec.records * spec.mess)
    for index in range(spec.records):
        sender_id, sender = people[index % len(people)]
        is_tagged = index < tagged
        category = rng.weighted(INBOX_CATEGORIES, weights) if is_tagged else None
        period = periods[index % len(periods)]
        received = f"{period}-{1 + index % 27:02d}T08:{index % 60:02d}:00"
        subject = f"{category[0]} " if category else ""
        subject += f"{world.company.name} {period} update {index + 1}"
        fields: dict[str, Any] = {
            "subject": subject, "from": f"{sender.lower().replace(' ', '.')}@{domain}.example",
            "to": [f"you@{domain}.example"], "received_at": received, "sent_at": received,
            "body": f"{subject}. Please action.", "labels": ["inbox"], "folder": "inbox", "is_read": index % 3 != 0,
            "sender_id": sender_id, "thread_id": content_key("hk-thread", tag, index)[:16],
            "state": "sent", "message_id": f"<{content_key('hk-msg', tag, index)[:20]}@{domain}.example>",
        }
        if spec.connector == "outlook":
            fields["parent"] = folders.get("", "") or records[0].id
        record = _record(spec, tag, "message", f"message:{index}", subject, fields)
        records.append(record)
        if category is not None:
            _, label, _ = category
            if index < misfiled:
                # Sits in the inbox; the rule files it under its category.
                if spec.connector == "outlook":
                    expected[record.id] = {"parent": folders[label]}
                else:
                    expected[record.id] = {"folder": label}
            else:
                # Already where it belongs.
                if spec.connector == "outlook":
                    record.fields["parent"] = folders[label]
                record.fields["folder"] = label
                record.fields["labels"] = ["inbox", label]
        elif index >= spec.records - round(spec.records * spec.stale) and not fields["is_read"]:
            # Old unread conversation: the rule says mark it read.
            expected[record.id] = {"is_read": True}
            record.fields["received_at"] = f"{periods[-1]}-{1 + index % 27:02d}T08:00:00"
    return records, expected


def _build_chats(world: World, spec: HousekeepingSpec, rng: Rng, tag: str) -> tuple[list[ConnectorRecord], dict[str, dict[str, Any]]]:
    units = _unit_names(world)
    periods = _periods(world, 6)
    cutoff = f"{periods[STALE_AFTER_MONTHS]}-01"
    records: list[ConnectorRecord] = []
    expected: dict[str, dict[str, Any]] = {}
    entity = "channel"
    stale = round(spec.records * spec.stale)
    misfiled = round(spec.records * spec.mess)
    purposes = ("planning", "incidents", "release", "hiring", "social", "vendors", "reporting")
    for index in range(spec.records):
        unit_id, unit_name = units[index % len(units)]
        purpose = purposes[index % len(purposes)]
        name = f"{unit_name.lower().replace(' ', '-')}-{purpose}-{index + 1}"
        silent = index < stale + misfiled
        last = f"{periods[-1]}-{1 + index % 27:02d}T10:00:00" if silent else f"{periods[index % STALE_AFTER_MONTHS]}-{1 + index % 27:02d}T10:00:00"
        fields = {
            "name": name, "state": "active", "unit_id": unit_id, "unit": unit_name, "purpose": purpose,
            "last_activity_at": last, "member_count": 3 + (index * 7) % 40, "is_private": index % 5 == 0,
            "created_at": f"{periods[-1]}-01T09:00:00",
        }
        if spec.connector == "teams":
            fields["team"] = unit_name
        record = _record(spec, tag, entity, f"channel:{index}", name, fields)
        records.append(record)
        if silent:
            expected[record.id] = {"state": "archived"}
    del rng, cutoff
    return records, expected


# ---------------------------------------------------------------------------
# Planning the cases
# ---------------------------------------------------------------------------


def _predicate(where: Sequence[tuple[str, str, Any]]) -> Predicate:
    return Predicate(where=tuple(FieldPredicate(field=field, op=PredicateOp(op), value=value) for field, op, value in where))


def _query(
    spec: HousekeepingSpec, tag: str, *, key: str, text: str, entity: str, operation: str,
    where: Sequence[tuple[str, str, Any]], arguments: dict[str, Any], count: int,
) -> PlannedEnterpriseQuery:
    predicate = _predicate([("housekeeping", "eq", tag), *where])
    source = SourceRequirement(connector=spec.connector, entity=entity, minimum=count, predicate=predicate, bind="predicate")
    mutation = MutationRequirement(connector=spec.connector, entity=entity, operation=operation,
                                   output_format="record", preexisting_record=False, verify_after_write=operation != "delete")
    limit = min(count, 1000)
    nodes = [
        EnterpriseDagNode(id="read-0", kind="search", operation="search", connector=spec.connector,
                          entity=entity, source_index=0),
        EnterpriseDagNode(id="write", kind="write", operation=operation, connector=spec.connector, entity=entity,
                          depends_on=("read-0",), for_each=ResultIteration(node="read-0", limit=limit),
                          bindings={"id": ResultReference(node="read-0", path=("id",), select="item")},
                          arguments=arguments),
    ]
    if operation != "delete":
        nodes.append(EnterpriseDagNode(
            id="verify-write", kind="verify", operation="read", connector=spec.connector, entity=entity,
            depends_on=("write",), for_each=ResultIteration(node="write", limit=limit),
            bindings={"id": ResultReference(node="write", path=("id",), select="item")},
        ))
    query_id = content_key("housekeeping-query", tag, key)
    return PlannedEnterpriseQuery(
        id=query_id, workflow=f"housekeeping_{spec.kind}", query=text,
        dimensions={"dag_grammar": "enterprise-dag@1", "dag_shape": f"housekeeping_{operation}",
                    "housekeeping": spec.kind, "connector": spec.connector, "group": key, "records": str(count)},
        generation=GenerationRequirement(process=PROCESS, source_requirements=(source,), mutation=mutation),
        expected_dag=tuple(node.model_dump(mode="json", exclude_none=True) for node in nodes),
    )


def _plan_drive(world: World, spec: HousekeepingSpec, tag: str, records: Sequence[ConnectorRecord], expected: dict[str, dict[str, Any]]) -> list[PlannedEnterpriseQuery]:
    by_id = {record.id: record for record in records}
    folders = {record.id: record for record in records if record.entity == "folder"}
    groups: dict[str, list[str]] = {}
    for fid, fields in expected.items():
        if fields.get("deleted"):
            groups.setdefault("duplicates", []).append(fid)
        else:
            groups.setdefault(fields["parent"], []).append(fid)
    queries = []
    for target, members in sorted(groups.items()):
        if target == "duplicates":
            queries.append(_query(
                spec, tag, key="duplicates", entity="file", operation="delete", count=len(members),
                text=(f"{world.company.name}'s document library holds stray copies: a file whose name ends in"
                      " \" (1)\" is a duplicate of the original that still exists. Find every such copy and delete it."),
                where=[("is_copy", "eq", True)], arguments={},
            ))
            continue
        folder = folders[target]
        sample = by_id[members[0]]
        if folder.fields.get("name") == "Archive":
            stale = sorted({by_id[fid].fields["reporting_period"] for fid in members})
            text = (f"Files older than the last {STALE_AFTER_MONTHS} reporting periods belong in the Archive folder."
                    f" Move every file whose reporting period is one of {', '.join(stale)} into Archive, then read each back.")
            where = [("reporting_period", "in", tuple(stale)), ("parent", "ne", folder.id), ("is_copy", "eq", False)]
        else:
            unit, period = sample.fields["unit"], sample.fields["reporting_period"]
            text = (f"Every {unit} document for {period} belongs in the folder {folder.fields['path']}."
                    f" Find the {unit} originals for {period} (not the stray copies) filed anywhere else,"
                    " move each into that folder, then read each back.")
            where = [("unit_id", "eq", sample.fields["unit_id"]), ("reporting_period", "eq", period),
                     ("parent", "ne", folder.id), ("is_copy", "eq", False)]
        queries.append(_query(spec, tag, key=f"move:{target}", entity="file", operation="move", count=len(members),
                              text=text, where=where, arguments={"parent": folder.id}))
    return queries


def _plan_inbox(world: World, spec: HousekeepingSpec, tag: str, records: Sequence[ConnectorRecord], expected: dict[str, dict[str, Any]]) -> list[PlannedEnterpriseQuery]:
    by_id = {record.id: record for record in records}
    folders = {record.fields.get("name", "").lower(): record.id for record in records if record.entity == "mail_folder"}
    groups: dict[str, list[str]] = {}
    for fid, fields in expected.items():
        if "is_read" in fields:
            groups.setdefault("unread", []).append(fid)
        elif "parent" in fields:
            groups.setdefault(f"folder:{fields['parent']}", []).append(fid)
        else:
            groups.setdefault(f"label:{fields['folder']}", []).append(fid)
    queries = []
    for key, members in sorted(groups.items()):
        if key == "unread":
            oldest = sorted({by_id[fid].fields["received_at"][:7] for fid in members})
            queries.append(_query(
                spec, tag, key="unread", entity="message", operation="update", count=len(members),
                text=(f"Unread messages received in {', '.join(oldest)} are stale conversation. Mark every unread"
                      " message from those months as read, then read each back."),
                where=[("received_at", "lt", f"{oldest[-1]}-32"), ("is_read", "eq", False), ("folder", "eq", "inbox")],
                arguments={"fields": {"is_read": True}},
            ))
            continue
        if key.startswith("folder:"):
            folder_id = key.split(":", 1)[1]
            label = next(name for name, fid in folders.items() if fid == folder_id)
            tag_text = next(tag_ for tag_, lbl, _ in INBOX_CATEGORIES if lbl == label)
            queries.append(_query(
                spec, tag, key=key, entity="message", operation="move", count=len(members),
                text=(f"Messages whose subject starts with {tag_text} belong in the {label.title()} folder."
                      f" Find every such message still in the Inbox, move it there, then read each back."),
                where=[("subject", "contains", tag_text), ("parent", "ne", folder_id)],
                arguments={"parent": folder_id},
            ))
            continue
        label = key.split(":", 1)[1]
        tag_text = next(tag_ for tag_, lbl, _ in INBOX_CATEGORIES if lbl == label)
        queries.append(_query(
            spec, tag, key=key, entity="message", operation="update", count=len(members),
            text=(f"Messages whose subject starts with {tag_text} are filed under the folder '{label}'. Find"
                  f" every such message still in the inbox folder, set its folder to {label}, then read each back."),
            where=[("subject", "contains", tag_text), ("folder", "eq", "inbox")],
            arguments={"fields": {"folder": label}},
        ))
    return queries


def _plan_chats(world: World, spec: HousekeepingSpec, tag: str, records: Sequence[ConnectorRecord], expected: dict[str, dict[str, Any]]) -> list[PlannedEnterpriseQuery]:
    members = sorted(expected)
    if not members:
        return []
    cutoff = f"{_periods(world, 6)[STALE_AFTER_MONTHS]}-01"
    text = (f"A channel with no activity since {cutoff} is dormant. Find every active channel whose last"
            f" activity is before that date and archive it, then read each back.")
    if spec.connector == "teams":
        return [_query(spec, tag, key="dormant", entity="channel", operation="update", count=len(members), text=text,
                       where=[("last_activity_at", "lt", cutoff), ("state", "eq", "active")],
                       arguments={"fields": {"state": "archived"}})]
    return [_query(spec, tag, key="dormant", entity="channel", operation="transition", count=len(members), text=text,
                   where=[("last_activity_at", "lt", cutoff), ("state", "eq", "active")],
                   arguments={"state": "archived"})]


def plan(world: World, spec: HousekeepingSpec) -> HousekeepingPlan:
    """The corpus and its cases for *spec*, from *world*'s own words."""
    tag = spec.tag(world)
    rng = Rng(int(world.seed or 0), "housekeeping").derive(tag)
    builders = {"drive": _build_drive, "inbox": _build_inbox, "chats": _build_chats}
    planners = {"drive": _plan_drive, "inbox": _plan_inbox, "chats": _plan_chats}
    records, expected = builders[spec.kind](world, spec, rng, tag)
    queries = planners[spec.kind](world, spec, tag, records, expected)
    return HousekeepingPlan(spec=spec, tag=tag, records=tuple(records), queries=tuple(queries), expected=expected)


def corpus(world: World, spec: HousekeepingSpec) -> Any:
    """A materialised ``EnterpriseCorpus``: the plan's cases over its records.

    Through ``materialize_corpus`` like every other corpus, so the fixtures,
    the compiled rows and the export are the ones ``evalrun`` already reads.
    """
    from .enterprise_corpus import materialize_corpus

    built = plan(world, spec)
    return materialize_corpus(world, built.queries, projections=built.projections(), strict_sources=True)


__all__ = ["CONNECTORS", "HousekeepingPlan", "HousekeepingSpec", "INBOX_CATEGORIES", "PROCESS", "corpus", "plan"]
