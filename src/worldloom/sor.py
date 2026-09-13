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

import re
from collections.abc import Sequence
from typing import Any

from .connector_data import (
    ConnectorProjectionRegistry,
    ConnectorRecord,
    builtin_projections,
)
from .ids import content_key
from .models import CanonicalFact
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
        "owner_bu": row.owner_bu,
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


def by_binding(rows: Sequence[ConnectorRecord]) -> dict[str, dict[str, list[ConnectorRecord]]]:
    """Records by binding id, then by period, in the order they were derived."""
    out: dict[str, dict[str, list[ConnectorRecord]]] = {}
    for record in rows:
        out.setdefault(str(record.fields["binding_id"]), {}).setdefault(str(record.fields["period"]), []).append(record)
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
    "ANCHOR_PERIOD", "CONNECTOR", "DEFAULT_PERIODS", "EXCEPTION_EVERY", "MONEY_KINDS", "RECORDS_PER_PERIOD",
    "answer", "by_binding", "entity_name", "periods_ending", "projections", "records",
]
