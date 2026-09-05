# Eval-first world compilation

Worldloom should generate the evaluation first and the synthetic estate second.

The evaluation is a partial specification of a world. Candidate generation is the act of finding coherent worlds that satisfy that specification.

```text
EvalSpec
   |
   v
Demand compiler
   |
   +-- evidence
   +-- search
   +-- artifact
   +-- absence
   +-- permission
   +-- state
   +-- cardinality
   +-- temporal
   +-- mutation
   |
   v
World demands
   |
   v
Generation tactics
   |
   v
Candidate world
   |
   v
Independent validation
   |
   +-- reject -> feedback -> next candidate
   |
   v
Oracle binding
   |
   v
Reference execution
   |
   v
Eval instance + exact corpus
```

## The rule

An eval must not ask the generator to invent an answer after the world exists.
It states conditions that must become true in the world.

A candidate builder may decide how to satisfy those conditions. It may use a vertical builder, deterministic tactics, an evolutionary policy, or an external coding harness. It does not own acceptance.

Worldloom validates the completed world independently. Only accepted worlds bind to an oracle and become gradeable eval instances.

## Demand compilation

`WorldRequirement` is the public contract. A demand compiler should translate task semantics into a small closed vocabulary of constructive obligations.

| Demand | Example | Construction consequence |
| --- | --- | --- |
| evidence | approved forecast exists | create grounded artifact evidence |
| search | find P1 incidents older than 7d | create witnesses and controlled near-misses |
| artifact | finance workbook required | emit an artifact intent through the normal compiler |
| absence | no duplicate change exists | reserve the negative condition during generation |
| permission | persona cannot read one candidate | compile an access-policy state |
| state | incident is resolved | generate a valid lifecycle path to resolved |
| cardinality | at least 3 matching cases | create the minimum coherent witness set |
| temporal | RCA follows incident | sequence events on the simulated clock |
| mutation | update/create action is required | create a fork-safe precondition and expected effect |

Demand compilation must not contain generated record IDs. Concrete IDs belong to candidate instantiation.

## Witnesses and near-misses

Search evals should be constructed, not discovered by luck.

For a predicate such as:

```text
priority = P1
AND age_days > 7
AND assignment_group = Payments-SRE
```

Worldloom should deliberately create exact witnesses and bounded near-misses:

```text
P1, 21d, Payments-SRE     match
P2, 21d, Payments-SRE     distance 1
P1,  3d, Payments-SRE     distance 1
P1, 21d, Identity-Ops     distance 1
P2,  3d, Payments-SRE     distance 2
```

This makes retrieval hardness measurable. Mutation operators must remain domain-aware; arbitrary strings or impossible state transitions are not valid distractors.

## One episode should satisfy many demands

The naive implementation creates one filler object per requirement. That produces a Frankenstein corpus.

Instead, generation should solve a constraint-cover problem. One coherent incident can satisfy search, temporal, connector, artifact, revision, and permission demands at once.

```text
incident episode
   +-- ServiceNow incident
   +-- escalation email
   +-- RCA page
   +-- remediation Jira issue
   +-- forecast revision
   `-- executive update
```

Prefer fewer causally connected episodes over many isolated witnesses. Candidate fitness may reward demand coverage per episode and penalize filler-only objects, but hard validity remains outside the fitness function.

## Frozen time

Relative time is meaningless without an explicit simulation clock.

`older than 7 days`, `due tomorrow`, `closed last month`, and SLA windows must compile relative to world time, never wall time. Candidate replay must therefore preserve the same clock along with the seed and recipe.

## Mutation isolation

Write evals must not contaminate later rows.

Every executable eval runs against a fork of the accepted candidate world:

```text
accepted world W
   +-- fork -> eval 1 -> trace -> discard
   +-- fork -> eval 2 -> trace -> discard
   `-- fork -> eval 3 -> trace -> discard
```

A real tenant implementation can map this contract to snapshots, namespaces, or resettable fixtures. The semantic contract is isolation, not a particular storage mechanism.

## Reference execution

Generation is not complete when a candidate satisfies static predicates.

A reference executor must prove that the task can actually be completed against the forked world. This separates an agent failure from an impossible benchmark.

Recommended states:

```text
UNPROVEN
PROVEN_EXECUTABLE
PROVEN_UNSAT
INVALID
```

Only `PROVEN_EXECUTABLE` instances enter a benchmark.

The executor should produce a trace of operations, evidence IDs, effects, and final assertions. It must never make a model response the source of truth.

## Unsatisfiable designs

Some demand sets conflict. Worldloom should fail loudly rather than generate pathological state.

A future solver should return a small conflicting requirement set when possible:

```text
UNSAT
  eval-42/incident-state: status=open
  eval-91/incident-state: status=closed
```

Start with deterministic conflict checks. Use CP-SAT/SMT only where the constraint surface earns the complexity.

## Candidate search

The search loop is validity first.

```text
eval design
   -> candidate
   -> independent checks
   -> feedback
   -> mutate generation recipe
   -> next candidate
```

Models or evolutionary policies may propose generation recipes. They cannot change the eval, hard requirements, oracle rules, reference executor, or validators.

After validity, use Worldloom's existing outcome-space dispersion to select accepted worlds that are materially different. Do not optimize the default benchmark against one retriever or one agent.

## Shared artifact grammar

Eval and corpus generation must share artifact semantics.

An eval must not demand an arbitrary `Risks` section and force the document generator to grow one. Artifact types own allowed and required structure. Eval generation samples capabilities that the artifact grammar can actually express; corpus generation instantiates the same grammar.

This keeps document realism and eval solvability aligned.

## Scale

World scale and evaluation scale are different axes.

A few thousand richly connected enterprise objects can support hundreds of thousands of valid tasks. The useful combinatorics come from task topology, predicates, connectors, temporal state, permissions, lifecycle, and mutation behavior—not from blindly generating more files.

## What belongs where

Worldloom should absorb the method, not a second corpus engine.

Existing Worldloom primitives remain authoritative for:

- canonical facts and events;
- episode grammar and vertical physics;
- artifact intent, IR, lifecycle, and native rendering;
- connector projections;
- access policy;
- deterministic replay;
- outcome measurement and dispersion.

The eval-first layer adds:

- demand compilation;
- constructive witnesses and near-misses;
- requirement-aware generation tactics;
- forked execution;
- reference proofs;
- unsat diagnostics.

The resulting product boundary is simple:

> Worldloom compiles executable agent specifications into synthetic enterprise environments and the evals that prove those environments are usable.
