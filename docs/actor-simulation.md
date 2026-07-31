# Actor simulation roadmap

Worldloom should use LLMs as bounded employees inside the deterministic world, not as authors of canonical truth.

The actor runtime extends the existing pipeline:

```
World state
  → role-scoped observation
  → actor invocation
  → typed tool call
  → policy and precondition checks
  → committed event, fact, task, or artifact intent
  → new observations for other actors
```

Only successful tool execution changes the world. Dialogue, reasoning, and model output do not.

This roadmap begins after the second vertical has established which roles, tools, and enterprise nouns are genuinely generic. The first implementation may use the retail-close episode as a fixture, but actor abstractions must not be extracted from retail alone.

---

## Design rules

1. **Actors inhabit the world; they do not author it.** They observe a bounded projection and act through tools.
2. **Canonical truth stays deterministic.** The runtime owns IDs, time, arithmetic, state mutation, permissions, lineage, and validation.
3. **Knowledge is local.** An actor sees only facts, records, messages, and obligations available to that employee at that time.
4. **Roles grant tools, not prompt privileges.** Authority is enforced by tool policy and state preconditions.
5. **Most employees are records, not running agents.** LLM actors are activated only for consequential episodes.
6. **Every invocation is replayable.** Requests, tool descriptions, outputs, rejected calls, and accepted results enter the generation ledger.
7. **Every episode is bounded.** Tool-call budgets, turn budgets, deadlines, and terminal conditions prevent open-ended simulations.

---

## Roadmap placement

Actor simulation depends on work already identified elsewhere:

```
second vertical
→ generic entity and relationship model
→ executable lore and decision rights
→ durable world state and event transitions
→ epistemic observations
→ actor runtime
→ multi-actor episodes
→ meetings and negotiation
→ scale and diversity
```

Do not build a generic multi-agent framework before these prerequisites exist. Without them, actors share an omniscient prompt, invent actions in prose, and generate disconnected records.

---

## A0. Define the actor boundary

Add thin-waist contracts without implementing a model loop.

```python
class ActorObservation(Model):
    actor_id: str
    observed_at: datetime
    trigger_event_id: str | None
    visible_fact_ids: list[str]
    visible_artifact_ids: list[str]
    message_ids: list[str]
    task_ids: list[str]
    obligation_ids: list[str]


class ActorInvocation(Model):
    id: str
    actor_id: str
    role_key: str
    observation_id: str
    available_tools: list[str]
    max_tool_calls: int
    max_turns: int


class ActorAction(Model):
    invocation_id: str
    tool_name: str | None
    arguments: dict[str, Any]
    confidence: float
    abstention_reason: str | None = None


class ToolResult(Model):
    accepted: bool
    event_ids: list[str]
    fact_ids: list[str]
    artifact_intent_ids: list[str]
    task_ids: list[str]
    rejection_reason: str | None = None
```

Add an append-only `ActorLedgerEntry` or extend `GenerationLedgerEntry` with actor call sites, tool schemas, observations, responses, and tool results.

### Exit gate

A scripted fake actor can receive an observation, call one fake tool, and replay byte-for-byte with the provider unavailable. No model is required.

---

## A1. Add epistemic observations

Canonical facts describe what is true. Actors need a separate record of who knew what and when.

```python
class Observation(Model):
    id: str
    observer_id: str
    fact_id: str
    learned_at: datetime
    source_type: str
    source_id: str | None
    confidence: float
```

Observation generation must respect:

- employment and role validity
- artifact permissions
- communication delay
- source authority
- role responsibilities
- explicit messages and meetings

An actor request receives observations, never the world fact ledger directly.

### Exit gate

Two actors reacting to the same incident receive materially different fact sets. Tests prove that neither can cite facts it has not observed.

---

## A2. Role policy and decision rights

Separate persona, role, and policy.

- `Persona` controls voice and interpretive tendencies.
- `Role` describes responsibilities and organisational position.
- `ActorPolicy` controls data visibility and legal actions.

```python
class ActorPolicy(Model):
    role_key: str
    allowed_tools: list[str]
    readable_domains: list[str]
    writable_domains: list[str]
    approval_limits: dict[str, float]
    required_evidence: dict[str, list[str]]
    prohibited_actions: list[str]
```

Add first-class decision rights where required:

```python
class DecisionRight(Model):
    decision_type: str
    accountable_role: str
    approver_roles: list[str]
    veto_roles: list[str]
    consulted_roles: list[str]
```

Policies are compiled from role definitions, executable lore, current assignments, geography, legal entity, and artifact access rules.

### Exit gate

The finance business partner can request a journal but cannot post one. The engineer can propose a production change but cannot approve it. Attempts are rejected without mutating the world.

---

## A3. Typed tool runtime

Tools are deterministic commands over world state.

```python
class ActorTool(Protocol):
    name: str
    input_model: type[Model]

    def authorise(self, actor: Employee, policy: ActorPolicy, state: World) -> None: ...
    def validate(self, arguments: Model, state: World) -> None: ...
    def execute(self, arguments: Model, state: World) -> ToolResult: ...
```

Initial tool families:

### Finance

- `read_ledger`
- `query_budget`
- `query_forecast`
- `create_variance_analysis`
- `request_journal`
- `escalate_close_issue`

### Service management

- `search_incidents`
- `create_incident`
- `update_incident`
- `assign_incident`
- `add_work_note`
- `escalate_major_incident`

### Engineering

- `query_logs`
- `inspect_dependencies`
- `record_hypothesis`
- `create_remediation_issue`
- `propose_change`
- `publish_runbook`

### Artifact creation

- `draft_artifact`
- `submit_for_review`
- `approve_artifact`
- `request_revision`

`draft_artifact` creates an `ArtifactIntent`; the existing artifact and narrative compilers remain responsible for IR, claims, and rendering.

### Exit gate

Every tool has schema tests, permission tests, precondition tests, idempotency tests, and a state-diff fixture proving exactly what it may change.

---

## A4. Event-driven scheduler

Do not run actors continuously. Activate them from explicit triggers.

```text
incident opened
approval requested
reporting deadline reached
threshold breached
message received
task assigned
meeting started
```

The scheduler resolves eligible roles, current assignees, priority, and invocation budget.

```python
class TriggerRoute(Model):
    event_kind: str
    eligible_roles: list[str]
    required_conditions: list[str]
    max_actors: int
    deadline_minutes: int
```

Use deterministic routing first. An LLM director may later resolve genuinely ambiguous actor selection, but it receives no mutation tools.

### Exit gate

A trigger produces the same actor queue from the same world and seed. No actor can recursively schedule itself without a new committed event or task.

---

## A5. First bounded actor episode: retail close incident

Use the existing inventory-valuation failure because its canonical facts, artifacts, and evaluations already exist.

Actors:

1. service desk analyst
2. finance business partner
3. data engineer
4. incident commander
5. group controller
6. CFO

Expected flow:

```text
pipeline failure
→ analyst opens incident
→ finance identifies close dependency
→ engineer records initial hypothesis
→ incident commander requests evidence
→ engineer confirms root cause
→ controller decides whether close moves
→ CFO receives an executive summary
→ remediation actions are assigned
```

Actor tools must produce or trigger:

- ServiceNow incident and work notes
- initial and confirmed hypotheses
- Jira remediation issues
- close-risk escalation
- decision to delay or continue close
- RCA intent
- CFO memo intent
- executive-summary intent

The deterministic scripted actor remains the CI reference. A real model adapter is tested against the same contracts.

### Exit gate

The actor-generated episode reaches the same canonical business outcome as the existing deterministic fixture while producing role-specific intermediate records. Every claim and state transition is attributable to an observation and accepted tool call.

---

## A6. Actor memory

Memory is scoped and typed.

### Stable role memory

Responsibilities, policy, standard operating procedures, vocabulary, incentives.

### Episodic memory

Events and interactions personally observed by that employee.

### Working memory

Current task, incident, report, approval, and unresolved questions.

### Institutional memory

Retrieved through tools from artifacts and systems. It is not injected automatically.

Actor memory should use references to canonical records rather than copied prose wherever possible. Summaries are content-addressed and replayable.

### Exit gate

An actor can retrieve a prior incident and use it in a later decision. Another actor without access cannot. Replay produces the same retrieval set and decision request.

---

## A7. Meetings and negotiation

Model a meeting as a bounded coordination episode, not an unconstrained chat.

```python
class MeetingTurn(Model):
    meeting_id: str
    speaker_id: str
    claims: list[GeneratedClaim]
    proposals: list[Proposal]
    objections: list[Objection]
    tool_calls: list[ActorAction]
```

Each attendee receives private observations and incentives. A deterministic meeting compiler extracts:

- decisions
- dissent
- unresolved questions
- action items
- owners
- deadlines
- follow-up artifact intents

First meeting: the close-risk review between Finance, Engineering, Operations, and the CFO.

### Exit gate

The meeting terminates within a fixed round budget, produces at least one committed decision or explicit unresolved state, and cannot create an action without a named owner and valid authority.

---

## A8. Behaviour and incentives

Add behavioural state only after tools and observations work.

Candidate dimensions:

- workload
- attention budget
- delivery pressure
- confidence
- trust
- political sensitivity
- local objective
- escalation tendency
- evidence threshold

These influence tool selection and framing; they do not override permissions or truth.

Executable lore may adjust distributions by role, team, or individual. Repeated events may update trust and confidence over time.

### Exit gate

Two valid actors in the same role can choose different legal actions for explainable reasons, while both remain bounded by the same policy and evidence requirements.

---

## A9. Multi-episode and cross-period actors

Carry actors across periods so earlier choices matter.

Examples:

- an engineer remembers the workaround from the prior close
- a controller raises the evidence threshold after repeated late adjustments
- an executive loses confidence after consecutive forecast misses
- a departing employee hands open obligations to a successor

Actor identity, observations, tasks, and relationships survive episode boundaries. Role assignments may change independently.

### Exit gate

Generated evaluations can answer:

- who knew the root cause before the close decision?
- which employee repeated a prior workaround?
- which obligation survived an employee departure?
- why did the approval path change between periods?

---

## A10. Evaluation and realism gates

Actor simulation must improve the corpus, not merely add tokens.

Generate evaluation families for:

- information asymmetry
- role authority
- action provenance
- temporal knowledge
- escalation chains
- task ownership
- decision rationale
- conflicting interpretations
- expected abstention

Add actor-specific validators:

- no actor cites an unobserved fact
- no tool exceeds role authority
- every mutation has one accepted tool result
- every artifact author was employed and authorised
- every action owner exists at the action time
- no meeting decision bypasses required approvers
- rejected actions leave no state residue

Realism remains a separate score from coherence. Add sampled human review and, later, a model critic calibrated against accepted enterprise records.

### Exit gate

The actor corpus is measurably harder than the non-actor baseline on temporal, authority, causal, and information-asymmetry evaluations without reducing direct-fact correctness.

---

## A11. Scale model

Do not instantiate one LLM per employee.

A large generated company may contain:

```text
200,000 employee records
300 role archetypes
2,000 employees eligible for simulated activity
20–50 active LLM actors in one consequential episode
```

Use three execution classes:

1. deterministic background actors for high-volume routine activity
2. hybrid policy actors where code handles the ordinary path
3. LLM decision actors for ambiguity, judgement, negotiation, and prose

Add model routing, invocation caching, concurrency limits, cost budgets, and deterministic fallbacks.

### Exit gate

A 10,000-artifact corpus can include multiple actor-driven episodes with bounded model calls, no runaway conversations, and complete replay from the generation ledger.

---

## Proposed package shape

Do not create these modules until their corresponding gate begins.

```text
src/worldloom/actors/
├── __init__.py
├── models.py
├── observation.py
├── policy.py
├── scheduler.py
├── runtime.py
├── memory.py
├── meetings.py
├── registry.py
├── roles/
│   ├── finance.py
│   ├── service_management.py
│   ├── engineering.py
│   └── executive.py
└── tools/
    ├── base.py
    ├── finance.py
    ├── incidents.py
    ├── engineering.py
    ├── artifacts.py
    └── meetings.py
```

Role packs should be ordinary typed data or Python declarations. Avoid a role DSL until two verticals demonstrate recurring structure.

---

## What actors never own

Even at the final gate, actors do not directly control:

- stable IDs
- canonical financial values
- formulas
- clocks and event ordering
- permission resolution
- validity windows
- graph integrity
- source-of-truth selection
- artifact lineage
- evaluation answers
- direct file rendering

Actors choose among permitted actions under incomplete information. The harness decides whether those actions are valid and what they change.

The target is not a multi-agent demo. It is an enterprise simulation in which realistic records emerge from bounded employees doing role-specific work through auditable tools.
