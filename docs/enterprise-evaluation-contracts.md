# Checked state and required source fields

The covering planner carries authored requirements through exported query plans,
materialized records, compiled connector rows and trace grading. Existing plans
still load: the added state and field contracts default to empty.

## State changes

For update, patch and an upsert whose target already exists, the planner derives
a target from the destination connector's workflow. It uses the second authored
state when the initial state can legally reach it. Ambiguous aliases and entities
without a workflow need an explicit destination requirement:

```python
DestinationRole(
    connector="salesforce",
    entities=("account",),
    operations=(Operation.UPDATE,),
    target_state="reviewed",
    target_state_field="review_status",
)
```

`MutationRequirement.target_state` and `target_state_field` carry this decision.
The request names it. The write payload applies it. A `state_equals` assertion
compares that exact field on the fixture's destination record. The grader also
requires a successful write to that record: a matching initial state, an errored
write, or a write to a different record does not satisfy the assertion. Changing
only the expected state produces `state_mismatch:<node>`.

An update without a workflow or explicit target has no state assertion. A
successful tool call alone does not prove a requested state change. Create,
send and reply do not accept an update-state requirement.

## Field authoring

Use the existing `ConnectorFieldDefinition` schema. Attach definitions to an
`EntitySpec.field_definitions`; name fields in either
`EntitySpec.required_fields` or `SourceRole.required_fields`. Requirements accept
canonical names, native ids and authored aliases. They normalize to canonical
names before planning. Unknown or nonqueryable required fields refuse during
registry review.

```python
field = ConnectorFieldDefinition(
    id="u_control_tier",
    canonical="control.tier",
    name="Control Tier",
    field_type="option",
    options=("Standard", "Restricted"),
    query_name="u_control_tier",
    payload_name="u_control_tier",
)
```

A scenario profile can replace a connector specification through
`additional_connectors`, alongside `additional_workflows`. That is a complete
connector specification replacement, so retain every entity the scenario uses.
The existing `enterprise-evals plan --profile` and `build --profile` commands
consume this schema; no separate manifest file is required. In the SDK, pass
the authored `SpecRegistry` to `plan_queries`.

For each required field, materialization preserves existing values or uses the
existing deterministic payload synthesizer. Required values bypass sparsity;
they still obey `present_when`. An impossible presence requirement refuses.
Synthetic field values add record shape, not evidence facts. Source evidence
validation remains independent.

The rendered request names the required fields. Its source search uses the
shared `Predicate` algebra to exclude null values and explicitly projects their
native payload names. A `fields_used` assertion requires successful reads whose
trace contains both those filters and those projections. Reading the right
records without using the requested fields fails `fields_not_used:<node>`.

Definitions travel with `SourceRequirement`, so JSONL export and replay preserve
them. `compile_row` embeds the needed connector definitions in its executable
row; `run_eval_row` restores them. An explicitly supplied runtime definition can
override the embedded definition. Alias entities expose fields only when their
full definitions agree across every concrete member.

These are Generation changes: planned query bytes and ids change when state or
field contracts change, and records carrying required fields gain those values.
