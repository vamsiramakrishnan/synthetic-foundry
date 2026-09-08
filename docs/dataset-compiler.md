# Compile a dataset, not a row count

`DatasetPlan` declares the population cells, exact row quotas, repetition caps,
minimum executable task families and companies, split policy and finite budget.
The compiler generates missing coverage through the existing company SDK,
episodes and operational projections. It independently qualifies the resulting
queries before they can consume a quota. Increasing a seed or repeating a
template cannot override admission.

```bash
worldloom evals dataset compile examples/datasets/retail-banking.json --out ./dataset
worldloom evals dataset verify ./dataset
worldloom evals dataset compile examples/datasets/retail-banking.json --out ./dataset --replay
```

The example requests 1,000 rows across retail inventory and banking arrears,
with ordinary execution and partial-write strata. It uses the eight executable
DAG templates wherever the connectors admit them. This is two business
workflows, not a claim of full retail or banking coverage. Add actual
`ScenarioProfile` workflows and their company generation sources to extend the
population; renaming a workflow will not create another executable task family.

## One contract drives generation and acceptance

1. Resolve each source's company specification. Conflicts refuse at plan load;
   unacknowledged unmet company claims refuse generation. `acknowledged_unmet`
   can name exact resolution findings accepted as limits of this dataset; both
   the findings and acknowledgments remain in every source receipt. The banking
   example acknowledges that the engine does not model a retail trading year.
   It does not assert that this mechanism exists. Episodes and simulators retain
   ownership of facts. No new business truth store is introduced.
2. Schedule unfinished strata fairly. Prefer the larger proportional deficit
   within a scheduling round; an impossible cell cannot monopolize the budget.
3. Produce a bounded `DatasetRequest`: deterministic seed, missing count,
   source contract, refusal counts and samples of saturated task/request keys.
4. Build a World using the existing SDK. Apply the declared scenario and source
   selectors, and remove equivalent plans before materializing fixtures.
5. Run existing strict source, evidence and connector-execution qualification.
   Rank the surviving batch by current task, request and case occupancy. Only
   admissions consume quotas; excess repetition remains a finding.
6. Reserve capacity for minimum task/company counts. At the final slot, verify
   that all requested splits can be populated without cutting a leakage group.
   If the candidate cannot meet that contract, keep generating within budget.
7. Checkpoint the exact World, shared connector records, fixtures and proofs.
   Compute splits over connected components of the selected evidence. Export a
   publishable queryset only when every declared obligation is met.

The compiler intentionally does not optimize a claimed semantic quality score.
Task fingerprints measure the actual labelled executable DAG, source field and
format obligations, mutation outcome and artifact contract. They ignore workflow
names, inert topology labels, company IDs and individual case predicates. The
directed structural hash is invariant under node renaming and independent-node
ordering; residual structural collisions merge families conservatively. It is
not a complete semantic equivalence test for natural language or arbitrary code.

Request identity removes generated case suffixes, company names and numeric/ID
literals before normalizing tokens. `max_per_request` limits repeated normalized
wording across companies. This is deterministic template deduplication, not a
claim of semantic near-duplicate recall. Changing numbers does not earn another
language family; genuine task differences remain in the executable contract.

## Dataset-level identity and isolation

| Identity | What owns it | Use |
| --- | --- | --- |
| Task | Executable graph and generation contract | Task minimum and repetition cap |
| Case | Selected source evidence, independent of fault variant | Counterfactual/variant cap and split isolation |
| Request | Normalized prompt, independent of company/record suffix | Template repetition cap |
| Company | Generated company content | Minimum companies and company-disjoint split option |
| Evidence | Actual source records, canonical facts and operational observations | Transitive leakage isolation |

With `split_by="task"` (default), the same executable family stays in one split.
With `split_by="company"`, all selected tasks from a company stay together, but
task families may recur in different splits. Both policies always co-locate
shared evidence and related cases. Choose the generalization question explicitly.

The union-find pass takes the transitive closure before assigning anything:
if A shares evidence with B and B with C, all three remain together. Whole
components are assigned largest-first toward the requested weights, reserving
components for still-empty splits. Weights are proportions, not exact row
quotas. The report exposes actual counts and the largest component. A giant
connected component can make the split contract infeasible; it is never cut to
make a ratio look better.

## SDK and existing harness integration

```python
from pathlib import Path
from worldloom.evals import DatasetPlan, compile_dataset

plan = DatasetPlan.model_validate_json(
    Path("examples/datasets/retail-banking.json").read_text()
)
run = compile_dataset(plan, "./dataset")
run.raise_if_incomplete()
```

A `DatasetBuilder` supplies a stable `id` and `__call__(DatasetRequest) ->
DatasetBuild`. The plan seals the builder ID. Custom adapters should derive it
from both their code version and full generation configuration; a hidden model
or prompt change must not reuse the old identity. A custom builder may reuse
`candidate_builder`, `EvalCampaign.construct/search`, `CampaignRun.map_worlds`,
narration, reader checks and calibrated-noise admission, then return its
finalized `EnterpriseEvalHarness` and metadata. The dataset compiler still owns
the declared scenario, selectors, budgets, qualification and dataset acceptance.
An SDK/ACP adapter belongs behind this builder boundary; it cannot self-approve
rows or change the plan during a run.

The built-in builder resolves the company, builds the SDK blueprint, optionally
runs domain episodes, and installs the declared operational simulation. It does
not call an LLM or infer new business mechanisms from the industry's name.
Native formats requiring authored evidence must be supplied through a custom
builder using the existing narration/rendering path; qualification refuses
missing source bytes. Reference proofs establish the supported connector
assertions, not prose entailment, complete business analysis or agent difficulty.

## Durable operation

```bash
worldloom evals dataset compile examples/datasets/retail-banking.json --out ./dataset --batch-limit 4
worldloom evals dataset compile examples/datasets/retail-banking.json --out ./dataset
```

`--batch-limit` pauses after that total number of batches. It does not alter the
sealed plan. Incomplete runs exit 3 and retain `candidates.jsonl`, `report.json`
and checkpoints. They do not emit `queryset.jsonl` or `agent-requests.jsonl`.
The first complete run emits both. The agent file contains only ID, request and
split; fixtures, expected DAGs and grading evidence remain in referenced batch
directories outside the evaluated agent's prompt.

Committed batch receipts bind all file bytes and their generation request.
Resume recomputes deterministic admissions from those receipts and generates
only missing batches. Completed replay invokes neither builder nor executor.
Editing a committed source, response, fixture, proof or request refuses replay.
An interrupted uncommitted batch is regenerated after its request identity is
checked. External callbacks therefore have at-least-once delivery until batch
commit; callers must use the request digest for idempotency. Use one writer per
run directory. Changing quotas, sources, builder ID or policies needs a new run.

`verify` checks the content inventory of the exported run. These are integrity
receipts, not signatures authenticating an adversarial file author. Existing
qualification remains the execution authority.

## Measure before enlarging the population

`tools/measure_dataset_compiler.py` runs generation, verifies the run and replays
it offline with identical manifest bytes. `--count 1000` exercises real rows;
`--index-probe` separately measures connected-component splitting on 100,000
metadata entries. The latter is explicitly not 100,000 generated or qualified
queries. Reports retain source hashes and the scope of each measurement.

To increase business breadth, author additional source cells. To measure language
quality or difficulty, use the [reader and calibration gates](quality-calibration.md)
inside the source builder. Dataset admission cannot infer those properties from
row count, graph variety or successful reference execution.

## Recorded run

The [measurement report](measurements/dataset-compiler.json) records these
results for the checked-in plan. The generated checkpoints were verified and
replayed in an isolated directory; timing fields explicitly identify resumed
compilation, not cold generation throughput.

| Check | Observed result |
| --- | --- |
| Quotas | 1,000 admitted rows; all four cells filled |
| Executable variety | 50 task fingerprints across seven admitted DAG shapes |
| Grounding | 998 evidence cohorts across 36 generated companies |
| Language | 126 normalized request forms; two authored business workflows |
| Company-disjoint split | 798 train, 96 validation, 106 test; largest group 32 |
| Replay | Identical manifest, zero generation/execution calls |
| Original inventory space | 448 configurations; 392 equivalents removed before qualification |
| Separate metadata index | 100,000 entries, 10,000 groups; approximately one second |

The pilot's destination operation remains email draft. Its task fingerprints
measure executable variety within the declared inventory/arrears population;
they do not turn two business workflows into fifty business objectives. The
index probe is separate from generated-row qualification.
