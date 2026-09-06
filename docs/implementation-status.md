# Closing unfinished contracts

Use this status reference to distinguish implemented mechanisms from partial
support and planned work. A named command or generated file is not sufficient
evidence of an end-to-end capability. Follow the tests and receipts associated
with the specific path you intend to use.

Baseline: `cee774688412530593ee10653cd7b60bcdd676db` (PR #33).

A green merge gate proves the shipped tests passed. It does not prove the earlier roadmap was implemented. This ledger distinguishes working contracts from designs and disconnected helpers.

| Commitment | Finding at baseline | Closure gate |
| --- | --- | --- |
| Canonical bitemporal facts | Observer/record time live in a separate compatibility observation model; `CanonicalFact` has neither transaction interval nor observer. | New fields round-trip in `facts.jsonl`; existing fact bytes remain unchanged; named views cannot read latent truth. |
| Shared historical predicates | Field comparison exists; joins and `as_of` are absent. | Tools, construction validation and oracle queries use the same frozen-context evaluator. Missing context refuses, never falls back to current state. |
| Replayable constructive demands | `intervene()` appends diagnostic events; its recipe cannot replay them. Revision construction stores proposal IDs rather than replayable inputs. | Idempotent demand events with eval provenance, executable revision interventions, and export/rebuild equivalence. Unsupported tactics produce explicit findings. |
| Narration programs | The library still requests prose per instance. | Bounded reusable programs expand to the existing `GeneratedNarrative` contract, pass existing claims validation, record clause dependencies and replay without model calls. |
| Field manifests and evidence locators | Proposed in discussion; not established by the generic CRUD surface. | One manifest maps canonical attributes to native fields; field validation, projection and typed locators share that mapping. |
| Manifest-driven tools and trace grading | Basic forked CRUD/search exists. It has no field projection or durable operation trace. | Isolation includes returned nested payloads; projected reads have byte counts; evidence/ordering/write checks inspect an actual trace. |
| Empirical source acquisition | Authored process factors were integrated, not a complete APQC/ESCO/Jira/BPI/EDGAR harvest. | Source files, licences, hashes and measured outputs are needed before calibration can be described as applied. |
| Large document families / reader checks / calibrated search | Design, not established by existing tests. | Native artifact extraction, explicit reader results and measured agent cohorts. Do not claim these complete from primitive counts. |

Implementation updates belong beside executable regression gates. Do not erase an unfinished row merely because a new API has been added.
