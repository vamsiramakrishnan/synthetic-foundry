"""Records in a company's systems of record, derived from its activity bindings.

A compiled catalogue says, for every activity a company performs, which
product records it (`sor_product`) and which record kinds that product holds
for it (`sor_objects`). This module turns that into records: one per
binding, record kind and period, served through the `sor` connector, which
stands in for every product no emulator of its own covers
(`_data/connectors/sor.json`, built by `tools/build_sor_connector.py`).

A record carries what the binding declares: the activity and its stream,
the PCF process, the function that performs it, the owning unit and
country, the product and class, the control, and the exception when the
record is one that tripped it. Its status is one of the record kind's
workflow states and its amount, for record kinds that carry money, is a
figure in the country's currency. Everything is derived from the binding
id, the record kind and the period through `content_key`, so the same
compiled catalogue yields the same records: no draw, no clock.

The records are not simulated operations; they are the population a
request about the binding is asked over. A request to find the exception in
March's invoices has records to find it in, on every product the catalogue
names, which is what makes a line of business buildable when its system is
SAP rather than ServiceNow.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from .connector_data import (
    ConnectorProjectionRegistry,
    ConnectorRecord,
    builtin_projections,
)
from .ids import content_key
from .models import CanonicalFact, Model
from .process_bindings import CompiledCatalogue, load_catalogue
from .process_bindings.models import ActivityBinding

CONNECTOR = "sor"

#: Record kinds that carry an amount. A catalogue kind absent here has none.
MONEY_KINDS: frozenset[str] = frozenset({
    "SalesOrder", "Order", "BillingDoc", "Invoice", "ARInvoice", "Bill", "PurchaseRequisition", "Requisition",
    "PurchaseOrder", "GoodsReceipt", "Receipt", "InvoiceReceipt", "VendorBill", "JournalEntry", "AROpenItem",
    "APOpenItem", "IncomingPayment", "CustomerPayment", "PaymentRun", "Dunning", "CashPosition", "PayRun",
    "Loan", "Claim", "Exposure", "Policy", "Quote", "Opportunity", "Deal", "Contract", "FreightOrder", "Shipment",
})

#: One record in this many, per binding and kind, is the one that tripped the
#: binding's exception. A declared share rather than a draw: the record is
#: chosen by its key, so it is the same record every time.
EXCEPTION_EVERY = 4

#: How many periods of records a projection holds when the caller names none:
#: the world's period and the five before it, two quarters of work.
DEFAULT_PERIODS = 6

#: The period a programme's records end at when no world names one. A
#: declared anchor, so a programme derived without a world and a dataset built
#: from one agree on the records they cite.
ANCHOR_PERIOD = "2026-06"

#: Records per binding, record kind and period. Three, so a list answer (the
#: exceptions among March's purchase orders, the open items to chase) is a
#: subset of a set rather than a yes or no about one record.
RECORDS_PER_PERIOD = 3

_PLACEHOLDER = re.compile(r"\{(\d+)d\}|\{(\d+)\}")


def entity_name(kind: str) -> str:
    """`PurchaseOrder` -> `purchase_order`; `APOpenItem` -> `ap_open_item`; `KB` -> `kb`."""
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", kind)
    return "_".join(w.lower() for w in words)


def periods_ending(period: str, count: int) -> tuple[str, ...]:
    """*count* monthly periods ending at *period* (`"2026-03"`), oldest first."""
    year, month = (int(part) for part in period.split("-")[:2])
    out: list[str] = []
    for back in range(count - 1, -1, -1):
        index = year * 12 + (month - 1) - back
        out.append(f"{index // 12:04d}-{index % 12 + 1:02d}")
    return tuple(out)


def _ident(pattern: str | None, kind: str, key: str) -> str:
    """The record's own id in the product's pattern (`SO{10d}`), digits from *key*."""
    digits = int(key[:16], 16)
    if pattern:
        def fill(match: re.Match[str]) -> str:
            width = int(match.group(1) or match.group(2))
            return f"{digits % (10 ** width):0{width}d}"

        return _PLACEHOLDER.sub(fill, pattern)
    prefix = "".join(ch for ch in kind if ch.isupper())[:3] or kind[:3].upper()
    return f"{prefix}{digits % 10 ** 10:010d}"


def _object_models(catalogue: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """(product, kind) -> the catalogue's object model (table, tcode, id pattern)."""
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for spec in catalogue["sor_classes"].values():
        for product, objects in spec.get("products", {}).items():
            for kind, model in objects.items():
                models[(product, kind)] = dict(model)
    return models


def _workflow_states(kind: str) -> tuple[str, ...]:
    from .connector_definition import load_connector_definition

    definition = load_connector_definition(CONNECTOR)
    entity = definition.entities.get(entity_name(kind))
    if entity is None or entity.workflow is None:
        return ("open", "closed")
    return tuple(entity.workflow.states)


def records(
    compiled: CompiledCatalogue,
    *,
    company_id: str,
    periods: Sequence[str],
    facts: Sequence[CanonicalFact] = (),
    catalogue: dict[str, Any] | None = None,
) -> list[ConnectorRecord]:
    """One record per bound activity, record kind and period, in binding order.

    *facts* are the programme's facts about the bindings (`industry.facts`);
    each record links the ones about its binding so an answer grounded on the
    record is grounded on the catalogue's declaration too.
    """
    cat = catalogue if catalogue is not None else load_catalogue()
    models = _object_models(cat)
    currencies = {country: str(variant.get("currency", "")) for country, variant in cat["regional_variants"].items()}
    facts_by_binding: dict[str, list[str]] = {}
    for fact in facts:
        facts_by_binding.setdefault(fact.subject, []).append(fact.id)
    states_of: dict[str, tuple[str, ...]] = {}
    out: list[ConnectorRecord] = []
    for row in compiled.rows:
        if not row.sor_objects:
            continue
        for kind in row.sor_objects:
            states = states_of.setdefault(kind, _workflow_states(kind))
            model = models.get((row.sor_product, kind), {})
            for period in periods:
                for ordinal in range(RECORDS_PER_PERIOD):
                    out.append(_record(row, kind, period, ordinal, company_id, model, states, currencies, facts_by_binding))
    return out


def _record(
    row: ActivityBinding, kind: str, period: str, ordinal: int, company_id: str, model: dict[str, Any],
    states: tuple[str, ...], currencies: dict[str, str], facts_by_binding: dict[str, list[str]],
) -> ConnectorRecord:
    key = content_key(CONNECTOR, company_id, row.id, kind, period, ordinal)
    ident = _ident(model.get("id"), kind, key)
    draw = int(key[16:24], 16)
    status = states[draw % len(states)]
    tripped = bool(row.exception.strip()) and draw % EXCEPTION_EVERY == 0
    fields: dict[str, Any] = {
        "ident": ident,
        "object": kind,
        "product": row.sor_product,
        "sor_class": row.sor_class,
        "table": model.get("table") or model.get("object") or model.get("entity") or "",
        "tcode": model.get("tcode", ""),
        "activity_id": row.activity_id,
        "activity": row.activity,
        "stream": row.stream,
        "stream_name": row.stream_name,
        "pcf_id": row.pcf_id,
        "pcf_name": row.pcf_name,
        "function": row.function,
        "lob": row.function,
        "owner_bu": row.owner_bu,
        "business_unit": row.owner_bu,
        "country": row.country,
        "control": row.control,
        "exception": row.exception.strip() if tripped else "",
        "status": status,
        "period": period,
        "company_id": company_id,
        "binding_id": row.id,
        "terminal": status == states[-1],
    }
    if kind in MONEY_KINDS:
        fields["amount"] = round(100.0 * (1 + int(key[24:30], 16) % 9000), 2)
        fields["currency"] = currencies.get(row.country, "")
    title = f"{kind} {ident}: {row.activity} ({row.owner_bu}, {period})"
    return ConnectorRecord(
        id=f"CONN-SOR-{key[:12].upper()}",
        connector=CONNECTOR,
        entity=entity_name(kind),
        external_id=ident,
        title=title,
        fields=fields,
        fact_ids=sorted(facts_by_binding.get(row.id, [])),
    )


def projections(
    compiled: CompiledCatalogue,
    world: Any,
    *,
    periods: int = DEFAULT_PERIODS,
    facts: Sequence[CanonicalFact] = (),
    catalogue: dict[str, Any] | None = None,
) -> ConnectorProjectionRegistry:
    """The builtin projections with this company's system-of-record records on `sor`.

    The seam a dataset build plugs into (`FrozenCompanyBuilder(projections=...)`):
    the world's own connectors project as they did, and every product the
    catalogue names is answered by the `sor` connector beside them.
    """
    period = str(getattr(world, "period", None) or ANCHOR_PERIOD)
    rows = records(compiled, company_id=compiled.company, periods=periods_ending(period, periods), facts=facts, catalogue=catalogue)
    return builtin_projections().extended(CONNECTOR, rows)


class _Company:
    """One process company's derived records, computed once per world payload."""

    def __init__(self, compiled: CompiledCatalogue, periods: tuple[str, ...], facts: tuple[CanonicalFact, ...]) -> None:
        self.compiled = compiled
        self.periods = periods
        self.facts = facts
        self.records = records(compiled, company_id=compiled.company, periods=periods, facts=facts)
        self.channel_records = channel_records(compiled, self.records, periods=periods, company_id=compiled.company)


def _company_of(world: Any) -> _Company | None:
    """The process company a world was built for, with its records, or `None`."""
    from .recipe import PROCESS_STRUCTURE_KEY

    recipe = getattr(world, "recipe", None) or {}
    payload = recipe.get(PROCESS_STRUCTURE_KEY)
    if not payload:
        return None
    period = str(getattr(world, "period", None) or ANCHOR_PERIOD)
    return _compiled_company(json.dumps(payload, sort_keys=True), period)


@lru_cache(maxsize=8)
def _compiled_company(payload: str, period: str) -> _Company:
    # Cached on the company's own JSON: every connector projection of one
    # world reads the same derivation, and the derivation is a pure function
    # of the payload and the period.
    from . import industry
    from .process_bindings import CompanySpec, compile_company

    compiled = compile_company(CompanySpec.model_validate(json.loads(payload)))
    return _Company(compiled, periods_ending(period, DEFAULT_PERIODS), industry.facts(compiled))


class ProductUse(Model):
    """One product the company's bindings name, and what it holds for them."""

    product: str
    sor_class: str
    kinds: tuple[str, ...]
    """The record kinds the product holds, as `sor` entity names, sorted."""
    owner_bu: str
    """The unit owning most of the product's bindings; ties go to the first by name."""
    bindings: int


def products_for_world(world: Any) -> tuple[ProductUse, ...]:
    """The products the process company's bindings name, in product order.

    Each is the system of record the catalogue declares for some of the
    company's work: the class it belongs to, the record kinds it holds and
    the unit that owns most of the bindings on it. Empty for a world built
    without a process company.
    """
    company = _company_of(world)
    if company is None:
        return ()
    uses: dict[str, dict[str, Any]] = {}
    for row in company.compiled.rows:
        if not row.sor_product:
            continue
        use = uses.setdefault(row.sor_product, {"classes": set(), "kinds": set(), "owners": {}})
        use["classes"].add(row.sor_class)
        use["kinds"].update(entity_name(kind) for kind in row.sor_objects)
        use["owners"][row.owner_bu] = use["owners"].get(row.owner_bu, 0) + 1
    out = []
    for product in sorted(uses):
        use = uses[product]
        owner = sorted(use["owners"].items(), key=lambda item: (-item[1], item[0]))[0][0]
        out.append(ProductUse(
            product=product, sor_class="/".join(sorted(use["classes"])), kinds=tuple(sorted(use["kinds"])),
            owner_bu=owner, bindings=sum(use["owners"].values()),
        ))
    return tuple(out)


def facts_for_world(world: Any) -> tuple[CanonicalFact, ...]:
    """The process company's facts, subjected to the world's own business units and systems.

    A programme's facts are about bindings (`industry.facts`); a world's
    ledger is about the world's entities, so each fact is restated with the
    owning unit as its subject, found by name among the world's business
    units (the company itself where no unit carries the name), and the
    binding's product as its source system where the world holds a system of
    that name (`products_for_world`; none otherwise). Ids, kinds and values
    are unchanged, so a record derived for the world cites the same ids.
    """
    company = _company_of(world)
    if company is None:
        return ()
    units = {unit.name: unit.id for unit in getattr(world, "business_units", ())}
    systems = {system.name: system.id for system in getattr(world, "systems", ())}
    fallback = world.company.id
    rows = {row.id: row for row in company.compiled.rows}
    out = []
    for fact in company.facts:
        row = rows.get(fact.subject)
        subject = units.get(row.owner_bu, fallback) if row is not None else fallback
        source = systems.get(row.sor_product) if row is not None and row.sor_product else None
        out.append(fact.model_copy(update={"subject": subject, "source_system": source}))
    return tuple(out)


def records_for_world(world: Any) -> list[ConnectorRecord]:
    """The records of the process company a world was built for, or none.

    Reads the company from the world's recipe (`recipe.process_structure_of`),
    compiles it, and derives the records for `DEFAULT_PERIODS` ending at the
    world's period (or `ANCHOR_PERIOD`), linked to the programme's facts. A
    world built without a process company projects nothing, so every corpus
    built before this existed is unchanged.
    """
    company = _company_of(world)
    return list(company.records) if company is not None else []


def channel_records_for_world(world: Any, connector: str) -> list[ConnectorRecord]:
    """The channel evidence of the process company a world was built for, on *connector*.

    Empty for a world built without a process company and for a connector
    that emulates no declared channel.
    """
    company = _company_of(world)
    if company is None:
        return []
    return [record for record in company.channel_records if record.connector == connector]


def by_binding(rows: Sequence[ConnectorRecord]) -> dict[str, dict[str, list[ConnectorRecord]]]:
    """Records by binding id, then by period, in the order they were derived."""
    out: dict[str, dict[str, list[ConnectorRecord]]] = {}
    for record in rows:
        out.setdefault(str(record.fields["binding_id"]), {}).setdefault(str(record.fields["period"]), []).append(record)
    return out


# ---------------------------------------------------------------------------
# Channel evidence: where a binding's records are talked about
# ---------------------------------------------------------------------------

#: The day of the month a channel record is dated, so it sits inside the
#: period it reports on whatever the world's clock says.
CHANNEL_DAY = 15


def _stamp(period: str) -> str:
    return f"{period}-{CHANNEL_DAY:02d}T09:00:00+00:00"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _address(name: str, company_id: str) -> str:
    return f"{name} <{_slug(name)}@{_slug(company_id)}.example>"


def _channel_text(row: ActivityBinding, period: str, cited: Sequence[ConnectorRecord]) -> str:
    lines = [
        f"{row.activity} in {row.stream_name}, {row.owner_bu}, {row.country}, period {period}.",
        f"Control: {row.control}.",
    ]
    if cited:
        names = ", ".join(f"{r.fields['object']} {r.external_id} ({r.fields['status']})" for r in cited)
        lines.append(f"Records in {row.sor_product}: {names}.")
        tripped = [r for r in cited if r.fields["exception"]]
        if tripped:
            names = ", ".join(f"{r.fields['object']} {r.external_id}" for r in tripped)
            lines.append(f"Exception {tripped[0].fields['exception']}: {names}.")
        else:
            lines.append("No record tripped the exception this period.")
    else:
        lines.append(f"No system of record holds a record for this step ({row.sor_class}).")
    return "\n".join(lines)


def channel_records(
    compiled: CompiledCatalogue,
    rows: Sequence[ConnectorRecord],
    *,
    periods: Sequence[str],
    company_id: str,
    table: dict[str, Any] | None = None,
) -> list[ConnectorRecord]:
    """One channel record per bound activity, declared channel and period.

    A binding declares the channels its evidence lands in (`channels`); the
    emulator table (`industry.emulated_systems`) says which connector stands
    in for each (an email thread, a Jira issue, a SharePoint file, a
    Confluence page). Each record is scoped like the system-of-record records
    it cites: the LOB (the function), the stream, the owning unit, the
    activity, the period. Its text names the period's records and the one
    that tripped the exception, so an agent that reads the thread and the
    records reads one account. A channel no emulator covers yields nothing;
    the line reports it as unemulated.
    """
    from . import industry

    channels = (table if table is not None else industry.emulated_systems())["channels"]
    grouped = by_binding(rows)
    out: list[ConnectorRecord] = []
    for row in compiled.rows:
        for channel in sorted(set(row.channels)):
            mapped = channels.get(channel)
            if not mapped:
                continue
            connector, entity = str(mapped["connector"]), str(mapped["entity"])
            for period in periods:
                cited = grouped.get(row.id, {}).get(period, [])
                key = content_key("sor-channel", company_id, row.id, channel, period)
                title = f"{row.activity} ({row.owner_bu}, {period})"
                body = _channel_text(row, period, cited)
                fields: dict[str, Any] = {
                    "channel": channel,
                    "activity_id": row.activity_id,
                    "activity": row.activity,
                    "stream": row.stream,
                    "stream_name": row.stream_name,
                    "pcf_id": row.pcf_id,
                    "function": row.function,
                    "lob": row.function,
                    "owner_bu": row.owner_bu,
                    "business_unit": row.owner_bu,
                    "country": row.country,
                    "period": period,
                    "company_id": company_id,
                    "binding_id": row.id,
                    "record_ids": [r.id for r in cited],
                    "record_idents": [r.external_id for r in cited],
                    "exception": next((str(r.fields["exception"]) for r in cited if r.fields["exception"]), ""),
                    "body": body,
                    "created_at": _stamp(period),
                    "modified_at": _stamp(period),
                }
                if connector == "email":
                    fields.update(
                        thread_id=f"<{key}@{_slug(company_id)}.example>",
                        subject=title,
                        sent_at=_stamp(period),
                        state="sent",
                        labels=["process", row.stream, row.function, period],
                        **{"from": _address(f"{row.function} team", company_id),
                           "to": [_address(row.owner_bu, company_id)]},
                    )
                elif connector == "jira":
                    project = row.stream.upper()[:10]
                    fields.update(
                        key=f"{project}-{int(key[:8], 16) % 100000}", summary=title,
                        status="done" if not fields["exception"] else "open",
                        assignee=row.owner_bu, project=project,
                        labels=[row.stream, row.function, period], priority="High" if fields["exception"] else "Medium",
                    )
                elif connector == "confluence":
                    fields.update(page_id=str(int(key[:10], 16) % 10**8), space=row.stream.upper()[:10], text=body)
                else:
                    fields.update(item_id=key[:16].upper(), name=f"{title}.{channel}",
                                  parent=f"/{_slug(row.function)}/{row.stream}", content=body)
                out.append(ConnectorRecord(
                    id=f"CONN-{connector.upper()}-{key[:12].upper()}",
                    connector=connector,
                    entity=entity,
                    external_id=key[:16].upper(),
                    title=title,
                    fields=fields,
                    fact_ids=sorted({fact for r in cited for fact in r.fact_ids}),
                ))
    return out


def answer(intent_id: str, answer_shape: str, rows: Sequence[ConnectorRecord]) -> tuple[str, tuple[str, ...]]:
    """The expected answer to a record-set intent over one binding's records in one period.

    Derived from the records alone, so an agent that reads the same records
    reaches the same answer: the exceptions among them for a `list` intent, the
    open ones in workflow order for a `ranked_list`, the item to chase and its
    owner for a `message`, the count and statuses for anything else. Returns the
    text and the ids of the records it cites.
    """
    if not rows:
        raise ValueError("an answer needs at least one record")
    first = rows[0].fields
    kind, activity, period, owner = first["object"], first["activity"], first["period"], first["owner_bu"]
    kinds = sorted({str(r.fields["object"]) for r in rows})
    what = kind if len(kinds) == 1 else f"{', '.join(kinds)}"
    ordered = sorted(rows, key=lambda r: (str(r.fields["object"]), str(r.external_id)))
    tripped = [r for r in ordered if r.fields["exception"]]
    open_items = [r for r in ordered if not r.fields["terminal"]]
    if intent_id in {"find_exception", "reconcile"} or answer_shape == "list":
        if tripped:
            names = ", ".join(f"{r.fields['object']} {r.external_id} ({r.fields['exception']})" for r in tripped)
            return (f"{len(tripped)} of {len(ordered)} {what} records for {activity} in {period} tripped the exception: {names}.",
                    tuple(r.id for r in tripped))
        return (f"None of the {len(ordered)} {what} records for {activity} in {period} tripped an exception.",
                tuple(r.id for r in ordered))
    if answer_shape == "ranked_list" or intent_id == "triage_queue":
        if not open_items:
            return (f"Nothing to triage: all {len(ordered)} {what} records for {activity} in {period} are closed.",
                    tuple(r.id for r in ordered))
        ranked = sorted(open_items, key=lambda r: (str(r.fields["status"]), str(r.external_id)))
        names = "; ".join(f"{r.fields['object']} {r.external_id} ({r.fields['status']})" for r in ranked)
        return (f"{len(ranked)} open of {len(ordered)} {what} records for {activity} in {period}, by workflow stage: {names}.",
                tuple(r.id for r in ranked))
    if answer_shape == "message" or intent_id == "chase":
        targets = tripped or open_items
        if not targets:
            return (f"Nothing to chase: every {what} record for {activity} in {period} is closed.",
                    tuple(r.id for r in ordered))
        names = ", ".join(f"{r.fields['object']} {r.external_id}" for r in targets)
        return (f"Chase {owner} for {names}: {activity}, {period}, outstanding in {first['product']}.",
                tuple(r.id for r in targets))
    statuses = sorted({str(r.fields["status"]) for r in ordered})
    names = ", ".join(f"{r.fields['object']} {r.external_id} is {r.fields['status']}" for r in ordered)
    return (f"{len(ordered)} {what} records for {activity} in {period} ({', '.join(statuses)}): {names}.",
            tuple(r.id for r in ordered))


__all__ = [
    "ANCHOR_PERIOD", "CHANNEL_DAY", "CONNECTOR", "DEFAULT_PERIODS", "EXCEPTION_EVERY", "MONEY_KINDS",
    "ProductUse", "RECORDS_PER_PERIOD", "answer", "by_binding", "channel_records", "channel_records_for_world",
    "entity_name",
    "facts_for_world", "periods_ending", "products_for_world", "projections", "records", "records_for_world",
]
