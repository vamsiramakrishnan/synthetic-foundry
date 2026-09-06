# Extension seams: proposal engines behind the compiler boundary

Worldloom is the final authority on identity, arithmetic, chronology, causality,
provenance and replay. Everything outside that boundary (a distribution learned
from real data, a locale's postcode grammar, rows a statistical model proposes,
events a domain simulator exports) is welcome *as a proposal*. This page is the
contract under which proposals get in, and the four things that were built on
it first.

The pattern is the one the project already had. `narrative.providers.Provider`
and `actors.providers.ActorProvider` are small `Protocol`s whose `id` enters a
content-addressed ledger key, each ships with a deterministic fake so the whole
pipeline is testable with no backend, and each is **asked once and replayed
forever**: the accepted output is what the corpus carries. `worldloom/providers.py`
names four more seams on exactly that pattern.

| Seam | What it may decide | What it may never decide | Shipped default |
| --- | --- | --- | --- |
| `PriorEstimator` | Physics *ranges* (`parameters.Span`) from data it may not copy | Any row, any entity, any fact | `calibrate.LaplaceHistogramEstimator` |
| `SurfaceValueProvider` | Leaf values on an entity the world minted: postcode, phone, registration number, bank account | Identity, relationships, outcomes | `surface.Vendored` |
| `DetailSynthesizer` | Candidate transaction rows | Any total the ledger states, `accept` reconciles them | `providers.EvenSynthesizer` (a contract fixture) |
| `DomainImporter` | Neutral `ImportedEvent`s from an external export | What the world does with them (a vertical's business) | none yet, the seam is declared |

## The receipt

Every external execution leaves a `Receipt`: backend and version, the operation,
digests of configuration, source, candidate and accepted output, the seed if any,
and a `PrivacyReceipt` when a privacy budget was spent. Its `key` is a content
address over all of it, the same discipline as `GenerationLedgerEntry.key`, for
the same reason. **Digests, never data**: no receipt field carries a value from
the source, so a receipt is safe to ship in a corpus precisely because it proves
what happened without repeating any of it.

```json
{
  "backend": "worldloom-dp",
  "backend_version": "1",
  "operation": "estimate_priors",
  "configuration_digest": "9ffca478e31bba6d72ced8f5…",
  "source_digest": "6ba948e27e2cd78d0542d1b2…",
  "privacy": {"mechanism": "laplace-histogram", "epsilon": 2.0, "delta": 0.0,
              "sensitivity": 12.0, "contribution_bound": 12, "queries": 2,
              "noise_source": "system-entropy"},
  "accepted_digest": "…"
}
```

## Calibration: `worldloom calibrate` and `build --priors`

`parameters.py` says its defaults were "chosen to make one plausible episode
work, not calibrated against anything". Calibration is how a user with their
own sensitive table gets physics that resemble it, without a row of it entering
the corpus.

```bash
worldloom calibrate --template > schema.json      # which columns inform which spans
worldloom calibrate --from actuals.csv --schema schema.json --epsilon 1.0 --out priors.json
worldloom build --seed 8128 --priors priors.json --out ./corpus
```

The built-in estimator clips each column to its declared domain, bounds one
individual's contribution by truncation, releases a Laplace-noised histogram
under sequential composition, and reads the span's low and high off the noised
distribution at the declared quantiles. The snapshot is exactly the `overrides`
document `--physics` reads, plus the receipt, plus a per-column **quality**
reading, how many values were read and what share of the released histogram is
expected to be noise. When that share is high, the CLI says so: the release is
still valid, it is just not informative, and the fix is more rows, more ε, or
wider bins.

Two things are deliberate and worth knowing:

- **Noise comes from system entropy by default**, so a calibration is not
  reproducible. That is correct: the thing that must replay is the corpus, and
  the corpus replays from the snapshot. `--noise-seed` exists for tests; a
  seeded snapshot says `noise_source: "seeded"`, reports `private == False`, and
  every span's `source` says it is a summary rather than a private release.
- **SmartNoise, Tumult and OpenDP are not dependencies.** They would do this
  with better mechanisms, and `PriorEstimator` is where such an adapter plugs
  in, producing the same snapshot with a different `mechanism` in its receipt.

## Surface values: `master_data` with `identifiers`

Four locales ship with regions, cities, names and number punctuation, and none
could put a postcode on an address or an ABN on a vendor. `surface.py` fills
those from rules vendored in `data/surface/rules.json`, versioned, and every
value a pure function of a `StableKey`: `seed / rules version / entity type /
entity id / field`. The version is *in the path*, so bumping the rules moves
values only for keys built under the new version; no two fields share a stream,
so adding a field never moves a neighbour.

Checksums are the issuing bodies' own: ABN (mod-89), German USt-IdNr (11-10),
Austrian UID, UK VAT (mod-97), NZBN (GS1), and every IBAN (ISO 7064). A number
the downstream ERP would reject is a tell; one it accepts is data.

```bash
# The value names the rules version, and rides the master_data request so the
# recipe records it: a corpus built under version 1 replays under version 1's
# rules however many versions the package gains, because every version is kept.
worldloom build --seed 8128 --spec company.json --out ./corpus   # spec: "master_data": {"vendors": 2000, "identifiers": 1}
```

```python
sdk.company("procurement").master_data(vendors=2000, customers=400, identifiers=1).build()
```

Faker was refused, again, for the reason `detail.py` and `generators/masterdata.py`
give: a value from a pip-installed dataset is a value a seed cannot mean across
versions. Recording the package version would detect the drift, not prevent it.

## Causal models: `build --causal`

`messiness.py` made *how much* imperfection a corpus carries a named dimension.
A causal model says *why*. It is a DAG of named quantities (exogenous nodes
drawn from physics spans or held constant, derived nodes a **linear** function
of their parents, clamped and rounded) with dated **interventions** (`do()`:
"the ERP migration happened in April") and **drives** that make a node's value,
scaled, an imperfection kind's budget. The stale pages in the archive are then a
consequence the model computed, not a number an author typed.

```bash
worldloom causal check --template > model.json
worldloom causal check model.json
worldloom causal trace model.json --periods 6 --period 2026-01   # the authoring loop
worldloom build --seed 8128 --periods 6 --incident --causal model.json --out ./corpus
```

Linear only, on purpose: it is `FactKindSpec.derive`'s closed-vocabulary
argument, a derivation the validator cannot recompute is a figure nothing
checks. The whole trace lands on the corpus as `causal.jsonl`; each intervention
mints a `causal.intervention` event on the timeline; the `Causal` recipe verb
replays the model under the recorded physics; and the `causal` validator group
recomputes every derived value from its recorded parents, refuses a trace that
drifted, holds delivery to the budget, and requires each intervention's event.
The imperfections themselves ride `apply_messiness`, so each one is still
establishable from the corpus by the audit trail `messiness.py` promises, and
now traceable to the node that sized its budget. `--causal` and `--messiness`
cannot be combined when the model drives imperfections: two passes would spend
the same corrections twice.

## Fidelity: `worldloom fidelity`

`stats.py` reports and refuses to grade, because there is no auditable reference
for "a real enterprise corpus". When the user has a real table of their own, the
comparison has a subject, and `fidelity` makes it, as a vector, never a score.

```bash
worldloom fidelity actuals.csv ./corpus --table order_lines --slices region --json
```

Per column: KS and Wasserstein for numbers; Jensen–Shannon, total variation,
cardinality and unseen-category share for categories; missingness always. Per
pair: correlation error across numeric pairs, contingency distance across
categorical pairs. Multivariate: Schilling's nearest-neighbour two-sample
statistic beside its same-distribution baseline (a copy sits near zero; a
different region sits well above). Privacy: exact-match rate, and distance to
the closest real record against the real set's own leave-one-out baseline. Per
slice: the univariate block again. A single number would reward whichever
dimension is cheapest to move.

## What is deliberately not here

- **A live Faker dependency**, for the replay reason above.
- **SDV, CTGAN, Copulas in core.** Business Source License, and a `DetailSynthesizer`
  adapter can be installed separately and *propose*; `providers.accept` is what
  makes a proposal into data by reconciling every declared total.
- **A free-form expression language** in causal models or episode specs.
  Weights buy the same function as `"0.18 - 0.12 * q"` without the parser or
  the hole in the validator.
- **A healthcare engine.** `DomainImporter` is the seam a Synthea/FHIR importer
  would fill; the vertical that consumes imported events is authored through
  `worldloom-vertical`, not through this page.
