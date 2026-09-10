# Reusing Worldloom for enterprise outcomes

The baseline was measured against the implementation published as `00a1724`.
The examples describe those inputs, not every company, geography, episode or
agent cohort. The implementation now adds
[executable qualification and case-bound coverage](enterprise-qualification.md).
The source generators, query planner, connector executor and covering algorithm
remain the existing owners of their contracts.

## What is reused and where it belongs

| Existing module or algorithm | Integration and outcome | Remaining boundary |
| --- | --- | --- |
| `company`, SDK blueprints, `pipeline` | Resolve one company, preserve unmet claims, build each planned seed through typed stages | Interview authoring remains an agent/skill responsibility; no automatic ACP interview service |
| `episodes`, domain generators, operational `Simulator` | Own business events, canonical facts and causal case lifecycles | Operational microdata is not automatically reconciled to aggregate company facts |
| `evals.EvalCampaign`, candidate tactics, `map_worlds` | Eval-first construction; transform, revalidate, rebind, prove and export the same worlds | Demands without constructive tactics remain refusals |
| Shared `Predicate`, operational projections and `SYNOBS` | Bind real cross-connector case cohorts and independently check evidence membership | Context-dependent source joins and relative time are explicitly unsupported |
| `enterprise_queries.constrained_cover` | Select semantic interactions and actual cases after qualification; recompute holes after caps | Streaming selection is deterministic, not globally optimal |
| `validate_corpus`, `compile_rows`, `run_eval_row` | Establish connector evidence and executable assertion outcomes before admitting coverage | Legacy model transforms and semantic answer quality remain outside the proof |
| Artifact byte inventory and native renderers | Require actual source-file witnesses, retain byte receipts and reject metadata-only claims | Existence is not native layout compliance or correct analysis |
| Narration contracts, generation ledger, programs, reader checks | Shared critical-evidence admission for ordinary prose and expansions, with offline review replay | Lexical recovery does not establish semantic entailment or synthesis |
| `Archive`, diversity, dispersion, evolution | Bounded observed-noise selection after revalidation and quality admission | Variant menus are declared; arbitrary mutation-program synthesis is not implemented |
| `fidelity`, difficulty features and calibrator | Complete population accounting and versioned, provenance-bound cohort estimates | Actual intended cohorts and reference populations must be measured |

The new code is an admission/composition adapter and a source-binding adapter.
Another episode grammar, narrator, campaign engine or covering library would
duplicate working ownership. Reuse is assessed by preserved contracts and
measured outputs, not an invented percentage of lines.

## What the examples actually exercise

| Probe | Available material | Exercised material or measured result |
| --- | --- | --- |
| Retail operational example | 17 exception cases; 68 connector records | 24 queries select evidence from just 1 distinct case |
| Banking operational example | 9 exception cases; 27 connector records | 24 queries select evidence from just 1 distinct case |
| One retail close, March, with incident | 16 artifacts; 35 pending narration sections | 35 program families; no family reuse within this example |
| Six retail closes, March–August, with incidents | 91 artifacts; 203 sections | 62 program families; default three variants request 186 author responses |
| One-close fallback program expansion | Zero requested author responses | 35 expanded sections; 1 exact redundant section; 2 near-duplicate redundant sections |
| One-close reader sampling | Sampling share 0.1 | 4 reader requests; generating requests does not demonstrate recovery |
| One-close mechanical realism | Compiled world and deterministic scripted narration | Both score 0.9498, with no findings |

Operational counts use `case_id` on fixture-selected source records. Query
count therefore overstates exercised business-case diversity in these examples.
The source lifecycles and cross-connector joins already exist; selection is the
missing integration. Keeping all roles on the same case must accompany broader
selection, or apparent diversity could join unrelated evidence.

Program expansion has dependency digests, targeted invalidation and offline
ledger replay. Its `model_calls` budget counts requested author variants, not
measured provider executions, retries or reader calls. These measurements support
reuse across repeated periods; they establish no speedup or semantic quality gain.
The fallback probe explicitly permits a near-duplicate rate of 1 for inspection;
its measured rate, 2/35, exceeds the normal 0.02 limit.

## Measured integration results

Run `python tools/measure_enterprise_qualification.py --out report.json` with
the project's render extras installed. The checked
[measurement report](measurements/enterprise-qualification.json) records inputs,
source hashes, dependency versions, refusal examples, coverage denominators and
export file digests. It is a bounded integration benchmark, not a measured
autonomous-agent success rate.

Eight company probes cover retail, banking, insurance and procurement in Germany
and the United Kingdom. Each uses seed 8128, one March episode, actual rendered
source artifacts, the existing enterprise query catalogue, a pool of 128,
strength 2 and an output cap of 64. Both geographies produce the counts below;
unmet company-resolution claims remain in the report.

| Engine | Eligible and selected per geography | Requested interactions | Witnessed and selected interactions |
| --- | ---: | ---: | ---: |
| Retail | 56 / 128 | 2,570 | 1,721 |
| Banking | 47 / 128 | 2,570 | 1,543 |
| Insurance | 35 / 128 | 2,570 | 1,367 |
| Procurement | 40 / 128 | 2,570 | 1,502 |

Only 356 of the 1,024 company candidates qualify. The other 668 have recorded
refusals: 332 at strict source preflight, 40 at independent corpus validation,
192 for selected source-format mismatch, and 104 without a supported source-file
byte witness. A refused selection does not prove suitable evidence is absent
everywhere: source binding may itself need improvement. None of these gaps is
erased from requested coverage.

Operational comparisons use identical simulations, pools of 24 and output caps
of 24, with designed failures disabled. All 24 candidates in each arm qualify.
The covering algorithm selects 21 retail queries and 16 banking queries in both
the default and case-bound arms.

| Vertical and execution shape | Cases available | Default selected cases | Case-bound selected cases |
| --- | ---: | ---: | ---: |
| Retail, legacy | 17 | 1 | 17 |
| Retail, mapped reads | 17 | 2 | 17 |
| Banking, legacy | 9 | 1 | 9 |
| Banking, mapped reads | 9 | 2 | 9 |

Across all 16 qualification arms, 504 selected rows pass after export, reload,
recompilation and re-execution. Replayed traces, grades and post-state match the
deserialized proofs; repeated qualifications produce identical export bytes.
An independent process with `PYTHONHASHSEED=73` reproduces all 16 arms and their
export digests exactly. The checked report's source hashes match the integrated
implementation.
These are fixture-based reference assertions. Native receipts do not establish
semantic document quality or fully parsed container validity. The results show
broader exercised case evidence and honest admission accounting; they do not
establish a 100× speedup or enterprise-wide representativeness.

## Compose the existing gates in the right order

1. Bind the company, geography, connectors, evidence and requested outcome.
   Qualify each candidate through executable evidence, permissions, temporal
   constraints and actual artifact requirements. Keep failures and their reasons.
2. Measure interactions over qualified candidates. `covering.covering_array`
   constructs declared combinations; `covering.coverage` and `covering.holes`
   measure them. These pure algorithms do not establish executable feasibility.
3. Report both denominators: all requested interactions, and interactions
   witnessed by qualified candidates in the evaluated pool. Call the latter
   *observed achievable coverage*, since an unsampled combination is not proven
   impossible. Report uncovered and unsupported combinations separately.
4. Use `archive.Archive` to retain qualified champions in declared niches;
   use diversity, dispersion and evolution to improve or fill remaining gaps.
   Neither archive occupancy, proposal count nor vocabulary size proves coverage.
5. Revalidate changed worlds and their evidence bindings before admission.
   `CampaignRun.map_worlds` already revalidates candidates and rebinds oracles;
   reuse that seam for authoring and repair.

Qualification must precede archive admission and evolutionary selection, and
run again after mutations. A high spread or difficulty score cannot compensate
for an unexecutable task. Qualification and case-binding regressions exercise
these boundaries, including repinned wrong-case evidence, output caps, designed
errors and export replay.

## Reuse one authoring and evidence boundary

The existing path is `ArtifactIntent` → `ArtifactIR` → bounded narration request
→ `GeneratedNarrative` and claims validation → `World.narrate` → native render.
`narrative.handshake` and `compiler.handshake` provide authoring/planning contracts;
`ResponseProvider`, the generation ledger and receipts provide acceptance/replay.
Use these for direct prose and `narrative.programs` alike.

Programs bind safe clauses to facts and expand without model calls. Their current
clause grammar binds one fact at a time; it does not itself deliver multi-fact
business synthesis. Claim validation checks allowed support, required references
and contract rules; it does not prove semantic entailment or readable conclusions.

The shared `reader_checks.plan/check_plan/accept` boundary now covers ordinary
narrated Worlds and expansions. It joins every `EvalInstance.oracle.fact_ids`
target to visible cited prose and required artifact witnesses, adds a budgeted
background sample, and sends only rendered text/aspects to the reader. Missing,
ambiguous and stale targets refuse. Text/target/context and reader configuration
bind receipts; accepted and rejected responses persist in the existing ledger.
Unchanged accepted reviews replay without callbacks. The older `requests/check`
interface remains compatible but retains its sampled writer-required scope.
See [quality and calibration](quality-calibration.md) for the shared workflow.

Keep quality measures separate:

- `realism.evaluate` measures ecology, lifecycle, links and fact presence. Its
  grounding score counts artifacts containing fact IDs, not supported prose.
  Assigned family labels do not by themselves prove distinct rendered structures.
- `programs.measure` and `stats.measure` expose actual prose repetition;
  compiler census/diversity expose composition and unsupported shapes. Inspect
  native artifacts as well as IR declarations when the requirement is visual.
- Blind reader recovery measures whether target evidence can be recovered from
  text. It still needs separate evaluation of reasoning, contradictions and tone.
- `enterprise_artifacts` currently renders source inventories and query text
  directly, without the ordinary `ArtifactIR` authoring path. Valid DOCX/XLSX/PPTX
  bytes are not proof of completed enterprise analysis. Adapt bounded sources
  into the existing IR pipeline before claiming authored deliverable quality.

## Calibration gaps addressed and limits retained

The baseline fidelity audit lost the reference-only `south` geography and
ignored geography's global marginal. The implementation now retains that
marginal, reports the full typed population union and exposes omitted metrics.
Strict support admission rejects missing populations; distance thresholds remain
separate because equal support is not equal frequency.

`DifficultyCalibrator` now accepts versioned eval/request feature contracts,
intervention conditions and provenance-bearing observations. Trials replay
idempotently; configuration changes and eval/corpus split leakage refuse.
Wilson intervals, support status and held-out scoring retain denominators.
Structural buckets, legacy unverified counts and reference-executor successes
cannot establish fitted agent difficulty.

`evals.calibration.calibrate_noise` composes these gates with existing campaign
transforms, Messiness and Archive. Variants derive independently from baseline
worlds, quality failures do not train, and selection freezes before holdout.
The finite loop preserves refused attempts, budget exhaustion and niche holes.
These mechanisms require actual cohort measurements; scripted integration
outcomes do not demonstrate production agent calibration.

## Recommended enterprise outcome scorecard

| Dimension | Report and gate on |
| --- | --- |
| Executability | Qualified / attempted candidates; named refusals; reference execution and permission/temporal witnesses |
| Business coverage | Distinct selected cases and resolved/open lifecycles; requested interactions, witnessed achievable interactions and remaining holes |
| Evidence quality | Critical targets present and independently recovered; missing targets, invalid quotes and unsupported conclusions |
| Artifact quality | Measured native shape compliance, composition failures, prose redundancy and reviewed synthesis quality |
| Realism and fidelity | Ecology components separately; distribution distances, missing slices and calibration provenance |
| Difficulty | Cohort identity, observed trials/successes, feature version, uncertainty and held-out results |
| Reuse and cost | Authored variants, actual writer/reader calls and retries, cache reuse, repair scope and offline byte replay |

The implemented priority is executable qualification plus case-bound coverage:
refused candidates contribute no witnessed coverage; same-case joins remain
valid; holes retain bounded denominators; exports preserve executed evidence.
The shared reader gate, full fidelity accounting and observed-noise controller
now extend that admission path. Run an independent reader and the intended
agent cohort before claiming quality or calibrated rates for that population.
Record these dimensions separately instead of collapsing them into an
unsupported headline.

## Reproducing the baseline

From this checkout, run Python with `PYTHONPATH=src` and the project dependencies:

```python
from worldloom import MonthEndClose, RetailWorld
from worldloom.narrative import handshake, programs, reader_checks
from worldloom.narrative.providers import DeterministicProvider
from worldloom.realism import evaluate
w = RetailWorld(seed=8128).build().run(
    MonthEndClose(period="2026-03", include_operational_incident=True)).compile()
p = programs.plan(w, budget=programs.Budget(model_calls=0, near_dup_rate=1))
e = programs.expand(w, p)
print(len(w.artifact_irs), len(handshake.pending(w)), len(p.families))
print(programs.measure(e), len(reader_checks.requests(w, e, share=.1)))
print(evaluate(w), evaluate(w.narrate(DeterministicProvider())))
```

For the six-period probe, start a fresh world, run the same close for each month
in `range(3, 9)`, then compile and call `programs.plan(w)` with the default budget.
Count `len(p.author_requests())` as requested variants, not actual model calls.

For operational counts, reuse the constructors in
`tests/test_synthesis_workflows.py`: retail `case_simulator()` and `IncidentRule`
for inventory/lost; banking `Simulator(banking(borrowers=8, ticks=8), seed=8128)`
and the loan/arrears rule. Build with `EnterpriseEvalHarness.from_world`,
`with_scenario(operational_profile(vertical))`,
`with_operational_data(sim, rule, include_world_records=False)` and `take(24)`.
Count `exception_episodes(sim, rule)`, `corpus.connector_data.records` and
`corpus.queries`; resolve every fixture's `input_record_ids` through those records
and count distinct `fields["case_id"]`. These are baseline measurements; rerun
after source-selection integration to establish its actual effect.
