# Enterprise corpus minimum

Use the enterprise admission audit to check whether a corpus covers the
required business functions and exposes their records. Coherence checks test
consistency against canonical state; they do not establish sufficient breadth,
realism, or downstream task performance.

A single coherent month-end-close episode is a pilot. Increasing its file
count does not add workforce, customer, procurement, or security coverage.

```bash
python -m evals.enterprise_minimum ./corpus-fleet \
  --out ./corpus-fleet/enterprise-minimum.json \
  --require enterprise-minimum
```

The audit has two profiles:

- `finance-operations-pilot` is a bounded retrieval and ingestion corpus. It
  requires identity/organisation, executive reporting, finance, operations,
  technology, collaboration artifacts, ACLs, time depth, lifecycle,
  provenance/evals, mixed office formats, and system projections.
- `enterprise-minimum` adds workforce, policies/legal/risk, procurement,
  customer/commercial, security, modeled knowledge flow, and entity reach.

A dimension is `covered`, `partial`, or `missing`. Only `covered` satisfies an
admission. For example, a roster without employment records is partial
workforce coverage; revenue figures without customers or commercial activity
are not customer coverage; document ACLs without access reviews or security
records are partial security coverage.

## Current rich pilot

`dist/enterprise-pilot-rich-reader` passes the finance/operations profile and
fails enterprise-minimum on seven dimensions:

1. Workforce records
2. Policies, legal, risk, and compliance
3. Procurement and third parties
4. Customer and commercial records
5. Security governance and operations
6. Modeled information flow
7. Entity-to-record reach

That verdict is intentional. Do not weaken the thresholds or relabel the pilot
as enterprise-complete.

## Enterprise-depth exemplar v1

`dist/enterprise-depth-v1-reader` exercises the existing cross-functional
surfaces before adding new generators: full policies, twelve turbulent periods,
hiring and review rounds, a large estate, master data, modeled conversations,
high evaluation density, document variation, and accountable archive noise.

It passes the finance/operations admission and closes three of the earlier
enterprise blockers: workforce, policies/risk, and modeled knowledge flow. The
enterprise minimum remains red on four partial dimensions:

1. Procurement transactions and third-party lifecycles
2. Customer/commercial activity and service history
3. Operational security records
4. Entity-to-record reach (66.87% against a 75% threshold)

The vendor, customer, and SKU masters count as partial evidence only. A master
row is not a contract, order, invoice, CRM interaction, service case, consent
record, or complaint. The checked-in company specification is
`evals/enterprise-depth-company.json`; the rendered corpus carries its own
machine-readable `enterprise-minimum.json` and corpus card.

## What the next evolution should optimize

The enterprise-depth exemplar now exercises the capabilities the harness already has:

- `--policies full`
- hiring and performance-review rounds
- `--conversations`
- a non-quiet timeline
- content messiness plus accountable workspace noise
- locales and broader configuration coverage
- denser record reach for people, systems, and services

The remaining gaps need generator work, not a larger seed count:

- compose procurement records into the same company rather than offering only
  a separate procurement vertical;
- introduce customer/CRM, sales, service, consent, and complaint lifecycles;
- introduce security policy, identity/access review, vulnerability, and
  security-incident records;
- add legal, compliance, contract, and enterprise-risk lifecycles;
- add task/workflow projections where the source system supports them.

AlphaEvolve selection should treat the machine-readable blocker count and
per-dimension evidence as objectives alongside coherence, replay, retrieval
hardness, configuration coverage, question diversity, and storage cost. A
candidate that produces more files without closing a dimension has not
improved enterprise breadth.

## Delivery quality is separate

The executive-prose gate in `evals/executive_narration.py` requires developed
sections, synthesis, explicit watchpoints where appropriate, required facts in
visible prose, and bounded specificity. The enterprise-minimum gate checks
breadth. Both must pass: rich prose cannot compensate for missing functions,
and broad functions cannot compensate for fixture-like documents.
