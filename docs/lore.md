# Lore

Lore is what the company *is*: its industry, history, culture, politics, and the scar tissue that still shapes its decisions. It is generated before any structure exists, because no org graph, service catalogue, or financial model is decidable without it.

This document defines what lore is as a data structure, where depth comes from, and how the generators that produce it are themselves authored.

---

## Lore is a constraint graph, not a story

The failure mode is predictable. Ask a model for "company history and culture" and you get *founded in 1987 by two engineers, innovative, customer-obsessed*. That is generic, and worse, **inert**: nothing downstream can consume it.

So the test for any piece of lore is:

> **Does it constrain a later decision?**

If not, it is decoration and it should not exist. Which means lore is not prose. It is a set of typed, identified, cross-referenced commitments:

```
LORE-0042  erp_migration_failure
  when:    2019-03 .. 2019-11
  actors:  [ORG-finance, VENDOR-0003, PERSON-0117]
  constrains:
    vendor_selection    → VENDOR-0003 never proposed again
    PERSON-0117 persona → risk_averse_in_writing +0.4
    tech_posture        → build_vs_buy: bias_to_buy -0.3
    approval_chains     → finance/eng: +2 stages
    artifact_density    → finance docs +30%, quality -20%
  scars:   [LORE-0058, LORE-0061]
```

Every clause has a downstream effect. The founding story is then a *rendering* of the lore, applying the project's own philosophy one level up: generate reality first, render the narrative second, recursively.

### Required fields

| Field | Purpose |
| --- | --- |
| `id` | Stable identifier, referenced by facts, personas, and artifacts |
| `kind` | `event` · `decision` · `norm` · `tension` · `capability` · `constraint` |
| `assertion` | What is true, as structured data |
| `when` | Effective dates. Lore can expire; a norm from 2014 may no longer bind |
| `actors` | Entity references, resolved against the graph |
| `constrains` | One or more typed downstream effects (**at least one is mandatory**) |
| `scars` | Other lore this caused or deepened |
| `visibility` | Whether the organisation openly acknowledges it |

`constrains` being mandatory is the schema enforcing the test. A commitment that constrains nothing fails validation, so decorative lore cannot be committed.

### The constraint vocabulary

Lore may only constrain things the deterministic engine knows how to apply. The vocabulary is closed and versioned:

```
org_shape          unit count, depth, span, matrix intensity
vendor_selection   allow / deny / bias
tech_posture       build_vs_buy, cloud_stance, release_cadence, modernisation
persona_trait      per-person weighted trait adjustments
approval_chains    stage count, required roles, cycle time
artifact_density   volume, latency, quality per team and domain
terminology        preferred and forbidden terms, with effective dates
metric_emphasis    which measures leadership actually watches
risk_appetite      per-domain tolerance
event_likelihood   raises or lowers the odds of event families
```

Adding to this vocabulary means teaching the deterministic engine to honour it. That coupling is deliberate: it is what stops lore from drifting into free text.

---

## Where depth comes from

Four mechanisms. None of them is "a better prompt."

### Interrogate, don't describe

Never ask for "the history." Ask specific, consequential questions that force commitments:

> *What did this company try in 2019 that failed, and who is still there who remembers?*
>
> *Which two departments cooperate badly, and what happened between them?*
>
> *What does leadership say publicly that the organisation privately ignores?*

Depth is a property of the question's specificity, not of the output's length.

### Adversarial deepening

After a first pass, run a critic that asks *what must also be true, and what does this make impossible?*

A retailer that acquired a competitor in 2018 necessarily has duplicate systems, a migration programme, a redundancy round, and two incompatible loyalty schemes. None of that appears in the first pass, and all of it is where texture lives. Second-order consequences are generated, validated, and appended as new commitments linked by `scars`.

### Scarcity

Budget the generator to roughly a dozen commitments per world, not two hundred. Constraint produces distinctiveness; unlimited generation regresses to the industry average.

### Extract shape, not facts

`inspired_by("woolworths")` yields structural invariants: store-network retail, thin margins, seasonal peaks, a unionised workforce, pricing under regulatory attention. *Those* generate lore. Nothing proprietary is copied, and the resulting world is recognisably that kind of company without being that company.

---

## Lore packs

A lore generator is a **lore pack**: versioned data, packaged the way a skill is, as instructions and validators rather than code.

```
packs/retail/
├── pack.toml            identity, version, prompt versions
├── schema.toml           industry-specific lore kinds
├── interrogation.toml    the question script, ordered, with follow-ups
├── vocabulary.toml       which constraints this industry can express
├── critics.toml          the adversarial deepening passes
└── exemplars/            worked lore graphs, hand-authored
```

A pack contributes questions, a constraint vocabulary subset, critics, and exemplars. It does not contribute prose.

---

## Authoring a pack

The honest answer has an unavoidable first step.

**1. Hand-author one pack completely.** Retail first. You cannot meta-generate the first one: there is nothing to generalise from and no way to judge the output. Any project that skips this ships slop and does not find out for six months.

**2. Generalise from the exemplar.** Banking is not *"write me a banking lore pack."* It is the retail pack as a worked example, plus the differences that matter (regulatory intensity, capital constraints, a real risk function), and the model produces a candidate.

**3. Accept mechanically, not by vibes.** This is what makes meta-generation safe, and it is the precondition for letting a model write generators at all: you may only do it if you can automatically measure whether a generator produces valid output.

**4. Human reviews the diff and commits it, versioned.** Worlds then reference the pack by version like any other dependency.

### Acceptance metrics

| Metric | What it catches | Bar |
| --- | --- | --- |
| **Consequence density** | Decorative lore | 100% of commitments constrain ≥1 decision |
| **Distinctiveness** | Packs that generate industry averages | Two seeds, same industry: distinguishable from artifacts alone |
| **Reachability** | Lore that never surfaces | Every commitment appears in ≥1 artifact |
| **Scar depth** | A frozen, ahistorical world | Median hops from a historical event to a present-day document > 1 |
| **Constraint coverage** | Packs exercising one lever | Commitments spread across ≥4 constraint kinds |

A candidate pack whose lore constrains nothing fails at step 3 without a human reading it. That is the difference between self-extension and self-dilution.

Consistent with [meta-generation being an authoring-time activity](generation-model.md#20-meta-generation), none of this happens during `simulate()`. A pack is a reviewed, committed dependency, never a runtime invention.

---

## Sequencing consequence

This makes the retail lore pack the critical path for everything meta. Its quality ceiling becomes the platform's, because every later pack is generalised from it.

That is an argument for building it small and early rather than large and late. The [build order](build-order.md) puts a minimal lore slot at step 3: three to five commitments for the retail close episode, enough to prove that lore constrains generation, and defers the full pack to step 8.

The reason is dependency direction, not scope. Lore feeds the org generator, the persona model, and the artifact planner. Adding the mechanism once those exist means touching all three; designing the slot early costs almost nothing.

---

## Worked example: the smallest useful lore

The [golden episode](build-order.md#1-hand-author-one-golden-enterprise-episode) states that engineering identifies stale product hierarchy data. On its own that is an unexplained coincidence. Three commitments make it a consequence:

```
LORE-0001  category_restructure
  kind:    decision
  when:    2024-08
  actors:  [ORG-merchandising]
  assertion: Product hierarchy remapped for a new category structure;
             the mapping table was maintained manually thereafter.
  constrains:
    event_likelihood  → data_quality_incident (inventory domain) ×2.5
    artifact_density  → merchandising runbooks −40%
  scars:   [LORE-0002]

LORE-0002  hierarchy_ownership_gap
  kind:    constraint
  when:    2024-11 ..
  actors:  [ORG-merchandising, ORG-data-platform]
  assertion: No team owns the hierarchy mapping. Both believe the other does.
  constrains:
    approval_chains   → hierarchy changes: no required reviewer
    persona_trait     → PERSON-0117: defensive_about_ownership +0.3
    event_likelihood  → recurrence after remediation ×1.8

LORE-0003  close_calendar_pressure
  kind:    norm
  when:    2022-01 ..
  actors:  [ORG-finance]
  assertion: Month-end close is expected within four business days;
             overruns are escalated to the CFO.
  constrains:
    metric_emphasis   → close_cycle_time: high
    artifact_density  → finance status reports +50% during close
    risk_appetite     → finance/workarounds: permissive
```

Everything the episode needs now follows from lore rather than from authorial fiat: the pipeline fails because a manual mapping went unmaintained (LORE-0001), nobody caught it because ownership is ambiguous (LORE-0002), the delay is escalated because four days is the norm (LORE-0003), a workaround is accepted because finance tolerates them under close pressure (LORE-0003), and the remediation ticket addresses a *control* failure rather than a data failure (LORE-0002).

Three commitments, five downstream consequences, and the episode's "why" is answerable. That is the whole idea at the smallest scale that demonstrates it.
