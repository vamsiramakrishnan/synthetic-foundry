---
title: Registration Seams
description: Register a vertical through the four seams, and report, never widen, the closed tables.
read-when: Before writing any vertical code.
tags: [worldloom, vertical, registries, thin-waist, cli]
---

# The registration seams: what is open, and what is deliberately not

A domain module reaches core through four registries and nothing else; the
closed tables at the bottom are the gaps to report, not widen.

## The seven files

| file | what is in it |
|---|---|
| `<vertical>.py` | the world builder, the lore, the check group, the domain registration |
| `<vertical>_scenarios.py` | the episode as a frozen dataclass with `run`, plus `recipe.register_step` |
| `<vertical>_documents.py` | artifact intents, custom compilers, `register_artifact_types` |
| `generators/<vertical>_org.py` | role table, personas, systems, access policies |
| `generators/<vertical>_<figures>.py` | pure numbers, no facts |
| `generators/<vertical>_<episode>.py` | events and facts, no numbers |
| `generators/<vertical>_evaluation.py` | the benchmark families |

## The seams that work

```python
domains.register_domain(Domain(...))                 # how a build finds you
recipe.register_step(name, arg_names, build)         # your scenario as a recipe verb
documents.register_artifact_types(standing=, lags=, outlines=, compilers=)
validate.register_domain_checks(name, checks)        # your invariants
```

Registering a `Domain` is worth more than it looks. It is what makes all of
these work with no further edits:

```bash
worldloom build -a <your_archetype> --seed 8128 --periods 6 -o ./corpus
worldloom pack template <your_domain>      # a starter pack for your engine
worldloom pack targets <your_domain>       # your consulted lore targets
worldloom pack texts <your_domain>         # your overridable surface text
worldloom build --pack yours.json          # a pack whose `base` is your domain
worldloom validate ./corpus                # your check group, on every world
worldloom render ./corpus -f xlsx -f docx  # your registered renderers
worldloom evaluate ./corpus                # your benchmark families
```

`--periods N` runs your episode N times, stepping by the `period_step_months`
you registered. Fill in `consulted_targets`, `system_slots`, `role_keys`,
`episode_text` and `evaluation_text` on the `Domain`: they are not decoration,
they are what a pack author sees and what `pack check` lints against.

## The seams that are not there

Four core tables have no registration seam. Each is a closed literal, so a
fourth vertical cannot add to it without editing core, which
`tests/test_thin_waist.py` forbids, correctly. Report the gap rather than
widening the table:

| table | consequence for you |
|---|---|
| `parameters.DEFAULTS` | your physics ranges are invisible to `worldloom pack params` and `Parameters.with_overrides` refuses them by name, so **a pack cannot tune your engine's physics**. Keep your spans in your own module and layer them under whatever a caller supplies. |
| `landscape.LANDSCAPES` | `--estate` cannot grow a landscape in your vocabulary. Refuse the flag with its reason rather than serving a retailer's `click-collect-api`. |
| `mosaic.ENGINES` | `worldloom mosaic -e <yours>` is refused; the per-engine variation axes are a literal map. |
| `locales.industry_suffixes` | your companies are named from the *retail* suffix pool in every shipped jurisdiction, silently: `suffixes_for` falls back rather than raising. |

And one seam that is not a registry at all: **a domain module registers by
being imported**, and the only thing that imports it unconditionally is
`src/worldloom/__init__.py`. That import is a hand edit and there is no way
around it. Lazy registration is not an option: a check group that runs only
in processes that happened to import the right module is a check that passes
on machines where it never ran.
