# Python SDK

Use the CLI for a fixed pipeline. Use `worldloom.sdk` when the required corpus
shape is itself a program: a Cartesian product, a parameter sweep, a dispersed
sample, an early-stopping loop, or a filter over measured worlds.

```python
from worldloom import sdk
```

The SDK does not expose a looser version of Worldloom. It rearranges the same
builders, scenarios, validators, compilers, and renderers used by the CLI.

## Mental model

```text
Blueprint                         Built                         World
+----------------------+         +----------------------+      +----------------------+
| immutable description| build() | minted world         |      | canonical typed state|
| safe to cross/filter |-------->| + source blueprint   |----->| queries and scenarios|
| no entities yet      |         | measure/render/export|      | compile/validate      |
+----------------------+         +----------------------+      +----------------------+
```

- `Blueprint` is a value. Every configuration method returns a new blueprint.
- `Blueprint.build()` is the only blueprint operation that mints a world.
- `Built` pairs the minted `World` with the blueprint that produced it.
- `Built.world` exposes the complete query and scenario surface.

Keeping the blueprint beside the result matters in selection loops: after
filtering forty generated worlds, the winning world's configuration remains
available without reverse-engineering it from the output.

## Starting a blueprint

```python
from worldloom import sdk

retail = sdk.company("retail", seed=8128)
bank = sdk.company("banking", seed=8128)
insurer = sdk.company("insurance", seed=8128)
procurement = sdk.company("procurement", seed=8128)
```

`sdk.company(name)` is the registry-driven entry point. It automatically supports
an installed domain. `sdk.engine(name)` is an alias. `sdk.retail()`,
`sdk.banking()`, and `sdk.insurance()` remain convenience functions for existing
callers.

An unknown domain is refused at blueprint construction rather than after an
expensive build.

## Configuring a blueprint

```python
blueprint = (
    sdk.company("retail", seed=8128)
    .seeded(9001)
    .archetype("omnichannel_retailer")
    .staff(80_000)
    .revenue(12_000_000)
    .org(headcount=45, span=6, levels=4)
    .calendar("retail_christmas")
    .located("australia")
    .estate("large")
    .physics(retail_margin_erosion=(0.10, 0.15))
    .master_data(vendors=2_000, customers=5_000, skus=10_000)
)
```

| Method | Meaning |
| --- | --- |
| `.seeded(n)` | Deterministic seed |
| `.archetype(key)` | Specific company shape owned by the domain |
| `.staff(n)` | Authoritative aggregate workforce, distinct from named roster size |
| `.revenue(annual)` | Annual revenue in the archetype's currency unit |
| `.org(headcount=, span=, levels=, functions=)` | Bounded named organisation shape; partial updates preserve earlier fields |
| `.calendar(name)` | Registered trading-year profile |
| `.located(locale)` | Locale and figure grammar; build reach depends on the domain/pack |
| `.estate(size, vocabulary=)` | Technology landscape size and optional vertical vocabulary |
| `.physics(**spans)` | Named parameter ranges; underscores map to dots when unambiguous |
| `.facets(**choices)` | Operational claims such as listing, maturity, competition, and trading pattern |
| `.master_data(**counts)` | Deterministic vendors, customers, SKUs, and shared contacts |
| `.pack(source)` | Authored company identity, shape, lore, voice, and geography |
| `.lob(spec, bind=...)` | Attach an authored line of business and optional process-slot bindings |

Every method validates what it can at the call site. A bad parameter name, unknown
calendar, inconsistent facet combination, invalid master-data collection, or LOB
binding to a missing role fails before build.

### Inspect without building

```python
description = blueprint.describe()
parameters = blueprint.parameters
seasonality = blueprint.seasonality
role_table = blueprint.role_table()
```

`describe()` is the planning surface for large loops. It returns engine, seed,
shape, calendar, estate, locale, revenue, pack, physics, master-data counts,
facets, lore sources, and unmet consequences without minting a fact.

## Build and run episodes

```python
built = blueprint.build()
history = built.episodes("2026-01", periods=3, incident=True)

assert history.ok
print(history.measure())
```

`Built.episodes()` runs the registered domain episode at its declared cadence.
For retail, the episode is `MonthEndClose`; single-episode domains provide their
own scenario factory and period step.

For an explicit scenario sequence, use `run`:

```python
from worldloom import MonthEndClose
from worldloom.scenarios import StructuralChange, WorkforceChange

result = (
    sdk.company("retail", seed=8128)
    .staff(80_000)
    .build()
    .run(
        MonthEndClose(period="2026-01", include_operational_incident=True),
        WorkforceChange(period="2026-02", headcount=82_000),
        StructuralChange(
            period="2026-02",
            business_units=6,
            sites=120,
            systems=18,
            services=40,
        ),
        MonthEndClose(period="2026-02", include_operational_incident=False),
    )
)
```

An explicit sequence is an escape hatch, not a way to disable scenario checks.
Each scenario still reviews preconditions, emits events and facts, records a
recipe step, and returns a new immutable world.

## Combinators

### Cartesian product

```python
base = sdk.company("retail", seed=8128).staff(25_000)

candidates = sdk.cross(
    base,
    calendar=["flat", "harvest", "retail_christmas"],
    estate=["small", "large"],
    org=[
        {"headcount": 24, "span": 4, "levels": 3},
        {"headcount": 45, "span": 6, "levels": 4},
    ],
)

assert len(candidates) == 12
```

Axis names are blueprint methods. A dictionary value is passed as keyword
arguments, so `org=[{"headcount": 24, ...}]` calls `.org(...)`.

`cross` is deliberately honest about cardinality. Six axes with six values are
46,656 blueprints. It does not silently truncate the product.

### One-dimensional sweep

```python
calendars = sdk.sweep(
    base,
    "calendar",
    ["flat", "harvest", "fiscal_year_end"],
)
```

Use `sweep` to isolate the effect of one variable. It is the named degenerate
case of `cross`.

### Consistent facet combinations

```python
company_field = sdk.companies(
    base,
    "listing",
    "competition",
    "maturity",
)
```

`companies` returns only combinations that satisfy facet exclusions. It does not
hand callers a raw product and require each loop to reimplement rules such as
"no listed mutual" or incompatible margin claims.

### Dispersed selection

```python
field = sdk.dispersed(candidates, 8)
```

`dispersed` applies farthest-first traversal to normalized configuration vectors.
Taking the first eight items of a Cartesian product usually varies only its last
axis. Farthest-first selects eight candidates that cover the available space.

Pass a custom numeric key when domain-specific outcome coordinates are more
useful:

```python
field = sdk.dispersed(
    candidates,
    8,
    key=lambda blueprint: (
        blueprint.describe()["shape"]["headcount"],
        len(blueprint.describe()["physics"]),
    ),
)
```

The built-in key normalizes each coordinate across the candidate set so a
headcount range does not dominate a small margin range solely because its units
are larger.

### Existing mosaic and probe spaces

```python
mosaic = sdk.mosaic_of(20, engine="banking", seed=8128)
probed = sdk.probe_of(session, 20, engine="retail", seed=8128)
```

Both return blueprints, not built worlds. Callers can constrain, cross, disperse,
or filter the descriptions before incurring generation cost.

## Lazy build and outcome selection

```python
selected = []

for built in sdk.built(field):
    measures = built.measure()
    if built.ok and measures["chokepoints"] >= 2:
        selected.append(built)
    if len(selected) == 5:
        break
```

`sdk.built()` is an iterator. Stopping after five selected worlds does not mint
the rest.

`Built.measure()` returns:

- active named people;
- distinct titles;
- facts;
- artifact intents;
- evaluation cases;
- active graph nodes;
- chokepoints;
- longest dependency chain.

`Built.topology()` returns the graph subset. `Built.ok` and `Built.validate()`
use the full coherence validator.

Outcome selection should be a filter or Pareto decision, not an optimization
loop against one baseline. Repeatedly tuning candidates until BM25 fails is an
efficient way to overfit the corpus to BM25.

### Selecting a whole field on its measurements

`dispersed` measures the *descriptions*. `outcome_selected` measures the
*corpora*:

```python
worlds = sdk.outcome_selected(candidates, 5)      # returns Built, not Blueprint
```

Every candidate is built, run for one episode, compiled and read; the same
farthest-first traversal then runs over the measurement vector rather than over
the configuration vector. Nothing is narrated or rendered, so a candidate costs
a build rather than a corpus — a pool of thirty retail worlds measures in about
five seconds.

The measurement vector is `worldloom.outcomes.read()`: the eight numbers of
`Built.measure()`, plus `stats.measure` repetition and shape counts,
`stats.compute` lexical texture and citation density, and the evaluation
family and difficulty *mix*. Question text is held separately and enters the
distance as a pairwise overlap term, because two worlds asking the same forty
sentences are two presentations of one benchmark however different their org
charts.

`outcomes.select()` is the safe objective and the only one reachable by
default: it maximizes spread, and nothing that is fit can be overfit.
`outcomes.Pool.hardest()` selects against a single named retriever, warns when
called, and exists to investigate that retriever rather than to build a
dataset.

`mosaic.outcome_field(n, pool=30)` is the same loop over the mosaic's own
candidates. `tools/outcome_selection.py` compares it against
`mosaic.field(n)` on the metrics `evaluate.across` already reports; the
comparison and its mixed result are summarized in the changelog.

## Company descriptions

`sdk.described()` resolves the same company specification accepted by
`worldloom build --spec`:

```python
specification = {
    "industry": "General insurance",
    "geo": "germany",
    "facets": {
        "listing": "listed",
        "competition": "fragmented",
        "maturity": "legacy",
        "trading_pattern": "steady",
    },
    "organisation": {"headcount": 32, "span": 5, "levels": 3},
    "identity": {
        "company_name": "Rheinmark Versicherung",
        "headquarters": "Munich, Germany",
    },
}

blueprint = sdk.described(specification, seed=8128)
```

The specification is resolved before a blueprint is returned. Contradictions
between industry, scale, revenue, facets, roles, locale, and pack identity are
reported together. The resulting blueprint can then participate in every SDK
combinator.

Use `strict=False` only to inspect a conflicted resolution. It does not relax
downstream build invariants.

## Lines of business and participation

```python
from worldloom import episodes, lob

finance = lob.Lob.model_validate(finance_document)
close = episodes.load("close-process.json")

blueprint = sdk.company("retail").lob(
    finance,
    bind={"MonthEndClose": {"preparer": "controller"}},
)

participants = blueprint.participation(close)
```

LOB roles extend the organisation. Responsibility edges and process-slot
bindings derive participation; they are not copied into a second manually
maintained roster.

## Querying a world

The underlying `World` exposes typed collections:

```python
world = result.world

finance = world.people.where(function="Finance")
causes = world.facts.where(kind="ops.cause")
incidents = world.events.where(kind="incident_opened")

one_controller = world.people.where(title="Group Financial Controller").one()
first_case = world.evaluations.first()
```

Collections implement `where`, arbitrary-predicate `filter`, `first`, `one`, and
standard sequence behavior. Conversion bridges are optional:

```python
people_polars = world.people.to_polars()
facts_pandas = world.facts.to_pandas()
events_arrow = world.events.to_arrow()
```

Temporal, authority, visibility, and provenance questions are first-class:

```python
snapshot = world.as_of("2026-04-01T10:00:00+00:00")
roster = world.org_at("2026-04-01T10:00:00+00:00")
visible = world.visible_to(one_controller.id)
current = world.authoritative("ops.cause", "SVC-0001")
lineage = world.provenance("ART-0003")
```

Avoid recreating these semantics with ad hoc joins. Validity, authority, access,
and restatement are part of the model and can be lost in a naive dataframe merge.

## Export and render

```python
path = result.export("./canonical-corpus")

rendered = result.render(
    "xlsx",
    "docx",
    "pptx",
    "pdf",
    "markdown",
    out="./rendered-corpus",
)
```

`export` writes canonical state and any already-rendered artifacts. `render`
compiles if needed, projects the requested native formats, and exports the
result. Structured Jira, Confluence, and ServiceNow bundles are most commonly
driven through the CLI renderer path.

## Direct world classes

The top-level package exports the four shipped builders and episodes:

```python
from worldloom import (
    BankingWorld,
    InsuranceWorld,
    MonthEndClose,
    ProcureToPayWorld,
    PurchaseToPayCycle,
    QuarterlyCapitalReturn,
    QuarterlyReserving,
    RetailWorld,
    World,
)
```

Use these classes when implementing or testing a vertical. Use `sdk.company()`
for registry-driven application code.

Load an existing corpus with:

```python
world = World.load("./corpus")
world.validate().raise_if_failed()
print(world.summary())
```

A loaded corpus is intentionally not a builder. Evidence should not acquire
unrecorded generator state merely because it was opened in Python.

## CLI versus SDK

| Requirement | Prefer |
| --- | --- |
| One build with known flags | CLI |
| Sharded/resumable mosaic | CLI |
| Agent request/accept handshake | CLI and JSON |
| Cross, sweep, or dispersed candidate program | SDK |
| Filter based on generated topology or counts | SDK |
| Explicit custom scenario sequence | SDK |
| Reusable application integration | SDK |
| Exact operator command and machine-readable status | CLI |

The distinction is arrangement, not capability or safety. If a single command
already expresses the operation, the CLI is the more observable production
surface. If the operation contains a loop, the SDK is the native representation.
