"""Deterministic wide-schema helpers for connector definitions.

These helpers create *shape*, not semantic truth. Critical business attributes
should come from harvested/customer field manifests. Synthetic fields exist to
reproduce the context and projection pressure of tenants with hundreds of
mostly-empty custom fields without spending model tokens or inventing hidden
claims.
"""

from __future__ import annotations

from .connector_definition import ConnectorFieldDefinition
from .ids import content_key

_FIELD_TYPES = (
    "text",
    "text",
    "text",
    "option",
    "number",
    "date",
    "user",
    "boolean",
    "multi_option",
    "rich_text",
)
_FILL_RATES = (0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.40, 0.65)
_STEMS = (
    "Regulatory Impact",
    "Customer Impact",
    "Business Service",
    "Data Classification",
    "Release Train",
    "Escalation Owner",
    "Control Family",
    "Portfolio",
    "Market",
    "Risk Rating",
    "Review Date",
    "Cost Centre",
    "Programme",
    "Exception Reason",
    "External Reference",
    "Operational Tier",
)
_OPTIONS = (
    ("None", "Low", "Medium", "High"),
    ("Not assessed", "Green", "Amber", "Red"),
    ("Internal", "Confidential", "Restricted"),
    ("No", "Yes", "Unknown"),
)


def _pick(parts: tuple[str, ...], seed: int, entity: str, ordinal: int) -> int:
    digest = content_key("connector-field", seed, entity, ordinal, *parts)
    return int(digest[:12], 16)


def synthesize_custom_fields(
    *,
    connector: str,
    entity: str,
    count: int,
    seed: int,
    start: int = 10_000,
    id_prefix: str = "customfield_",
) -> tuple[ConnectorFieldDefinition, ...]:
    """Create a deterministic long-tail field manifest.

    The distribution is intentionally sparse: enterprise custom fields are often
    present in metadata while empty on most records. IDs and choices depend only
    on the field's hierarchical key, so inserting an unrelated field elsewhere
    never reshuffles this manifest.
    """

    if count < 0:
        raise ValueError("custom field count must be non-negative")
    out: list[ConnectorFieldDefinition] = []
    for offset in range(count):
        ordinal = start + offset
        chooser = _pick((connector,), seed, entity, ordinal)
        field_type = _FIELD_TYPES[chooser % len(_FIELD_TYPES)]
        stem = _STEMS[(chooser // 17) % len(_STEMS)]
        name = f"{stem} {offset + 1:03d}"
        canonical = f"custom.{connector}.{entity}.{ordinal}"
        options: tuple[str, ...] = ()
        cardinality: int | None = None
        if field_type in {"option", "multi_option"}:
            options = _OPTIONS[(chooser // 31) % len(_OPTIONS)]
            cardinality = len(options)
        average_bytes = {
            "text": 48,
            "rich_text": 512,
            "number": 16,
            "date": 24,
            "user": 96,
            "boolean": 8,
            "option": 24,
            "multi_option": 64,
        }[field_type]
        native_id = f"{id_prefix}{ordinal}"
        query_name = f"cf[{ordinal}]" if connector == "jira" else native_id
        out.append(
            ConnectorFieldDefinition(
                id=native_id,
                canonical=canonical,
                name=name,
                aliases=(f"{stem} {ordinal}",),
                field_type=field_type,  # type: ignore[arg-type]
                options=options,
                fill_rate=_FILL_RATES[(chooser // 7) % len(_FILL_RATES)],
                cardinality=cardinality,
                deprecated=(chooser % 29 == 0),
                queryable=True,
                writable=(chooser % 23 != 0),
                query_name=query_name,
                payload_name=native_id,
                average_bytes=average_bytes,
            )
        )
    return tuple(out)


def estimated_populated_fields(
    fields: tuple[ConnectorFieldDefinition, ...],
) -> float:
    """Expected populated custom-field count for one record."""

    return sum(field.fill_rate for field in fields)


def estimated_payload_bytes(
    fields: tuple[ConnectorFieldDefinition, ...],
) -> float:
    """Expected payload bytes contributed by the field manifest."""

    return sum(field.fill_rate * field.average_bytes for field in fields)


__all__ = [
    "estimated_payload_bytes",
    "estimated_populated_fields",
    "synthesize_custom_fields",
]
