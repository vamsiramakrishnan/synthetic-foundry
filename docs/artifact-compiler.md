# Artifact compiler

Worldloom already has the correct semantic boundary:

```
World → events → facts → ArtifactIntent → ArtifactIR → renderer
```

The next rendering problem is not "ask a model to make a PowerPoint". It is to compile one resolved `ArtifactIR` into many native, useful, visibly different artifacts without allowing format-specific code to invent meaning.

This document defines that compiler in terms of the contracts that exist today:

- `ArtifactIR`, `ArtifactSection`, `Table`, `Chart`, `Cell`, and `FormulaKind` in `worldloom.models`
- the format registry and `Rendered` result in `worldloom.render`
- fact-reference substitution and claim validation in `worldloom.narrative`
- XLSX and DOCX as current native renderers
- Jira, Confluence, and ServiceNow as portable bundle renderers
- deterministic generation, generation-ledger replay, and corpus validation as non-negotiable properties

The proposal extends those contracts. It does not introduce a second artifact model, allow a renderer to read the world directly, or move arithmetic and truth into an LLM.

---

## 1. The technique

Use **constrained procedural artifact synthesis**:

```
Resolved ArtifactIR
      ↓
format compiler
      ↓
component assignment
      ↓
constraint-valid composition
      ↓
deterministic native rendering
      ↓
structural and visual validation
      ↓
bounded repair or resampling
```

An LLM may help choose narrative emphasis, semantic component families, or bounded repairs. It never owns coordinates, formulas, facts, identifiers, dates, or final acceptance.

The useful unit is not a PowerPoint template or a Word paragraph style. It is a typed, reusable **artifact component** with a semantic role and measurable capacity.

Examples:

- metric strip
- variance table
- revenue bridge
- timeline
- decision panel
- risk matrix
- executive callout
- financial statement
- document-control block
- approval table
- reconciliation block

A rounded rectangle is too low-level. A complete board-deck template is too high-level. Components sit between those extremes.

---

## 2. Preserve the existing thin waist

`ArtifactIR` remains format-independent and resolved. It continues to own:

- title and subtitle
- ordered sections
- section purpose
- prose
- fact references
- resolved tables
- declared charts
- declared formulas
- metadata

The artifact compiler introduces a format-local plan after `ArtifactIR`:

```python
ArtifactIR
    -> PresentationPlan
    -> DocumentPlan
    -> WorkbookPlan
```

These plans are renderer concerns. They must not be persisted as canonical enterprise truth and must not introduce new business values.

A plan may decide:

- which slide or page receives a section
- which compatible component presents a table
- whether detail moves to an appendix
- whether a document section becomes landscape
- where a workbook report region is placed
- which style genome is used

A plan may not decide:

- which facts are true
- which rows belong in the table
- which series a chart represents
- how a variance is calculated
- what an author knew at a point in time
- which artifact should exist

Those decisions already belong upstream.

---

## 3. Component registry

Add a renderer-local component registry rather than widening the top-level plugin system prematurely.

```python
@dataclass(frozen=True)
class ComponentSpec:
    id: str
    formats: frozenset[str]
    semantic_roles: frozenset[str]
    accepted_content: frozenset[str]
    min_width: float
    min_height: float
    preferred_aspect_ratios: tuple[float, ...]
    min_density: float
    max_density: float
    incompatible_with: frozenset[str]
    validator_ids: tuple[str, ...]
```

A concrete component implementation receives only resolved content plus a format plan:

```python
class PptxComponent(Protocol):
    spec: ComponentSpec

    def measure(self, content: ResolvedContent, style: StyleGenome) -> Measurement: ...
    def draw(self, canvas: SlideCanvas, box: Box, content: ResolvedContent, style: StyleGenome) -> None: ...
```

The registry initially lives under each renderer:

```
worldloom/render/pptx/components/
worldloom/render/docx/components/
worldloom/render/xlsx/components/
```

Only extract a shared package once at least two native renderers require the same behaviour rather than merely sharing names.

### Initial PPTX component set

Build 20–30 strong components first:

- title slide
- section divider
- executive summary
- statement slide
- metric strip
- KPI grid
- variance table
- financial summary table
- bar chart
- line chart
- waterfall
- timeline
- causal chain
- options matrix
- decision request
- risk matrix
- milestone plan
- before/after
- evidence-and-interpretation
- recommendation and next steps

### Initial DOCX component set

- cover
- document control
- revision history
- executive summary
- heading and prose block
- callout
- table
- figure and caption
- financial statement
- decision record
- risk table
- approval block
- appendix
- portrait/landscape section boundary

### Initial XLSX component set

The workbook is an executable dependency graph, not a slide canvas:

- cover sheet
- assumptions sheet
- raw-data table
- calculation table
- report table
- KPI band
- variance table
- trend chart
- bridge chart
- conditional-format band
- control check
- reconciliation sheet
- lineage sheet

The current XLSX renderer already has the most important property: formulas are declared in IR and rendered rather than invented. The component layer should preserve that and focus on placement, styling, and sheet composition.

---

## 4. Artifact grammars

Components are assembled through a grammar. This prevents technically valid but organisationally absurd combinations.

### Presentation grammar

```
Deck
  := Opening Body+ Closing Appendix*

Opening
  := Title | Title ExecutiveSummary

Body
  := SectionDivider
   | EvidenceSlide
   | ComparisonSlide
   | TimelineSlide
   | DecisionSlide
   | TableSlide
   | ChartSlide
   | MixedEvidenceSlide

Closing
  := DecisionSummary | Recommendations | NextSteps
```

The grammar consumes the ordered `ArtifactSection` list. It does not reorder facts freely. A planner may split one dense section or combine adjacent sparse sections when their purposes are compatible.

### Document grammar

```
Document
  := FrontMatter ExecutiveSummary? Section+ Appendix* BackMatter?

Section
  := Heading Block+

Block
  := Paragraph | Table | Figure | Callout | List | DecisionRecord
```

### Workbook grammar

```
Workbook
  := Cover? InputSheet* CalculationSheet* ReportSheet+ ReconciliationSheet LineageSheet
```

Recipes should constrain the permitted grammar productions by artifact type. An incident RCA and a CFO memo should not share the same document skeleton merely because both render to DOCX.

---

## 5. Planning without semantic drift

Introduce a deterministic format planner:

```python
class FormatPlanner(Protocol):
    def plan(self, artifact: ArtifactIR, context: RenderContext) -> FormatPlan: ...
```

`RenderContext` may contain:

- artifact type
- size profile
- style genome
- target dimensions
- deterministic RNG namespace
- renderer capabilities

It must not contain the `World` or fact ledger. The renderer still reads resolved IR and nothing else.

### Planning phases

1. Classify each section by semantic role from `purpose`, table shape, chart declaration, and prose/table balance.
2. Enumerate compatible components.
3. Generate a small number of candidate assignments.
4. Solve hard composition constraints.
5. Score valid candidates.
6. select deterministically using a namespaced seed.

The LLM may propose a semantic family when the section purpose is genuinely ambiguous, but its proposal is validated against the registry and recorded in the generation ledger. The ordinary path should remain deterministic.

---

## 6. Constraint solving

Use two levels of constraints.

### Global assignment

Use OR-Tools CP-SAT when the renderer has enough components to make greedy packing brittle.

Variables represent:

- component chosen for each semantic block
- slide/page/sheet assignment
- optional appendix promotion
- allowed grouping of adjacent blocks

Hard constraints include:

- every required section is represented
- no component receives unsupported content
- maximum capacity is not exceeded
- incompatible components do not share a page
- title, closing, and appendix ordering is valid
- size-profile bounds are respected

The objective can reward:

- semantic fit
- coherent narrative progression
- balanced density
- style compatibility
- component diversity

and penalise:

- overflow risk
- repeated layouts
- unnecessary slides or pages
- excessive fragmentation
- appendix bloat

CP-SAT should be optional. For the first PPTX renderer, a deterministic candidate enumerator plus scored greedy assignment is likely sufficient. Introduce the solver only when tests demonstrate a real composition failure class.

### Local geometry

Use a Cassowary-compatible solver such as `kiwisolver` for slide regions and responsive page frames.

Variables:

```
x, y, width, height
```

Constraints:

- margins
- gutters
- alignment
- minimum component size
- preferred aspect ratio
- title/body/footer relationships
- non-overlap

Do not use a solver for worksheet cells. Workbook placement is grid allocation and dependency management, not free geometry.

---

## 7. Diversity is a batch property

Random layout selection is not diversity. It produces repeated patterns with cosmetic noise.

Represent each rendered plan with a feature vector:

```python
@dataclass(frozen=True)
class ArtifactFingerprint:
    narrative_shape: tuple[str, ...]
    component_sequence: tuple[str, ...]
    layout_sequence: tuple[str, ...]
    chart_kinds: tuple[str, ...]
    density_buckets: tuple[int, ...]
    style_genome_id: str
    page_or_slide_count: int
```

Use three mechanisms.

### Recency-aware weighted sampling

Reduce the probability of component and layout sequences recently emitted for the same artifact family.

### Batch quotas

A generation run can declare:

```yaml
diversity:
  minimum_unique_layout_ratio: 0.35
  maximum_component_family_share: 0.25
  maximum_repeated_layout_run: 2
  minimum_style_genomes: 4
```

### Candidate-set selection

When generating a batch, choose among valid plans using max-min distance or a determinantal point process over fingerprints. The objective is high individual quality plus low pairwise similarity.

Do not use embeddings as the only diversity signal. Structural fingerprints are transparent, deterministic, and directly tied to the thing being diversified.

---

## 8. Style genomes, not template explosion

A style genome parameterises a coherent visual system:

```python
@dataclass(frozen=True)
class StyleGenome:
    id: str
    type_scale: tuple[float, ...]
    spacing_scale: tuple[float, ...]
    title_alignment: str
    whitespace_bias: float
    table_density: str
    border_weight: float
    corner_radius: float
    chart_gridline_policy: str
    image_treatment: str
    colour_roles: Mapping[str, str]
```

Worldloom should ship a small number of opinionated genomes, not hundreds of complete templates:

- editorial neutral
- finance compact
- executive sparse
- operating review
- technical architecture

A genome is deterministic data and can be versioned, tested, and fingerprinted.

Template ingestion comes later. When added, ingest templates as:

- style reservoirs
- slide/page skeletons
- placeholder measurements
- spacing relationships
- colour roles

Do not make a template the source of semantic structure.

---

## 9. Format-specific architecture

### 9.1 PPTX

Add `worldloom.render.pptx` only after its IR contract and validation fixtures are defined.

Recommended first implementation:

- stay in Python and use `python-pptx` to match the current package and OOXML normalisation path
- reuse `render/ooxml.py` for deterministic package timestamps
- introduce a TypeScript/PptxGenJS worker only if chart or layout fidelity creates concrete limitations

Pipeline:

```
ArtifactIR
→ PresentationPlan
→ slide components
→ geometry solve
→ python-pptx
→ OOXML normalisation
→ structural validation
→ optional raster validation
```

The renderer should initially target one artifact: the executive summary already emitted by the retail-close episode. That creates a direct cross-format test against Markdown and DOCX.

### 9.2 DOCX

The existing renderer is intentionally sober. Evolve it into block composition rather than replacing it.

Add:

- typed front-matter components
- section-orientation planning
- table-capacity measurement
- explicit keep-with-next and row-splitting rules
- derived PDF preview for pagination validation

The canonical test remains cross-format semantic equality. Pagination quality is an additional gate, not a substitute.

### 9.3 XLSX

Keep XlsxWriter/openpyxl choices subordinate to the current IR contract.

Add:

- workbook plan
- semantic sheet roles
- report-region components
- chart-placement policies
- conditional-format rule objects
- workbook fingerprint

Do not let an LLM emit formulas or cell addresses. `FormulaKind` and operands remain the only formula source. If formula expressiveness grows, add a typed formula AST upstream and compile it to Excel syntax.

### 9.4 PDF

PDF remains derived by default:

```
DOCX → PDF
PPTX → PDF
```

A native PDF renderer is justified only for an artifact whose canonical form is PDF, such as a statement, certificate, or regulatory form. It must consume the same IR.

### 9.5 Jira, Confluence, and ServiceNow

These are record projections, not layout-generation surfaces. Do not force visual-component abstractions into them.

Their diversity comes from:

- workflow histories
- comment patterns
- field completeness
- page hierarchy
- attachment topology
- lifecycle state
- authority and permission patterns

They continue to use portable bundles before live publishers.

---

## 10. Images and diagrams

Charts remain declarations over resolved tables, as they are today.

For diagrams, introduce a graph IR rather than allowing an image model to draw architecture semantics:

```python
class Diagram:
    nodes: list[DiagramNode]
    edges: list[DiagramEdge]
    layout: DiagramLayout
```

Compile this to SVG using Graphviz, ELK, or a deterministic layered layout, then embed the SVG in PPTX, DOCX, or PDF.

Generated or sourced images require an `ImageIntent` with:

- semantic role
- subject
- aspect ratio
- composition requirement
- permitted treatment
- provenance

The image pipeline validates dimensions, crop, saliency, and overlay-safe regions. Image bytes never become untracked anonymous decoration.

---

## 11. Render, critic, repair

Worldloom already has a large deterministic validator. Extend it in layers.

### Static validation

Before native rendering:

- every required section has a component
- every component accepts its content
- all tables and chart references remain valid
- size and density budgets are feasible
- all fonts and assets resolve

### Package validation

After rendering:

- OOXML opens
- deterministic timestamps are normalised
- required metadata is present
- expected slide/page/sheet counts hold
- no artifact fact references were lost

### Visual validation

Canonicalise visual outputs:

```
PPTX → slide images
DOCX → PDF → page images
XLSX → defined print regions or HTML previews
PDF → page images
```

Measure deterministic signals first:

- overlap
- clipping
- text overflow
- whitespace ratio
- alignment
- minimum font size
- table density
- chart-label collision
- orphan headings
- empty pages

A multimodal critic is optional and advisory. It may emit only bounded repair operations:

- split
- merge
- replace component
- resize
- reflow
- shorten title
- reduce rows
- transpose table
- move detail to appendix

Each repair is recorded, re-rendered, and revalidated. The critic cannot rewrite facts or unrestricted prose.

---

## 12. Candidate generation and selection

Do not fully render a combinatorial set.

For one artifact:

```
1 resolved IR
× 3 component assignments
× 2 layout variants
× 2 compatible style genomes
= 12 structural candidates
```

Use staged elimination:

```
12 candidates
→ hard-constraint filter
→ semantic and density scoring
→ top 2 native renders
→ visual validation
→ best accepted result
```

A suggested score:

```text
semantic fit           0.30
constraint fitness     0.25
narrative continuity   0.15
visual quality         0.15
batch novelty          0.10
style fitness          0.05
```

Weights belong to versioned renderer policy, not prompts.

---

## 13. Libraries and algorithms

Keep the control plane in Python unless a concrete renderer forces a worker boundary.

| Need | Recommended |
| --- | --- |
| Typed contracts | Pydantic, existing Worldloom models |
| Data preparation | Polars, Arrow, DuckDB |
| Assignment constraints | OR-Tools CP-SAT, introduced only when needed |
| Geometry constraints | kiwisolver |
| Structural diversity | NumPy/SciPy, scikit-learn, custom fingerprints |
| PPTX | python-pptx first; PptxGenJS worker only on demonstrated need |
| DOCX | python-docx, existing renderer |
| XLSX | current renderer stack; openpyxl for inspection and template mining |
| PDF inspection | PyMuPDF |
| Diagrams | Graphviz or ELK to SVG |
| Image processing | Pillow; Sharp only if a TypeScript worker exists |
| Property tests | Hypothesis |

The architectural rule is more important than the exact library:

> Libraries render and solve. They do not decide enterprise truth.

---

## 14. Implementation order aligned to the branch

The branch has already landed the world, event/fact ledger, artifact planning, narrative handshake, XLSX, DOCX, bundles, evaluations, deterministic replay, and validation. The next work should therefore be:

### A. PPTX vertical slice

1. Add `PresentationPlan`, `SlidePlan`, `Box`, and `StyleGenome` under `worldloom.render.pptx`.
2. Implement 8–10 components sufficient for the existing executive summary.
3. Render the retail-close executive summary to six slides.
4. Normalise OOXML timestamps through the existing helper.
5. Test semantic equivalence against the Markdown and DOCX versions.
6. Add deterministic structural checks for shape overlap, bounds, slide count, and font floor.

### B. Generalise only after the slice

1. Extract component registry and measurement protocol.
2. Add two additional layout families per component.
3. Add plan fingerprints and batch diversity reports.
4. Add candidate generation and deterministic selection.
5. Add three style genomes.

### C. Strengthen DOCX and XLSX

1. Add a DOCX document plan for orientation, front matter, and pagination hints.
2. Add an XLSX workbook plan for semantic regions and chart placement.
3. Keep both downstream of the same `ArtifactIR`.
4. Add cross-format and formula-equivalence tests.

### D. Visual harness

1. Add optional LibreOffice/MuPDF preview adapters behind capability detection.
2. Compute deterministic visual metrics.
3. Add bounded repair operations.
4. Add an optional multimodal critic adapter only after deterministic repair cases exist.

### E. Scale and diversity

1. Fingerprint each format plan.
2. Report diversity per generation batch.
3. Add recency-aware sampling.
4. Add max-min candidate selection.
5. Introduce CP-SAT only if greedy planning fails recorded fixtures.

---

## 15. Exit gates

### PPTX Gate

- one executive deck renders from existing IR
- no facts or values are introduced by the renderer
- deck content agrees with Markdown, DOCX, and XLSX
- the same seed and ledger produce byte-identical normalised OOXML
- all shapes remain in bounds and non-overlapping

### Component Gate

- at least three artifact types compile through reusable components
- components have measured capacity and explicit compatibility
- no artifact-specific `if` chain is required inside generic layout code

### Diversity Gate

- a 100-artifact batch meets declared structural diversity quotas
- diversity does not reduce coherence or validation pass rate
- fingerprints and selection are reproducible

### Visual Gate

- every native artifact has a canonical preview
- deterministic visual validators catch seeded overflow, clipping, and orphan fixtures
- repairs are bounded, replayable, and preserve semantic equality

### Scale Gate

- planning and fingerprinting stream without loading the corpus
- candidate generation is bounded per artifact
- renderer failures isolate to one artifact and resume correctly

---

## 16. Non-goals

Do not build yet:

- an unconstrained prompt-to-PPTX agent
- LLM-authored formulas
- a universal canvas abstraction shared by slides, pages, and worksheets
- hundreds of templates
- a mandatory TypeScript runtime
- a vision critic as the only quality gate
- a graph database for artifact composition
- distributed rendering before local generation is semantically stable
- live Jira, Confluence, or ServiceNow publishing as part of the artifact compiler

The compiler succeeds when a finite library of high-quality components can produce a large family of native artifacts while every artifact remains a faithful projection of one resolved structure.
