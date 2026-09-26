"""What a case is worth, and whether a case set looks like the work it stands for.

A pass rate counts a case that drafts a courtesy email the same as one that
deletes a posted goods receipt. An improvement loop that chases the pass rate
will spend its rounds on whatever fails most often, which is not the same as
whatever costs most when it fails. This module prices cases from the records
they touch, and compares a case set's mix with the mix of work the company
actually does, so the loop can be steered towards failures that matter on
flows that happen.

Everything here is computed at report time from the cases, the records and
(optionally) the compiled process catalogue. No case row, case-set digest or
default output changes; a run graded before this module existed is priced
exactly as one graded after it.

Value of one case (``value_of``):

- **At stake** is the money the records the expected DAG reads or writes
  carry: the first monetary field a record has (``evalrun.value.money_fields``,
  in order), else quantity times unit price when a record has both, else the
  same monetary field summed over an operational record's observation
  ``history``. Records in different currencies are never added together: the
  largest single-currency total is kept and the rest are named in the basis.
  A case whose records carry no money has ``at_stake=None``. Nothing is ever
  estimated.
- **Frequency** is how often the company does the activity the case stands
  for, per period: the compiled catalogue's binding volume when one is given,
  else the records of that activity in the record set divided by the periods
  they span, else, for an operational case, the number of exception episodes
  the simulation raised on the case's source. ``None`` when the case maps to
  none of these.
- **Error cost** is a multiplier by operation class (read < update < create <
  delete) with a factor for cases that carry a designed failure, all policy.
- **Weight** is the product of the three, each monetary and volume part
  divided by the set's median of it (so a typical case has 1.0) and clamped to
  ``[1/max_factor, max_factor]``; a missing part is 1.0, the typical case, and
  the basis says so. ``value_table`` computes the medians over a case set;
  ``value_of`` alone, without a ``scale``, can only compare a case with itself.

Mix (``mix_report``, ``check_mix``): a case set's shares over activity,
workflow and operation, compared with a reference mix by total variation
distance. The reference is the company's own simulated operations (record and
binding volumes), which is an authored prior: "representative" here means
representative of the simulated company until an empirical reference
population exists.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import ConfigDict, Field

from .. import packkit
from ..models import Model
from .contract import EvalCase
from .runner import RunReport

VALUE_SCHEMA = "worldloom.eval-value/v1"
MIX_SCHEMA = "worldloom.eval-mix/v1"

#: Operation classes, cheapest mistake first. A case's class is its most
#: expensive expected outcome; a case with no write is a read.
OPERATION_CLASSES: tuple[str, ...] = ("read", "update", "create", "delete")

#: The mix dimensions a report covers by default.
MIX_DIMENSIONS: tuple[str, ...] = ("activity", "workflow", "operation")

#: Record fields each reference dimension is counted from.
_RECORD_FIELDS: dict[str, str] = {"activity": "activity_id", "stream": "stream", "lob": "lob",
                                  "pcf_id": "pcf_id", "function": "function"}


def _policy(key: str) -> Any:
    return packkit.policy(key)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _lookup(fields: Mapping[str, Any], names: Sequence[str]) -> tuple[str, float] | None:
    """The first of *names* that *fields* holds as a number, matched without regard to case."""

    lowered = {str(key).lower(): key for key in fields}
    for name in names:
        key = lowered.get(name.lower())
        if key is None:
            continue
        number = _number(fields[key])
        if number is not None:
            return str(key), number
    return None


# -- records -------------------------------------------------------------------


class _Record:
    __slots__ = ("connector", "entity", "fid", "fields")

    def __init__(self, fid: str, connector: str, entity: str, fields: Mapping[str, Any]) -> None:
        self.fid = fid
        self.connector = connector
        self.entity = entity
        self.fields = fields


def _normalise(record: Any) -> _Record:
    held = record.model_dump() if hasattr(record, "model_dump") else dict(record)
    fields = held.get("fields")
    if not isinstance(fields, Mapping):
        fields = held
    return _Record(fid=str(held.get("fid") or held.get("id") or ""),
                   connector=str(held.get("server") or held.get("connector") or ""),
                   entity=str(held.get("entity") or ""), fields=fields)


class RecordIndex:
    """Records by id, with the per-activity and per-source volumes pricing needs; built once per set."""

    def __init__(self, records: Iterable[Any]) -> None:
        self.by_id: dict[str, _Record] = {}
        activity_records: Counter[str] = Counter()
        activity_periods: dict[str, set[str]] = defaultdict(set)
        episodes: dict[tuple[str, str], set[str]] = defaultdict(set)
        for raw in records:
            record = _normalise(raw)
            if not record.fid:
                continue
            self.by_id[record.fid] = record
            activity = record.fields.get("activity_id")
            if activity:
                activity_records[str(activity)] += 1
                if record.fields.get("period"):
                    activity_periods[str(activity)].add(str(record.fields["period"]))
            if isinstance(record.fields.get("synthesis_provenance"), Mapping):
                episode = record.fields.get("case_id") or record.fid
                episodes[(record.connector, record.entity)].add(str(episode))
        self.activity_records = dict(activity_records)
        self.activity_periods = {key: len(value) for key, value in activity_periods.items()}
        self.episodes = {key: len(value) for key, value in episodes.items()}

    def __len__(self) -> int:
        return len(self.by_id)


def index_records(records: Iterable[Any] | RecordIndex) -> RecordIndex:
    """*records* indexed once; an index passes through unchanged."""

    return records if isinstance(records, RecordIndex) else RecordIndex(records)


# -- one case -------------------------------------------------------------------


class CaseValue(Model):
    """What one case is worth, and exactly what that was read from."""

    case_id: str
    #: Money the touched records carry, in ``currency``; ``None`` when none carries any.
    at_stake: float | None
    currency: str | None = None
    #: The activity's volume per period; ``None`` when the case maps to no activity or source volume.
    frequency: float | None
    #: The operation-class multiplier, times the designed-failure factor when the case carries one.
    error_cost: float
    #: The normalised product; 1.0 is a typical case of its set.
    weight: float
    #: The catalogue activity the case stands for, when one is known.
    activity: str | None = None
    #: ``read``, ``update``, ``create`` or ``delete``: the case's costliest expected outcome.
    operation: str
    #: One line per input used or missing, in the order they were read.
    basis: tuple[str, ...]


class ValueScale(Model):
    """The medians a set's weights are normalised against, and the clamp."""

    at_stake: float | None = None
    frequency: float | None = None
    max_factor: float = 100.0


def touched_records(case: EvalCase) -> tuple[str, ...]:
    """Record ids the expected DAG reads or writes, in first-mention order.

    Node fixtures, a node's ``expected_reads``, ``reads_contain`` and
    ``failure_at`` assertions, outcome fixtures and per-record lists, the
    artifact's required records and a row's ``expected_record_ids``. A record
    a create will make is not here: it does not exist yet, so it carries no
    money the case could lose.
    """

    ids: list[str] = []
    row = case.row
    for node in (row.get("expected_dag") or {}).get("nodes", ()):
        if node.get("fixture"):
            ids.append(str(node["fixture"]))
        ids.extend(str(value) for value in node.get("expected_reads", ()))
    for assertion in row.get("assertions", ()):
        if assertion.get("type") in {"reads_contain", "per_record_state", "deleted"}:
            ids.extend(str(value) for value in assertion.get("records", ()))
        if assertion.get("fixture"):
            ids.append(str(assertion["fixture"]))
    for outcome in case.outcomes.structured:
        if outcome.fixture:
            ids.append(outcome.fixture)
        ids.extend(outcome.records)
    if case.outcomes.unstructured is not None:
        ids.extend(case.outcomes.unstructured.required_records)
    ids.extend(str(value) for value in row.get("expected_record_ids", ()))
    return tuple(dict.fromkeys(ids))


def operation_class(case: EvalCase) -> str:
    """The costliest expected outcome's kind, or ``read`` for a case that writes nothing."""

    kinds = {outcome.kind for outcome in case.outcomes.structured}
    for kind in reversed(OPERATION_CLASSES):
        if kind in kinds:
            return kind
    return "read"


def _record_money(record: _Record, money: Sequence[str], quantity: Sequence[str],
                  unit_price: Sequence[str]) -> tuple[float, str] | None:
    """A record's money and how it was read, or ``None`` when it carries none."""

    found = _lookup(record.fields, money)
    if found is not None:
        return found[1], f"{record.fid}.{found[0]}={found[1]:g}"
    qty, price = _lookup(record.fields, quantity), _lookup(record.fields, unit_price)
    if qty is not None and price is not None:
        return qty[1] * price[1], f"{record.fid}.{qty[0]}={qty[1]:g} x {price[0]}={price[1]:g}"
    history = record.fields.get("history")
    if isinstance(history, Sequence) and not isinstance(history, str):
        observations: list[Mapping[str, Any]] = [
            item["values"] for item in history if isinstance(item, Mapping) and isinstance(item.get("values"), Mapping)]
        for name in money:
            hits = [_lookup(values, (name,)) for values in observations]
            numbers = [hit[1] for hit in hits if hit is not None]
            if numbers:
                total = sum(numbers)
                return total, f"{record.fid}.history[].{name} summed over {len(numbers)} observation(s)={total:g}"
    return None


def _activity_of(case: EvalCase, touched: Sequence[_Record]) -> tuple[str | None, str]:
    counts = Counter(str(record.fields["activity_id"]) for record in touched if record.fields.get("activity_id"))
    if counts:
        value = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return value, f"activity {value} from the activity_id of {counts[value]} touched record(s)"
    declared = case.dimensions.get("activity_id") or case.row.get("activity_id")
    if declared:
        return str(declared), f"activity {declared} as the case row declares it"
    return None, "no activity: neither the touched records nor the row name one"


def _catalogue_volume(catalogue: Any, activity: str) -> tuple[float, str] | None:
    if isinstance(catalogue, Mapping):
        number = _number(catalogue.get(activity))
        return (number, f"frequency {number:g}/period for {activity} from the supplied volumes") if number is not None else None
    rows = [row for row in getattr(catalogue, "rows", ()) if activity in {row.activity_id, row.id}]
    if not rows:
        return None
    from ..sor import records_per_period

    per = records_per_period()
    objects = sum(len(row.sor_objects) for row in rows)
    if not objects:
        return None
    volume = float(objects * per)
    return volume, (f"frequency {volume:g}/period for {activity}: {len(rows)} binding(s), {objects} record kind(s)"
                    f" x {per} record(s) per period (compiled catalogue; authored prior, not measured)")


def _frequency(case: EvalCase, activity: str | None, touched: Sequence[_Record], index: RecordIndex,
               catalogue: Any) -> tuple[float | None, str]:
    if activity is not None and catalogue is not None:
        found = _catalogue_volume(catalogue, activity)
        if found is not None:
            return found
    if activity is not None and index.activity_records.get(activity):
        count = index.activity_records[activity]
        periods = index.activity_periods.get(activity) or 1
        volume = round(count / periods, 4)
        return volume, (f"frequency {volume:g}/period for {activity}: {count} record(s) over {periods} period(s)"
                        " in the record set (the company's simulated volume, an authored prior)")
    sources = sorted({(record.connector, record.entity) for record in touched
                      if (record.connector, record.entity) in index.episodes})
    if sources:
        connector, entity = sources[0]
        volume = float(index.episodes[(connector, entity)])
        return volume, (f"frequency {volume:g} for {connector}:{entity}: exception episodes the simulation raised"
                        " over its horizon (simulated volume, not measured)")
    return None, "no frequency: the case maps to no activity or simulated source volume"


def _error_cost(case: EvalCase) -> tuple[float, str, str]:
    costs = _policy("evalrun.value.error_cost")
    operation = operation_class(case)
    cost = float(costs[operation])
    line = f"error cost {cost:g} for a {operation}"
    if case.trajectory.failures:
        factor = float(_policy("evalrun.value.designed_failure_factor"))
        cost *= factor
        kinds = ", ".join(sorted({failure.kind for failure in case.trajectory.failures}))
        line += f", x{factor:g} for the designed failure ({kinds})"
    return round(cost, 4), operation, line


def _factor(value: float | None, median: float | None, cap: float, name: str) -> tuple[float, str]:
    if value is None:
        return 1.0, f"{name} unknown: counted as a typical case (1.0)"
    if not median:
        return 1.0, f"{name} has no positive median in the set: counted as 1.0"
    raw = value / median
    clamped = min(cap, max(1.0 / cap, raw))
    note = f"{name} factor {clamped:.4g} ({value:g} / median {median:g})"
    return clamped, note + (f", clamped from {raw:.4g}" if clamped != raw else "")


def _raw(case: EvalCase, index: RecordIndex, catalogue: Any) -> tuple[CaseValue, list[str]]:
    """Every part but the weight, with its basis."""

    basis: list[str] = []
    ids = touched_records(case)
    touched = [index.by_id[fid] for fid in ids if fid in index.by_id]
    absent = len(ids) - len(touched)
    basis.append(f"{len(ids)} record(s) the plan touches, {len(touched)} in the record set"
                 + (f" ({absent} absent)" if absent else ""))
    money = tuple(_policy("evalrun.value.money_fields"))
    quantity = tuple(_policy("evalrun.value.quantity_fields"))
    unit_price = tuple(_policy("evalrun.value.unit_price_fields"))
    by_currency: dict[str, float] = defaultdict(float)
    lines: dict[str, list[str]] = defaultdict(list)
    for record in touched:
        found = _record_money(record, money, quantity, unit_price)
        if found is None:
            continue
        currency = str(record.fields.get("currency") or "")
        by_currency[currency] += found[0]
        lines[currency].append(found[1])
    at_stake: float | None = None
    currency_out: str | None = None
    if by_currency:
        currency, total = sorted(by_currency.items(), key=lambda item: (-item[1], item[0]))[0]
        at_stake, currency_out = round(total, 2), currency or None
        basis.append(f"at stake {at_stake:g} {currency or '(no currency on the records)'} from "
                     f"{len(lines[currency])} record(s)")
        basis.extend(lines[currency][:6])
        if len(lines[currency]) > 6:
            basis.append(f"... and {len(lines[currency]) - 6} more record(s)")
        others = sorted(key for key in by_currency if key != currency)
        if others:
            basis.append("not added: records in " + ", ".join(other or "(no currency)" for other in others))
    else:
        basis.append(f"at stake unknown: no monetary field on the {len(touched)} touched record(s)")
    activity, activity_line = _activity_of(case, touched)
    basis.append(activity_line)
    frequency, frequency_line = _frequency(case, activity, touched, index, catalogue)
    basis.append(frequency_line)
    cost, operation, cost_line = _error_cost(case)
    basis.append(cost_line)
    value = CaseValue(case_id=case.id, at_stake=at_stake, currency=currency_out, frequency=frequency,
                      error_cost=cost, weight=cost, activity=activity, operation=operation, basis=tuple(basis))
    return value, basis


def _weighted(value: CaseValue, basis: list[str], scale: ValueScale) -> CaseValue:
    stake, stake_line = _factor(value.at_stake, scale.at_stake, scale.max_factor, "at stake")
    often, often_line = _factor(value.frequency, scale.frequency, scale.max_factor, "frequency")
    weight = round(stake * often * value.error_cost, 6)
    lines = [*basis, stake_line, often_line,
             f"weight {weight:g} = at-stake factor x frequency factor x error cost"]
    return value.model_copy(update={"weight": weight, "basis": tuple(lines)})


def _median(values: Iterable[float | None]) -> float | None:
    known = [value for value in values if value is not None and value > 0]
    return float(statistics.median(known)) if known else None


def value_scale(values: Iterable[CaseValue]) -> ValueScale:
    """The medians of a set's known at-stake and frequency parts, and the policy clamp."""

    items = list(values)
    return ValueScale(at_stake=_median(item.at_stake for item in items),
                      frequency=_median(item.frequency for item in items),
                      max_factor=float(_policy("evalrun.value.max_factor")))


def value_of(case: EvalCase, records: Iterable[Any] | RecordIndex, *, catalogue: Any = None,
             scale: ValueScale | None = None) -> CaseValue:
    """The value of one case, deterministic, with every input it used named in ``basis``.

    ``records`` are the connector records the case runs over (models or the
    emulator's dicts; an index from ``index_records`` avoids re-indexing).
    ``catalogue`` is a compiled process catalogue, or a mapping of activity id
    to volume per period, and takes precedence over record volumes. Without a
    ``scale`` the case is its own median, so its weight is its error cost;
    ``value_table`` prices a whole set against the set's medians.
    """

    index = index_records(records)
    value, basis = _raw(case, index, catalogue)
    if scale is None:
        scale = value_scale([value])
    return _weighted(value, basis, scale)


def value_table(cases: Iterable[EvalCase], records: Iterable[Any] | RecordIndex, *,
                catalogue: Any = None) -> dict[str, CaseValue]:
    """Every case's value, weighted against the set's own medians, by case id in case-id order."""

    index = index_records(records)
    raw = {case.id: _raw(case, index, catalogue) for case in sorted(cases, key=lambda item: item.id)}
    scale = value_scale(value for value, _ in raw.values())
    return {case_id: _weighted(value, basis, scale) for case_id, (value, basis) in raw.items()}


def _weights(values: Mapping[str, CaseValue] | Mapping[str, float]) -> dict[str, float]:
    return {key: float(value.weight if isinstance(value, CaseValue) else value) for key, value in values.items()}


# -- a run, weighted -------------------------------------------------------------


class ValuedCase(Model):
    case_id: str
    weight: float
    at_stake: float | None
    currency: str | None
    activity: str | None
    operation: str
    score: float | None
    passed: bool | None


class ActivityValue(Model):
    #: The catalogue activity, else ``workflow:<name>``, else ``unmapped``.
    activity: str
    cases: int
    graded: int
    passed: int
    weight: float
    value_weighted_pass_rate: float
    at_stake: float
    at_stake_failed: float
    frequency: float | None


class ValueSummary(Model):
    schema_version: str = Field(default=VALUE_SCHEMA, alias="schema")
    agent: str
    case_set: str
    cases: int
    graded: int
    errors: int
    #: Cases whose records carry money, and the currency the totals are in
    #: (``None`` when no record names one; ``mixed`` notes list the rest).
    priced: int
    currency: str | None
    pass_rate: float
    value_weighted_pass_rate: float
    mean_score: float
    value_weighted_mean_score: float
    at_stake: float
    at_stake_passed: float
    at_stake_failed: float
    at_stake_errored: float
    top_failing: tuple[ValuedCase, ...]
    by_activity: tuple[ActivityValue, ...]
    notes: tuple[str, ...] = ()

    model_config = ConfigDict(populate_by_name=True)


def _rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _slice_key(value: CaseValue, dimensions: Mapping[str, str]) -> str:
    if value.activity:
        return value.activity
    if dimensions.get("workflow"):
        return f"workflow:{dimensions['workflow']}"
    return "unmapped"


def value_summary(report: RunReport, cases: Iterable[EvalCase], records: Iterable[Any] | RecordIndex, *,
                  catalogue: Any = None, values: Mapping[str, CaseValue] | None = None,
                  top: int | None = None) -> ValueSummary:
    """A run read by value: weighted pass rate and score, money passed and failed, the costliest failures.

    Errored cases are not zeros in the rates (as in ``summarize``); their
    money is reported apart, as ``at_stake_errored``. Money totals add only
    cases in the summary's currency, the one with the most money at stake.
    """

    chosen = {case.id: case for case in cases}
    table = dict(values) if values is not None else value_table(chosen.values(), records, catalogue=catalogue)
    limit = int(_policy("evalrun.value.top")) if top is None else top
    rows = sorted(report.results, key=lambda row: row.case_id)
    notes: list[str] = []
    missing = [row.case_id for row in rows if row.case_id not in table]
    if missing:
        notes.append(f"{len(missing)} case(s) in the run are not in the case set; they weigh 1.0 and carry no money")
    money: dict[str, float] = defaultdict(float)
    for row in rows:
        value = table.get(row.case_id)
        if value is not None and value.at_stake is not None:
            money[value.currency or ""] += value.at_stake
    currency = sorted(money.items(), key=lambda item: (-item[1], item[0]))[0][0] if money else ""
    if len(money) > 1:
        notes.append("money in other currencies is left out of the totals: "
                     + ", ".join(f"{key or '(none)'} {total:g}" for key, total in sorted(money.items()) if key != currency))
    graded_weight = passed_weight = scored = 0.0
    passes = graded = priced = 0
    scores: list[float] = []
    stake = {"all": 0.0, "passed": 0.0, "failed": 0.0, "errored": 0.0}
    failing: list[ValuedCase] = []
    slices: dict[str, list[tuple[CaseValue | None, Any]]] = defaultdict(list)
    for row in rows:
        value = table.get(row.case_id)
        weight = value.weight if value is not None else 1.0
        counted = value is not None and value.at_stake is not None and (value.currency or "") == currency
        amount = value.at_stake if counted and value is not None and value.at_stake is not None else 0.0
        priced += counted
        stake["all"] += amount
        key = _slice_key(value, row.dimensions) if value is not None else "unmapped"
        slices[key].append((value, row))
        if not row.graded or row.score is None:
            stake["errored"] += amount
            continue
        graded += 1
        graded_weight += weight
        scores.append(row.score.score)
        scored += weight * row.score.score
        if row.score.passed:
            passes += 1
            passed_weight += weight
            stake["passed"] += amount
        else:
            stake["failed"] += amount
            failing.append(ValuedCase(
                case_id=row.case_id, weight=weight, at_stake=value.at_stake if value else None,
                currency=value.currency if value else None, activity=value.activity if value else None,
                operation=value.operation if value else "read", score=row.score.score, passed=False))
    failing.sort(key=lambda item: (-item.weight, -(item.at_stake or 0.0), item.case_id))
    by_activity: list[ActivityValue] = []
    for key in sorted(slices):
        members = slices[key]
        weight_total = sum(value.weight if value is not None else 1.0 for value, _ in members)
        graded_rows = [(value, row) for value, row in members if row.graded and row.score is not None]
        graded_total = sum(value.weight if value is not None else 1.0 for value, _ in graded_rows)
        passed_total = sum(value.weight if value is not None else 1.0 for value, row in graded_rows if row.score.passed)

        def _money(value: CaseValue | None) -> float:
            if value is None or value.at_stake is None or (value.currency or "") != currency:
                return 0.0
            return value.at_stake

        frequencies = sorted({value.frequency for value, _ in members if value is not None and value.frequency is not None})
        by_activity.append(ActivityValue(
            activity=key, cases=len(members), graded=len(graded_rows),
            passed=sum(1 for _, row in graded_rows if row.score.passed), weight=round(weight_total, 6),
            value_weighted_pass_rate=_rate(passed_total, graded_total),
            at_stake=round(sum(_money(value) for value, _ in members), 2),
            at_stake_failed=round(sum(_money(value) for value, row in graded_rows if not row.score.passed), 2),
            frequency=frequencies[-1] if frequencies else None,
        ))
    return ValueSummary(
        agent=report.agent, case_set=report.case_set, cases=len(rows), graded=graded, errors=len(rows) - graded,
        priced=priced, currency=currency or None,
        pass_rate=_rate(passes, graded), value_weighted_pass_rate=_rate(passed_weight, graded_weight),
        mean_score=_rate(sum(scores), len(scores)), value_weighted_mean_score=_rate(scored, graded_weight),
        at_stake=round(stake["all"], 2), at_stake_passed=round(stake["passed"], 2),
        at_stake_failed=round(stake["failed"], 2), at_stake_errored=round(stake["errored"], 2),
        top_failing=tuple(failing[:limit]), by_activity=tuple(by_activity), notes=tuple(notes),
    )


def render_value(summary: ValueSummary) -> str:
    """The summary as plain text: the two pass rates side by side, then where the value failed."""

    unit = f" {summary.currency}" if summary.currency else ""
    lines = [
        f"Value of agent {summary.agent!r} over case set {summary.case_set[:16]}:",
        f"{summary.graded} graded of {summary.cases} ({summary.errors} errored); {summary.priced} case(s) carry money",
        f"pass rate {summary.pass_rate}, value-weighted {summary.value_weighted_pass_rate}",
        f"mean score {summary.mean_score}, value-weighted {summary.value_weighted_mean_score}",
        f"at stake {summary.at_stake:g}{unit}: passed {summary.at_stake_passed:g}, failed {summary.at_stake_failed:g},"
        f" errored {summary.at_stake_errored:g}",
    ]
    if summary.top_failing:
        lines.append("Costliest failures:")
        for item in summary.top_failing:
            money = f", {item.at_stake:g}{' ' + item.currency if item.currency else ''} at stake" if item.at_stake is not None else ""
            lines.append(f"  {item.case_id}: weight {item.weight:g}{money}, {item.operation}"
                         + (f", activity {item.activity}" if item.activity else ""))
    lines.append("By activity:")
    for entry in summary.by_activity:
        lines.append(f"  {entry.activity}: {entry.passed}/{entry.graded} passed, weight {entry.weight:g},"
                     f" value-weighted pass rate {entry.value_weighted_pass_rate}, {entry.at_stake_failed:g} failed at stake")
    lines.extend(f"note: {note}" for note in summary.notes)
    return "\n".join(lines) + "\n"


def value_weighted_delta(comparison: Any, values: Mapping[str, CaseValue] | Mapping[str, float]) -> float:
    """The comparison's per-case deltas, averaged by case weight: the value-aware twin of ``mean_delta``.

    Over the same cases ``mean_delta`` averages (both sides graded, an axis
    in common). A case absent from ``values`` weighs 1.0, a typical case. Two
    runs graded by different graders have no delta worth weighting, so that
    comparison is refused rather than averaged.
    """

    if getattr(comparison, "grader_mismatch", False):
        raise ValueError("the runs were graded differently; their deltas cannot gate anything")
    weights = _weights(values)
    total = weighted = 0.0
    for item in comparison.deltas:
        if item.delta is None:
            continue
        weight = weights.get(item.case_id, 1.0)
        total += weight
        weighted += weight * item.delta
    return round(weighted / total, 4) if total else 0.0


# -- mix -------------------------------------------------------------------------


class ReferenceMix(Model):
    """The share of the company's work in each slice of one dimension, and where it came from."""

    dimension: str
    volumes: dict[str, float]
    basis: tuple[str, ...] = ()
    #: False for every reference Worldloom can build today: the volumes are
    #: the simulated company's, not a measured population's.
    empirical: bool = False

    @property
    def shares(self) -> dict[str, float]:
        total = sum(value for value in self.volumes.values() if value > 0)
        return {key: round(value / total, 6) for key, value in sorted(self.volumes.items()) if value > 0} if total else {}


def reference_mix(records: Iterable[Any] | RecordIndex, *, dimension: str = "activity") -> ReferenceMix:
    """The company's mix over *dimension*, counted from the records its simulated systems hold.

    Counts records per value of the record field the dimension names
    (``activity`` reads ``activity_id``; also ``stream``, ``lob``,
    ``pcf_id``, ``function``). The system-of-record projection writes the
    same number of records per binding, kind and period, so this is the
    binding volume: an authored prior, not a measurement.
    """

    if dimension not in _RECORD_FIELDS:
        raise ValueError(f"records carry no {dimension!r}; use one of {', '.join(sorted(_RECORD_FIELDS))}")
    field = _RECORD_FIELDS[dimension]
    index = index_records(records)
    counts = Counter(str(record.fields[field]) for record in index.by_id.values() if record.fields.get(field))
    if not counts:
        raise ValueError(f"no record carries {field!r}; this record set has no {dimension} mix")
    return ReferenceMix(dimension=dimension, volumes={key: float(value) for key, value in sorted(counts.items())},
                        basis=(f"{sum(counts.values())} record(s) with {field} over {len(counts)} value(s)",
                               "the company's simulated system-of-record volume; an authored prior, not measured"))


def reference_from_catalogue(compiled: Any, *, dimension: str = "activity") -> ReferenceMix:
    """The company's mix over *dimension* from its compiled bindings: binding x record kind x records per period.

    ``activity`` counts by catalogue activity id, ``stream``, ``lob`` (the
    performing function) and ``activity_type`` (capture, approve, ...) by the
    binding's own columns.
    """

    from ..sor import records_per_period

    attribute = {"activity": "activity_id", "stream": "stream", "lob": "function", "function": "function",
                 "activity_type": "type", "pcf_id": "pcf_id"}.get(dimension)
    if attribute is None:
        raise ValueError(f"bindings carry no {dimension!r}")
    per = records_per_period()
    volumes: dict[str, float] = defaultdict(float)
    for row in compiled.rows:
        # A binding with no record kind writes no record: the company does
        # the step somewhere no system of record sees, so it has no volume here.
        if row.sor_objects:
            volumes[str(getattr(row, attribute))] += len(row.sor_objects) * per
    if not volumes:
        raise ValueError("the compiled catalogue has no bindings")
    return ReferenceMix(dimension=dimension, volumes=dict(sorted(volumes.items())),
                        basis=(f"{len(compiled.rows)} binding(s) of {compiled.company}, x record kinds x {per} per period",
                               "the process catalogue's authored bindings; not measured"))


def case_slice(case: EvalCase, dimension: str, index: RecordIndex | None = None) -> str:
    """The value one case takes on a mix dimension; ``none`` when it has none."""

    if dimension == "activity":
        if index is not None:
            touched = [index.by_id[fid] for fid in touched_records(case) if fid in index.by_id]
            activity, _ = _activity_of(case, touched)
        else:
            declared = case.dimensions.get("activity_id") or case.row.get("activity_id")
            activity = str(declared) if declared else None
        return activity or "none"
    if dimension == "operation":
        return case.dimensions.get("operation") or operation_class(case)
    value = case.dimensions.get(dimension) or case.row.get(dimension)
    return str(value) if value not in (None, "") else "none"


class MixSlice(Model):
    value: str
    case_share: float
    reference_share: float
    #: ``case_share - reference_share``: positive is over-represented.
    gap: float


class MixDimension(Model):
    dimension: str
    counts: dict[str, int]
    shares: dict[str, float]


class MixComparison(Model):
    dimension: str
    tvd: float
    over: tuple[MixSlice, ...]
    under: tuple[MixSlice, ...]
    reference_basis: tuple[str, ...]
    empirical: bool


class MixReport(Model):
    schema_version: str = Field(default=MIX_SCHEMA, alias="schema")
    cases: int
    dimensions: tuple[MixDimension, ...]
    comparison: MixComparison | None = None
    notes: tuple[str, ...] = ()

    model_config = ConfigDict(populate_by_name=True)


def total_variation(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Half the L1 distance between two share maps over the union of their keys."""

    keys = set(left) | set(right)
    return round(0.5 * sum(abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in keys), 6)


def _shares(counts: Mapping[str, float]) -> dict[str, float]:
    total = sum(counts.values())
    return {key: round(value / total, 6) for key, value in sorted(counts.items())} if total else {}


def _compare(case_shares: Mapping[str, float], reference: ReferenceMix, top: int) -> MixComparison:
    ref = reference.shares
    slices = [MixSlice(value=key, case_share=case_shares.get(key, 0.0), reference_share=ref.get(key, 0.0),
                       gap=round(case_shares.get(key, 0.0) - ref.get(key, 0.0), 6))
              for key in sorted(set(case_shares) | set(ref))]
    over = sorted((item for item in slices if item.gap > 0), key=lambda item: (-item.gap, item.value))
    under = sorted((item for item in slices if item.gap < 0), key=lambda item: (item.gap, item.value))
    return MixComparison(dimension=reference.dimension, tvd=total_variation(case_shares, ref),
                         over=tuple(over[:top]), under=tuple(under[:top]),
                         reference_basis=reference.basis, empirical=reference.empirical)


def mix_report(cases: Iterable[EvalCase], *, reference: ReferenceMix | None = None,
               records: Iterable[Any] | RecordIndex | None = None,
               dimensions: Sequence[str] = MIX_DIMENSIONS, top: int = 5) -> MixReport:
    """The case set's shares over each dimension and, given a reference, how far it is from it.

    ``records`` resolve a case's catalogue activity from the records it
    touches; without them a case's activity is what its row declares.
    """

    items = sorted(cases, key=lambda case: case.id)
    index = index_records(records) if records is not None else None
    wanted = list(dict.fromkeys([*dimensions, *([reference.dimension] if reference is not None else [])]))
    reported: list[MixDimension] = []
    by_dimension: dict[str, dict[str, float]] = {}
    for dimension in wanted:
        counts = Counter(case_slice(case, dimension, index) for case in items)
        shares = _shares(counts)
        by_dimension[dimension] = shares
        reported.append(MixDimension(dimension=dimension, counts=dict(sorted(counts.items())), shares=shares))
    comparison = _compare(by_dimension[reference.dimension], reference, top) if reference is not None else None
    notes = () if reference is None or reference.empirical else (
        "representative of the company's own simulated operations; no empirical reference population exists yet",)
    return MixReport(cases=len(items), dimensions=tuple(reported), comparison=comparison, notes=notes)


class MixCheck(Model):
    dimension: str
    tvd: float
    max_tvd: float
    ok: bool
    #: ``cases`` when measured over compiled cases (exact); ``plan`` when
    #: predicted from a plan's strata (a stratum that does not pin the
    #: dimension is assumed to follow the reference).
    measured_on: str
    over: tuple[MixSlice, ...]
    under: tuple[MixSlice, ...]
    reason: str


def _plan_shares(plan: Any, reference: ReferenceMix) -> dict[str, float]:
    strata = plan.get("strata") if isinstance(plan, Mapping) else getattr(plan, "strata", None)
    if strata is None and hasattr(plan, "plan"):
        strata = plan.plan.get("strata")
    counts: dict[str, float] = defaultdict(float)
    ref = reference.shares
    for stratum in strata or ():
        data = stratum if isinstance(stratum, Mapping) else stratum.model_dump(mode="json")
        count = float(data.get("count") or 0)
        where = (data.get("source") or {}).get("where") or {}
        pinned = where.get(reference.dimension)
        if pinned is not None:
            counts[str(pinned)] += count
        else:
            for key, share in ref.items():
                counts[key] += count * share
    return _shares(counts)


def check_mix(target: Any, reference: ReferenceMix, max_tvd: float | None = None, *,
              records: Iterable[Any] | RecordIndex | None = None, top: int = 3) -> MixCheck:
    """Whether a curriculum, a dataset plan or a case set stays within ``max_tvd`` of the reference mix.

    ``max_tvd`` defaults to the policy ``evalrun.curriculum.max_mix_tvd``.
    Cases are measured exactly; a plan is predicted from its strata counts
    and the value each pins on the reference dimension.
    """

    limit = float(_policy("evalrun.curriculum.max_mix_tvd")) if max_tvd is None else float(max_tvd)
    if isinstance(target, Sequence) and target and all(isinstance(item, EvalCase) for item in target):
        index = index_records(records) if records is not None else None
        shares = _shares(Counter(case_slice(case, reference.dimension, index) for case in target))
        measured = "cases"
    else:
        shares = _plan_shares(target, reference)
        measured = "plan"
    comparison = _compare(shares, reference, top)
    ok = comparison.tvd <= limit + 1e-9
    reason = (f"total variation {comparison.tvd:.4g} from the {reference.dimension} mix "
              + ("is within" if ok else "exceeds") + f" {limit:g}")
    if not ok and comparison.over:
        reason += "; most over-represented: " + ", ".join(f"{item.value} (+{item.gap:.3g})" for item in comparison.over)
    return MixCheck(dimension=reference.dimension, tvd=comparison.tvd, max_tvd=limit, ok=ok, measured_on=measured,
                    over=comparison.over, under=comparison.under, reason=reason)


class SliceScore(Model):
    cases: int
    graded: int
    passed: int
    pass_rate: float
    mean_score: float


class MixScores(Model):
    """A curriculum run's score on its representative rows and on its failure-targeted tail, apart."""

    representative: SliceScore
    tail: SliceScore
    unassigned: int = 0


def _score(rows: Sequence[Any]) -> SliceScore:
    graded = [row for row in rows if row.graded and row.score is not None]
    passed = sum(1 for row in graded if row.score.passed)
    return SliceScore(cases=len(rows), graded=len(graded), passed=passed, pass_rate=_rate(passed, len(graded)),
                      mean_score=_rate(sum(row.score.score for row in graded), len(graded)))


def mix_scores(report: RunReport, curriculum: Any, *, strata: Mapping[str, str] | None = None) -> MixScores:
    """Split a run over a curriculum's cases into its representative rows and its tail.

    ``strata`` maps case id to the stratum it was compiled under (a dataset
    entry's ``stratum``). Without it a case is assigned by its dimensions:
    to the tail when a failure-targeted stratum's predicates all hold, else
    to the representative rows when a representative stratum's do.
    """

    representative_ids = {target.stratum for target in curriculum.targets if target.keys == (REPRESENTATIVE_KEY,)}
    rep: list[Any] = []
    tail: list[Any] = []
    unassigned = 0
    for row in sorted(report.results, key=lambda item: item.case_id):
        if strata is not None and row.case_id in strata:
            (rep if strata[row.case_id] in representative_ids else tail).append(row)
            continue
        matches = [target for target in curriculum.targets
                   if all(row.dimensions.get(key) == value for key, value in target.where.items())]
        if any(target.stratum not in representative_ids for target in matches):
            tail.append(row)
        elif matches:
            rep.append(row)
        else:
            unassigned += 1
    return MixScores(representative=_score(rep), tail=_score(tail), unassigned=unassigned)


#: The ``keys`` of a curriculum target that keeps the mix rather than chasing a failure.
REPRESENTATIVE_KEY = "mix:representative"


__all__ = [
    "MIX_DIMENSIONS",
    "MIX_SCHEMA",
    "OPERATION_CLASSES",
    "REPRESENTATIVE_KEY",
    "VALUE_SCHEMA",
    "ActivityValue",
    "CaseValue",
    "MixCheck",
    "MixComparison",
    "MixDimension",
    "MixReport",
    "MixScores",
    "MixSlice",
    "RecordIndex",
    "ReferenceMix",
    "SliceScore",
    "ValueScale",
    "ValueSummary",
    "ValuedCase",
    "case_slice",
    "check_mix",
    "index_records",
    "mix_report",
    "mix_scores",
    "operation_class",
    "reference_from_catalogue",
    "reference_mix",
    "render_value",
    "total_variation",
    "touched_records",
    "value_of",
    "value_scale",
    "value_summary",
    "value_table",
    "value_weighted_delta",
]
