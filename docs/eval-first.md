# Eval-first generation

Worldloom can generate a corpus first and inspect it for questions. That is useful for corpus QA.

It is not the right default when the corpus exists to support an evaluation.

For evaluation generation, Worldloom starts with the eval.

```text
EvalSpec
   |
   v
CandidatePlan[]
   |
   v
candidate world builders
   |
   v
independent requirement checks
   |
   +---- reject / mutate / retry
   |
   v
accepted World
   |
   v
EvalInstance + Oracle + derived assertions
```

The ordering is load-bearing.

An eval states the capability being tested, its abstract task DAG, and the conditions a valid synthetic world must contain. No concrete fact, ticket, document, person, or connector record exists yet.

Candidate plans are then derived deterministically from the complete eval design. A design edit changes the candidate family. Candidate builders receive the plan and its seed. They may use a normal vertical builder, an evolutionary search loop, or an external coding harness.

They do not decide whether their output is valid.

Worldloom independently checks the completed world against the eval requirements. Only accepted candidates are bound into gradeable eval instances. At bind time the world supplies concrete evidence IDs and canonical fact IDs. Assertions are derived from the task DAG and those checks; they are not separately authored.

## Minimal SDK

```python
from worldloom.evals import (
    EvalCampaign,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

spec = EvalSpec(
    id="forecast-authority",
    capability="authority_resolution",
    persona="finance director",
    request_template=(
        "Find the approved forecast, explain what changed from the prior version, "
        "and identify the unresolved operational risk."
    ),
    steps=(
        EvalStepSpec(id="find", capability="search", connector="drive"),
        EvalStepSpec(
            id="compare",
            capability="version_compare",
            depends_on=("find",),
            effect="transform",
        ),
        EvalStepSpec(
            id="verify",
            capability="evidence_check",
            depends_on=("compare",),
            effect="verify",
        ),
    ),
    requirements=(
        WorldRequirement(
            id="forecast-chain",
            kind=RequirementKind.REVISION_CHAIN,
            selector={"artifact_type": "finance_workbook"},
            minimum=2,
        ),
        WorldRequirement(
            id="approved-forecast",
            kind=RequirementKind.ARTIFACT,
            selector={"artifact_type": "finance_workbook", "lifecycle": "approved"},
        ),
        WorldRequirement(
            id="operational-risk",
            kind=RequirementKind.CONNECTOR,
            selector={"connector": "servicenow", "entity": "incident"},
        ),
    ),
    candidate_count=16,
    difficulty="hard",
)

campaign = EvalCampaign(spec)

# No synthetic data has been generated yet.
plans = campaign.plans()


def build_candidate(plan):
    return RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03"))


instances = campaign.instantiate(build_candidate)
```

A builder is expected to inspect `plan.requirements` and choose or tune a scenario capable of satisfying them. The simple example above deliberately does not pretend that a generic retail close can satisfy the revision-chain eval; such candidates are rejected until the builder produces the required state.

## Contracts

### `EvalSpec`

The pre-data problem definition.

It contains:

- the capability under test;
- the user/persona and canonical request;
- an ordered task DAG;
- declarative world requirements;
- difficulty and candidate budget.

It contains no generated record IDs.

### `CandidatePlan`

One deterministic attempt to instantiate an eval.

Its seed is content-addressed from the full `EvalSpec` plus the candidate ordinal. Candidate zero for one eval cannot silently become candidate zero for a materially different eval.

### `WorldRequirement`

A condition the candidate estate must make true. The initial closed vocabulary covers facts, events, artifacts, connector records, artifact revision chains, permissions, distractors, and temporal relations.

Selectors are data. They are not Python expressions and are never executed.

### `CandidateValidation`

An independent report over the completed world. Hard requirements gate acceptance. Soft requirements are reported but do not reject a candidate.

Generators and language models cannot weaken this layer.

### `EvalInstance`

A concrete eval bound only after candidate acceptance.

It contains the task steps, deterministic assertions, and an oracle that points back to canonical Worldloom evidence. Artifact and connector evidence is closed back to canonical fact IDs where possible, so a generated document's prose never becomes ground truth merely because it says something.

## Candidate search

`candidate_count` intentionally describes attempts, not guaranteed outputs.

```text
same EvalSpec
   |
   +-- candidate 0 -- reject: no approved version
   +-- candidate 1 -- reject: evidence too sparse
   +-- candidate 2 -- accept
   +-- candidate 3 -- accept
   +-- candidate 4 -- reject: missing connector state
```

This is the seam for quality-diversity or evolutionary generation.

Search is allowed to mutate generator parameters, scenario choices, organization shape, artifact policy, distractor placement, and other bounded candidate controls. The eval design, hard requirements, oracle rules, and validators remain outside that search space.

A future candidate archive can therefore optimize for realism, difficulty, evidence dispersion, and behavioral diversity without permitting novelty to compensate for an invalid eval.

## Relationship to legacy eval generation

`worldloom.agent_evals` remains useful when a corpus already exists and the question is: *what can this world test?*

The eval-first path answers the inverse question: *what world must exist to test this capability?*

They are complementary, not competing implementations.

For benchmark construction, the eval-first direction should be preferred because it prevents accidental capability coverage from defining the benchmark.

## Harnesses and LLMs

A model may help propose:

- task wording;
- candidate-generation tactics;
- bounded world parameters;
- distractor placement;
- natural-language realizations.

It does not author oracle facts or assertions independently.

A paraphrased request should be retained only when an independent planner can recover the same task semantics. The canonical request and DAG remain replayable even when no model is available.
