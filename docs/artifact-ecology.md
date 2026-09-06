# Artifact ecology

Design a set of artifacts around the roles, events, and business processes
that produce them. Use the coverage and relationship checks below to identify
missing context before generating more files.

File count, format count, and functional breadth measure different properties.
Assess them separately and retain the admission result with the corpus.

```text
World facts + events + actors
            |
            v
      business episode
            |
    +-------+--------+---------+---------+
    |       |        |         |         |
  email   SNOW     Jira    Confluence   IR
    |       |        |         |         |
    |       |        |         |     +---+---+
    |       |        |         |     |   |   |
    |       |        |         |   XLSX DOCX PPTX/PDF
    +-------+--------+---------+---------+
                    |
                    v
              realism gates
```

## The two invariants

**Truth is upstream of presentation.** Artifact ecology never creates a business number. PPTX charts, DOCX/PDF tables, and XLSX formulas remain projections of Artifact IR and its cited facts.

**Variation is addressed, not drawn from a shared random stream.** Organization, department, artifact, and surface choices use named deterministic streams. Adding one artifact cannot reshuffle the style of every other artifact.

## Organization DNA

`organisation_dna(seed, company_id, industry)` describes stable house behavior: density, tone, style archetype, chart preference, title conventions, footer behavior, and similar presentation choices.

`department_dna(...)` mutates that house style within bounded limits. Finance can be denser and more controlled than Operations while still looking as if both artifacts came from the same company.

`plan_for(...)` derives an artifact-local surface plan. Surface plans select from a small grammar, not from hundreds of templates.

Examples of bounded families:

| Surface | Families |
| --- | --- |
| PPTX | decision story, operating review, metric narrative, incident brief, board update |
| DOCX/PDF | memo, operating pack, controlled document, RCA, brief |
| XLSX | controller model, analyst model, operational tracker, reconciliation pack |
| ServiceNow | major incident, standard incident, problem/change chain |
| Jira | delivery issue, defect remediation, control remediation |
| Confluence | knowledge tree, RCA space, operating handbook |
| Email | working thread, escalation thread, approval thread, handoff thread |

Families decide information architecture. They do not decide facts.

## Lifecycle and provenance

Every ecology artifact has a deterministic lifecycle derived from simulated world time. Draft, review, approval, publication, supersession, and archival are provenance, not decorative labels.

Word and PDF keep lifecycle/revision/family metadata in document properties. XLSX carries a hidden Document Control sheet. Connector records carry their own native histories.

No lifecycle path uses wall-clock `now()`.

## Product-specific evidence

### ServiceNow

ServiceNow records carry incident/change semantics, assignment groups, affected services/CIs, SLA information, state history, work notes, and related-record links. State and work-note timestamps advance from the simulated incident time.

### Jira

Jira represents delivery/remediation work. It carries project/issue semantics, status history, comments/activity, labels, links, and ownership. It is intentionally not a ServiceNow record with renamed fields.

### Confluence

Pages exist in spaces and page trees. Ecology adds owners, versions, labels, parent relationships, backlinks, macros, and canonical navigation identifiers.

### Email

Messages preserve thread identity, reply references, recipients, Cc, attachment references, client/signature variation, and conversation ordering. A reply must reference a message that exists in the generated corpus.

## Office artifacts

### PPTX

Ecology density feeds the existing semantic component planner. Airy, balanced, and compact decks select different valid component mixes while keeping chart/table data fact-backed. Organization style remains correlated through the shared style seed.

### XLSX

Existing Worldloom workbooks already use formulas, named ranges, lineage, reconciliation, and charts tied to cells. Ecology adds analyst affordances without introducing independent data: filters on fact/detail tables and a hidden Document Control sheet containing only provenance/style metadata.

### DOCX and PDF

Both formats use the same Artifact IR. Ecology adds deterministic style selection and machine-readable lifecycle/revision/family metadata. The control metadata stays out of ordinary readable prose.

## Python

```python
from worldloom import MonthEndClose, RetailWorld
from worldloom.ecology import connectors, prepare, render

world = RetailWorld(seed=8128).build().run(
    MonthEndClose(period="2026-03", include_operational_incident=True)
)

prepared = prepare(world)
print(prepared.profile)
print(prepared.realism)

rendered = render(prepared.world, "xlsx", "docx", "pdf", "pptx")
records = connectors(prepared.world, ("servicenow", "jira", "confluence", "email"))
```

Ordinary Worldloom generation remains model-free. Harnesses are optional proposal engines.

## Harnesses

The artifact-realism skill in `.claude/skills/worldloom-artifact-realism/SKILL.md` defines the collaboration boundary.

A model may propose prose, emphasis, structure, or one of the bounded families. `review_proposal` rejects unsupported fact references and ungrounded numeric claims. The host owns acceptance. Model output cannot relax limits or validators.

## Realism is measured

`worldloom.realism.evaluate` reports structural diversity, lifecycle validity, graph connectivity, cross-surface coverage, and evidence grounding. These metrics are gates and search objectives; they are not claims that a synthetic corpus empirically matches a specific customer.

The distinction matters. Structural realism can be tested mechanically. Distributional realism requires calibration data and remains a separate problem.

## Adding a surface family

Prefer one composable grammar over many templates.

1. Add the bounded family to `_FAMILIES`.
2. Describe its structural roles in `plan_for`.
3. Reuse Artifact IR facts/tables instead of adding a second content model.
4. Add product-specific chronology/provenance rules if the surface is a business system.
5. Add deterministic tests: same seed stable; another seed can vary; no dangling references; no invented numeric claims.
6. Run existing renderer tests as well as the new tests.

If adding the family requires bypassing Artifact IR or creating independent numbers, the abstraction is wrong.

## Current boundary

Artifact ecology improves structural, temporal, visual, and cross-surface realism. It does not claim to fit a real customer's document distribution, brand system, writing culture, ticket statistics, or spreadsheet conventions. Those require calibration corpora and privacy-aware fitting. The layer is designed so calibrated parameter distributions can replace authored defaults later without changing the truth and replay contracts.
