# Configure native business-data tactics

`NativeScenarioDemand.realism` controls population and presentation through the
existing scenario recipe, relational simulator and artifact renderers. It is
optional. Omitting it preserves the earlier recipe and generated facts.

```python
from worldloom import RetailWorld
from worldloom.benchmarks import (
    NativeRealismProfile, NativeScenarioDemand, build_native_scenarios,
)

source = RetailWorld(seed=8128).build()
built = build_native_scenarios(source, NativeScenarioDemand(
    episodes=6,
    realism=NativeRealismProfile(
        line_count=12,
        budget_spread="zipf",
        exception_rate=0.25,
        decision_placement="back",
        row_order="varied",
        comparison_detail="variance",
        line_commentary="largest_variance",
        revision_views=("opened", "reviewed"),
    ),
))
built.verify_source_replay()
rendered = built.render(formats=("docx", "pptx", "xlsx"))
measurements = [episode.realism for episode in built.episodes]
```

| Tactic | Configuration | What changes |
| --- | --- | --- |
| Population size | `line_count`: 3–64 | Canonical transaction lines and their derived facts |
| Concentration | `budget_spread`: authored, lognormal, zipf | Per-line allocation; the cohort budget total remains exact |
| Distribution shape | `lognormal_sigma`, `zipf_exponent` | Parameters for the existing allocation mechanisms |
| Exception prevalence | `exception_rate`: 0–1 | Rounded share of unresolved obligations; downstream amounts recalculate |
| Decision placement | authored, front, middle, back, varied | The decision's authored section position |
| Row ordering | authored, reversed, varied | Table presentation with the same fact bindings |
| Comparison detail | ratio, variance, amounts | Existing calculated columns included in the presentation |
| Narrative detail | none, largest_variance, all | Fact-bound line commentary |
| Revision views | opened, reviewed | Working assessments containing only evidence available at issue |

Population tactics change canonical values through the simulator. Presentation
tactics preserve facts and IDs. Independent named random streams keep a change
in presentation from perturbing population draws. Revision files, format copies
and presentation variants retain their source ancestry.

Each episode reports realised exception counts, allocation concentration,
numeric/formula/table/narrative counts, distinct projected facts, decision
position and the first section containing each fact. These measurements do not
claim Word pagination, exclusive deep evidence or subjective realism. Moving
the decision section does not conceal an earlier table containing the answer.

The CLI consumes this profile inside the existing scenario demand JSON:

```json
{
  "episodes": 6,
  "batch_id": "close-scenarios",
  "realism": {
    "line_count": 12,
    "budget_spread": "lognormal",
    "lognormal_sigma": 0.9,
    "exception_rate": 0.25,
    "revision_views": ["opened", "reviewed"]
  }
}
```

Pass that demand to `worldloom native-evals scenarios` with the workload plan,
training/held-out family counts and output directory described in
[the native benchmark workflow](native-benchmark-workflow.md).

The built-in native processes remain supplier reconciliation, customer
settlement and inventory replenishment. These are authored distributions;
there is no claim that the default parameters fit a particular enterprise.
Use the existing calibration and fidelity mechanisms when reference data is
available. Scanned evidence, advanced workbook semantics, multilingual prose
and wider native process coverage remain distinct generation/evaluation gaps.
