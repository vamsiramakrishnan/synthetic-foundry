# Eval demand compiler

Status: design contract.

## Purpose

Compile an abstract `EvalSpec` into constructive obligations without generating records.

The compiler is intentionally small. It does not build a world and it does not contain connector fixtures. It normalizes what must become true so generation tactics can solve the requirements jointly.

## Thin waist

```text
EvalSpec -> DemandSet -> candidate generation -> World -> validator
```

`DemandSet` is the thin waist. Eval authoring can become richer without coupling to vertical builders. Vertical generation can become richer without changing the eval schema.

## Proposed contracts

```python
class DemandKind(StrEnum):
    EVIDENCE = "evidence"
    SEARCH = "search"
    ARTIFACT = "artifact"
    ABSENCE = "absence"
    PERMISSION = "permission"
    STATE = "state"
    CARDINALITY = "cardinality"
    TEMPORAL = "temporal"
    MUTATION = "mutation"

class WorldDemand(Model):
    id: str
    kind: DemandKind
    source_requirement_ids: tuple[str, ...]
    selector: dict[str, Scalar]
    minimum: int = 1
    hard: bool = True

class DemandSet(Model):
    eval_spec_id: str
    design_digest: str
    demands: tuple[WorldDemand, ...]
```

The first implementation should compile today's `WorldRequirement` values mechanically. Do not add an expression language yet.

## Normalization

Requirements that describe the same obligation should merge before generation.

Example:

```text
R1: >= 1 ServiceNow P1 incident
R2: >= 3 ServiceNow P1 incidents
```

becomes:

```text
D1: >= 3 ServiceNow P1 incidents
sources = [R1, R2]
```

A hard and soft requirement for the same predicate becomes hard.

Conflicting exact-state requirements should be rejected before generation where the conflict is statically obvious.

## Tactics are separate

The demand compiler must not know that a retail stockout can create a ServiceNow incident or that a month-end close can create a finance workbook.

Those mappings belong to tactics:

```text
DemandSet
   |
   +-- revision tactic
   +-- incident tactic
   +-- search-witness tactic
   +-- access tactic
   +-- temporal tactic
   `-- artifact tactic
```

A tactic proposes changes to a normal Worldloom generation recipe. The completed world is still independently checked against the original requirements.

## Constraint cover

Tactics should publish which demands a proposed episode can satisfy and an approximate construction cost.

```python
class TacticProposal(Model):
    tactic: str
    covers: tuple[str, ...]
    cost: int
    recipe_patch: ...
```

The first planner can use deterministic weighted greedy cover:

1. discard proposals that violate known hard constraints;
2. choose the proposal with the best uncovered-demand-per-cost score;
3. apply it;
4. repeat until every hard demand is covered or no proposal remains;
5. validate the built world independently.

CP-SAT is a later optimization, not a prerequisite.

## Search witnesses

Search tactics should expose two operations:

```text
witness(predicate)
near_miss(predicate, dimension)
```

Near-miss generation must mutate one valid domain dimension at a time. The mutation must preserve all unrelated invariants.

This gives a useful distance measure for retrieval evals without optimizing against a particular retriever.

## Negative requirements

Absence is a construction constraint, not something to check only at the end.

If an eval requires that no matching change request exists, tactics that would accidentally create such a record must be excluded during planning. The validator still checks the absence after construction.

## Feedback

Rejected candidates already expose `RequirementCheck` values. Adaptive builders should consume only that sealed feedback:

```text
requirement id
observed
required
satisfied
detail
```

No oracle answer text is required to improve candidate construction.

## Done means

The first implementation is complete when:

- an `EvalSpec` deterministically compiles into a `DemandSet`;
- equivalent demands normalize;
- obvious conflicts refuse before world generation;
- at least revision, connector/search, permission, temporal, and artifact demands map to tactics;
- a planner can cover multiple demands with one episode proposal;
- completed worlds are still accepted only by the existing candidate validator;
- the same eval design and seed replay byte-identically.
