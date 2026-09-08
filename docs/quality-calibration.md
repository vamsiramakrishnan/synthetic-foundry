# Evidence quality and empirical noise calibration

This layer composes existing Worldloom contracts. Company interviews resolve a
`CompanySpec`; episodes generate business state; `EvalCampaign` constructs the
eval's evidence. Narration and rendering precede quality admission. The calling
harness supplies readers and observed agent outcomes through SDK callbacks or
JSON handoffs. Model SDKs and ACP transports remain outside the generation core.

| Responsibility | Reused owner | Added contract |
| --- | --- | --- |
| Blind evidence recovery | Narration references, requests, generation ledger and recipe replay | One reader plan/review/accept boundary for ordinary prose and program expansions |
| Distribution support | `fidelity.compute` and its existing distance vector | Full union population census, missing groups and capped metrics |
| Cohort difficulty | `eval_metrics.DifficultyCalibrator` | Versioned features, observed trial ledger, Wilson uncertainty and held-out scoring |
| Noise interventions | `Messiness`, `Imperfections`, `CampaignRun.map_worlds` | Independently transform each baseline, then revalidate and rebind |
| Feedback and selection | Existing `Archive` | Bounded scheduling over declared variants, uncertainty admission and explicit niche holes |

## Read evidence without giving away the answer

```python
from worldloom.narrative import reader_checks

planned = reader_checks.plan(
    narrated_world,
    reader_id="reader-model/prompt-v1",
    reader_config={"prompt_version": "evidence-v1", "temperature": 0},
    instances=(instance,),
    share=0.05,
)
public_document = planned.requests_document()
# Send only public_document to the independent reader.
# Keep planned, the World, and instance.oracle inside the checker.
accepted = reader_checks.accept(narrated_world, planned, responses)
accepted.world.export("reviewed-corpus")
accepted.raise_if_failed()
```

The full `ReaderPlan` is private: it contains expected fact records and eval
oracles. Its public document contains rendered prose, requested aspects, opaque
correlation fields and the response schema. A reader returns `ReaderResponse`
objects with copied subject, displayed value and verbatim evidence quotation.
The request identity, text digest, reader identity and contract version must be
returned unchanged. A quotation must locate subject and value together; this is
a lexical evidence check, not a semantic entailment model.

Every `EvalInstance.oracle.fact_ids` target is mandatory, including targets
beyond the writer's three-fact brief. Artifact witnesses constrain where a
target may be recovered. Unknown, invisible or uncited evidence is a finding;
an empty sample cannot pass. Background sampling adds obligations and never
replaces the mandatory set. Explicit `critical_fact_ids` are also supported.

Accepted and rejected reviews retain replies, findings and content bindings in
the existing generation ledger. Persist `accepted.world` before raising on a
rejected review. `reader_checks.run(world, planned, reader_callback)` invokes
the callback only for a new review; unchanged accepted receipts replay with
zero reader calls. Text, target records, cutoff, locale, observer or reader
configuration changes invalidate acceptance. A copied `review.passed=True`
is insufficient: consumers call `verified_review` against the current ledger.

For program expansions, supply `expansion=expanded` to the same plan and accept
functions, then pass the plan and responses to `programs.commit`. Existing
`requests/check` and `Budget.reader_check_share` remain legacy compatibility
interfaces; use the shared plan for evaluation-critical coverage.

The CLI provides the same public handoff:

```bash
worldloom narrate readers requests ./corpus --reader-id reader-v1 --eval-instance instance.json --out reader-requests.json
worldloom narrate readers accept ./corpus --reader-id reader-v1 --eval-instance instance.json --from reader-responses.json
```

Use identical reader configuration and sampling arguments for both commands.
The request file is the only reader input. Failed acceptance remains a failed
review even though its audit receipt is persisted. Repair prose through the
existing narration path, then request a fresh review.

## Preserve every fidelity denominator

```bash
worldloom fidelity reference.jsonl synthetic.jsonl --slices geo --slices company_size --require-slice-support --max-slices 32 --json
```

Slice columns retain their ordinary global marginals. `slice_support` accounts
for every population on either side, including absent keys, nulls and empty
strings. Typed identities prevent values such as integer `1` and string `"1"`
from collapsing. `max_slices` caps metric computation, not the population
census. Omitted groups and one-sided groups prevent complete support.

The strict flag requires at least one slice and exits with a named refusal when
support is incomplete. Without the flag, the report remains diagnostic. A
complete support census does not establish small distribution distances. Set
metric-specific thresholds: total variation and KS are normalized, while
Wasserstein distance uses the original column units. Missing or nonfinite
metrics cannot satisfy a threshold.

## Record observed cohorts, never infer them from difficulty labels

```python
from worldloom.eval_metrics import (
    CalibrationObservation, DifficultyCalibrator, feature_slice,
)
from worldloom.providers import digest

calibrator = DifficultyCalibrator()
observed = CalibrationObservation(
    cohort="retrieval-agent/model-and-prompt-v1",
    trial_id=trial_id,
    eval_id=instance.id,
    corpus_digest=exact_export_digest,
    evaluator_config_digest=digest(evaluator_config),
    evaluator_kind="agent",
    features=feature_slice(spec, conditions={"noise_variant": variant_digest}),
    passed=graded_outcome,
    split="train",
)
calibrator.ingest(observed)
estimate = calibrator.estimate(observed.cohort, observed.features, min_trials=20)
calibrator.export("cohort.json")
```

`passed` must be a real boolean from a caller-owned grading adapter. Bind the
exact corpus and model, prompt, tools and grading configuration. Distinct
interventions belong in `conditions`; otherwise different noise policies would
be pooled into one slice. Request features and eval-design features have
separate schemas. Neither feature bucket alone is fitted difficulty.

Exact trial replay is a no-op; conflicting replay refuses. A cohort cannot
silently mix evaluator kinds or configurations. The same eval/corpus group
cannot enter both training and validation/holdout, even with a new trial ID.
Splits are caller-declared: keep related companies, templates or source
documents in one split when they would otherwise leak information.

Estimates retain the Laplace point estimate and add a 95% Wilson interval,
support threshold, estimator version and provenance status. Unsupported slices
remain unfitted. Legacy count-only observations remain unverified, and reference
executor successes cannot establish agent calibration.

Wilson intervals are nominal per-slice binomial intervals. They are not
simultaneous guarantees over all searched variants or confidence sequences
valid under arbitrary stopping. Keep frozen held-out confirmation separate from
adaptive training selection and report its own support and interval.

```bash
worldloom evals calibration ingest --from observations.jsonl --out cohort.json
worldloom evals calibration report cohort.json --cohort retrieval-agent/model-and-prompt-v1 --split holdout --min-trials 20
```

Held-out reports score against training-only predictions and retain scored and
unsupported denominators, Brier score and expected calibration error. A
descriptive held-out pass interval never updates the training estimate.

## Run a finite feedback loop over actual worlds

```python
from worldloom.evals.calibration import (
    MetricThreshold, NoiseCalibrationPlan, NoiseVariant, calibrate_noise,
)

policy = NoiseCalibrationPlan(
    variants=(
        NoiseVariant(name="clean", budget={}, niche="current"),
        NoiseVariant(name="stale", budget={"staleness": 1}, niche="decayed"),
    ),
    niches=("current", "decayed", "still_uncovered"),
    cohort="retrieval-agent/model-and-prompt-v1",
    evaluator_config=evaluator_config,
    reader_id="reader-model/prompt-v1",
    reader_config={"prompt_version": "evidence-v1", "share": 0.05},
    fidelity_config={"reference_digest": reference_digest, "projection": "facts-v1"},
    fidelity_slices=("geo",),
    fidelity_thresholds=(MetricThreshold(
        path=("univariate", "amount", "ks"), maximum=0.15,
    ),),
    target_low=0.3, target_high=0.7, min_support=20,
    formats=("markdown",),
    max_training_attempts=128, max_holdout_attempts=64,
    holdout_ordinals=held_out_candidate_ordinals,
)
result = calibrate_noise(
    finalized_campaign, policy, evaluate,
    read=read, fidelity=measure_fidelity,
    checkpoint=lambda record: record.export("calibration-checkpoint.json"),
)
result.export("calibrated-campaign")
```

The campaign needs distinct candidate seeds and a nonempty, disjoint holdout
subset. `evaluate(TrialRequest)` is a trusted grading adapter: it receives the
world and oracle-bearing instance, but must send only permitted task and tool
inputs to the agent under evaluation. It returns `TrialOutcome`. A reader
callback returns an actual `ReaderAcceptance`, and a fidelity callback returns
an actual `FidelityReport`. Seal their configurations in the policy. The reader
must use that policy's reader ID, configuration and sampling share.

Each intervention starts from its original baseline. Mutable generator state
is isolated; another variant cannot consume its IDs. Existing campaign
validation and oracle rebinding run after every transform. The reader may add
review receipts; prose authoring must already be complete. Missing quality
inputs, failed reviews and fidelity failures become recorded refusals and never
train the cohort.

`formats` materializes native output before measurement. Added noise intents
receive deterministic structure and template prose through the existing
narration provider, with explicit template authorship and ledger receipts.
Existing authored IR retains its original authorship. Template output is not
reported as model-authored prose or an improvement in writing quality. Reader admission
covers the declared critical set and sampled visible cited sections; it is not
a blanket review of every added document. Supply an appropriately authored
baseline and define evidence/shape requirements for the task being calibrated.
Ordinary offline replay uses an explicit set of recorded model identities;
ambiguous current receipts refuse instead of selecting an arbitrary author.
When `formats` is empty, an in-memory baseline's existing uniform render policy
is verified and reused. Persisted native files or heterogeneous rendering need
an explicit format policy. Finish baseline narration before starting the loop.

The scheduler explores declared variants, then prioritizes support and
uncertainty around the requested pass-rate band. It assumes no monotonic
relationship between noise and difficulty. This is bounded empirical selection
over an explicit candidate menu; it does not synthesize arbitrary new mutation
programs. A variant enters the existing archive only when its entire Wilson
interval is inside the target band. Unsupported niches remain holes.

Selection freezes before held-out evaluation. Held-out failure is reported
without retraining or selecting a replacement. Inspect each selected variant's
`holdout_status`; selection alone is not held-out confirmation. Exports retain
the exact trial worlds and split-labeled attempt record. Keep training worlds
out of a final held-out benchmark using those recorded split assignments.

Resume with `recorded=NoiseCalibrationRecord.load(path)`. A complete record
replays without reader, fidelity or evaluator callbacks; a prefix invokes only
remaining work. Changed policy, world, schedule or conflicting receipts refuse.
Content hashes detect drift, not a malicious caller rewriting all evidence.
Provider transport, authentication, retries and durable checkpoint delivery
remain the calling harness's responsibility.

## Limits to preserve in enterprise claims

The independent [reader probe](measurements/blind-reader.json) used an isolated
agent given only four public request passages from the existing grocery
narration. It recovered 2 of 10 target occurrences; no sampled section passed.
All nine returned claims had valid local quotations. The refusals came from
missing evidence and mismatched canonical subject/value recovery, including a
business name in the preceding sentence and generic incident subjects. This
shows a concrete gap between authoring acceptance and this stricter reader
contract. It is not a finding that the reader understood only 20% of the prose.

The source narration remains unchanged. Recorded responses and rejected review
are retained; identical response resubmission preserves exported bytes. Recheck
the recorded experiment without calling a reader:

```bash
python tools/measure_blind_reader.py --out blind-reader-report.json
```

The [protocol integration report](measurements/quality-calibration.json) is a
separate scripted experiment. It exercises critical evidence, fidelity support,
cohort observation, finite selection and replay; its deliberately small
support threshold and broad target band do not validate production difficulty.
It recovers all five critical facts through ordinary and program narration,
records 12 protocol trials over six baseline Worlds, and introduces six workbook
errors plus one stale artifact. All 264 exported files match during record
replay. Every selected World also independently rebuilds from its recipe and
ledger with zero provider calls and identical rendered bytes. The full report
matches in a separate process with `PYTHONHASHSEED=73`.

```bash
python tools/measure_quality_calibration.py --out quality-calibration-report.json
```

These contracts add evidence and measured-cohort admission; they do not prove
native layout quality, semantic entailment, multi-document synthesis or
macro/micro reconciliation. SDK tests using scripted outcomes establish
protocol correctness, not deployed agent performance. Measure the intended
company/geo/connector population and a real independent cohort before making
enterprise-wide calibration or performance claims.
