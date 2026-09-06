---
title: Paperwork and signatures
description: Add hiring and review rounds, standing policies, and approval blocks the validator can hold.
read-when: The corpus needs documents beyond its episodes: vacancies, reviews, policies, or signatures.
tags: [hiring, reviews, policies, approvals, standing-documents]
---

# Line management produces documents

The organisation was modelled in full and used as a source of *bylines*. A
420-person retailer named 24 of 444 people anywhere in its corpus: a manager
three levels down existed, had a name, a function and a manager of their own,
and appeared in nothing.

```bash
worldloom build --seed 8128 --policies core --periods 3 \
  --hiring 3 --reviews 4 --out ./corpus
```

`--hiring` raises, approves, offers and fills vacancies; `--reviews` reviews
people. The hiring manager and the reviewer come from **everybody with a direct
report**, 73 people on a synthesised 420-person company against the dozen the
role table names, which is what the two rounds are for. Measured on three periods:
113 artifacts across 28 types with none above 21%, and 41 distinct people named
in 37 distinct titles.

Two things make these more than filler. **A requisition reads the company's own
rules**: its three-year commitment is checked against the delegation of
authority, and the lowest rung that covers it signs, so "was this approved at
the right level" is the first question here whose answer is in neither document
alone. And **the two performance records disagree by design**: the signed
review is an approved report countersigned one level up, the running one-to-one
note is an unofficial note carrying the view held before calibration, and the
authority ranking is what resolves them.

Both rounds mint a fifth access class on first use: an offer letter states one
person's salary, and none of the four classes an engine ships describes a
readership of one person and their line.

# The paperwork a company has, rather than the paperwork it produces

Every document in this corpus was **episodic**: a close ran, an incident
happened, a return was filed, and paperwork came out of it. Measured on a
twelve-period, eight-division build: 195 artifacts, of which 96 were the same
type with a different division's name on it, and not one of them was a policy.
An assistant asked "what is our expense approval threshold" or "how long do we
keep contracts" had nothing to find, because the company had no rules.

```bash
worldloom build --seed 8128 --policies core --out ./corpus   # five
worldloom build --seed 8128 --policies full --out ./corpus   # ten
```

A standing document is a different shape, and `worldloom.policies` says so in
three ways. **Nothing triggers it.** It is not caused by an event and does not
report a period; it is in force, from a date, until it is revised. **Its content
is parameters.** "Receipts above 90 need a manager's approval" is minted as a
`CanonicalFact` with a number in it, so every question this repository can
already ask of a figure works on a policy unchanged, and forty-eight `policy.*`
kinds sit in `factkinds` beside every other. **A revision is supersession.**
The earlier threshold's window closes, the later fact records what it
superseded, and *the earlier document stays on the shelf*, which is what makes
"what was the limit before the revision" answerable rather than merely askable.

Money provisions are stated as a fraction of the company's own revenue and
rounded to a figure a policy would really name, so a 7.8bn retailer and a 2bn
insurer do not share an expense limit. A delegation-of-authority ladder that
stops climbing is refused rather than clamped, and a policy is dated no earlier
than whoever signed it joined. That is `form_units`' rule about a unit and its
leader, and `validate.author_not_yet_employed` found the violation the first
time it was not applied.

`--policies` is off by default and a strict no-op, so every corpus built before
it existed is byte-for-byte what it was. `policies.register` adds an area for a
vertical whose paperwork genuinely is its own.

# Who signed it

Every document was authored and none of them approved, which is not how a
company's archive works: "who approved the March pack for Fuel and Convenience"
is the first question a real reader asks. A signed document now carries an
**Approval** block (prepared by, approved by, name, role, date) in Markdown,
DOCX, PDF, PPTX and as a worksheet in XLSX. Ten distinct people were named
across an eight-division corpus before; nineteen after.

Who signs what is a table per vertical (`_APPROVED_BY` in each planner), because
who signs a prudential return is an argument about banking rather than a rule
about documents. The divisional close commentary is the one approval that fans
out with the company: eight divisions means eight different managing directors
signing eight different documents.

**Absence is a claim.** A ServiceNow ticket has an assignee, an email thread a
sender, a calendar is issued rather than approved; banking's RWA working paper
is unsigned *because* it is the contested-authority distractor, and internal
audit's review carries the Chief Internal Auditor's name and no countersignature
at all. A corpus where everything is signed is as unlike a real archive as one
where nothing is.

`validate.approvals` holds a signature to being one somebody could have given:
the approver exists, is not the author, and is permitted by the document's own
access policy. It found two real defects the day it existed and a third the
first time a unit changed hands, which is why `personnel.promote` now carries
the post's access to whoever holds it. Added, never substituted: the archive is
historical and the policy is current state, so striking a name off today would
retroactively invalidate every signature that person ever gave.
