---
title: Writing responses
description: Answer narration requests under the fact rules — references, claims, voice, and search.
read-when: Writing responses.json for narrate accept, or a submission was rejected and you need the rule.
tags: [narration, responses, fact-references, claims, search]
---

# Writing responses

`requests.json` carries everything you need. Do not go looking for other context;
if a fact is not in the request, you may not use it.

Each request looks like this:

```json
{
  "id": "ART-0003/By business unit",
  "artifact_type": "cfo_variance_memo",
  "section": "By business unit",
  "written_by": "Group Financial Controller",
  "voice": "precise, procedural, cautious",
  "audience": "group_cfo",
  "target_words": 130,
  "knows_as_of": "2026-04-08T09:40:00+00:00",
  "must_not_claim": [],
  "facts": [
    {
      "id": "FACT-0020",
      "statement": "financial.revenue.actual = 408,800 AUD_thousands",
      "authority": "system_of_record",
      "valid_from": "2026-04-07T16:40:00+00:00",
      "superseded": false,
      "required": true
    }
  ]
}
```

Answer it like this, one entry per request, `id` matching exactly:

```json
{
  "responses": [
    {
      "id": "ART-0003/By business unit",
      "text": "Food finished {{fact:FACT-0028}} against plan, the largest of the three shortfalls.",
      "claims": [
        {
          "text": "Food finished below plan by the largest margin.",
          "supporting_fact_ids": ["FACT-0028", "FACT-0029", "FACT-0030"]
        }
      ]
    }
  ]
}
```

## The rules, and why each exists

**Never write a number.** Every figure, percentage, and date goes in as
`{{fact:FACT-0028}}`. The renderer substitutes the value from the ledger at render
time, so a board deck and the workbook it derives from read the same entry and
neither holds a copy. A number you type is a copy, and a copy can drift. This is
checked lexically — any digit outside a reference is rejected.

**Every claim cites its facts.** A claim with no support is invalid, not merely
weak: there is nothing to check it against.

**Use only the facts in your request.** The request is the boundary. Citing a fact
outside it means you reached for something the author of this document did not
have.

**Respect `knows_as_of`.** This is when the document was written. You may not
anticipate anything discovered later — a triage page written at 09:26 cannot cite
a root cause confirmed at 13:27, and the corpus depends on it not doing so.

**A `superseded` fact is a past belief.** It was true when recorded and later
proved wrong. Refer to it as history — "it was initially recorded as…" — never as
the current position. This is how an incident RCA discusses the hypothesis that
turned out to be wrong.

**Invent no entities.** No company, person, system, or metric that is not in your
facts.

**Write in the given voice, for the given audience, at roughly the given length.**
This is the part that is actually yours. A CFO's controller writes differently from
a service desk analyst, and an executive summary is not an RCA.

## Aim for a document, not a list

The dullest possible correct answer is one sentence per fact. Prefer prose that
argues: lead with the position, group what belongs together, say what it means.
Sections partition the facts deliberately — a section headed "By business unit"
was given unit figures precisely so it does not restate the group position.

## Reading what the corpus already says

```bash
worldloom search ./corpus "operational incident stock loss" -k 3
worldloom search ./corpus "margin" --as-of 2026-03-31 --json
```

Ranks the corpus's own passages against a query — the same passage index and
the same BM25 ranking `evaluate` scores retrievers with, so what you retrieve
while writing is exactly what the benchmark's baseline retriever will see when
the corpus is judged. Use it before writing a document that leans on earlier
ones: how the incident memo phrased the outage, which sections already carry a
figure, what a summary should echo rather than restate. `--as-of` applies the
temporal-cutoff rule to retrieval — an author amending in March may only lean
on what existed in March.

What it is not: a fact source. The facts-only rule above stands unchanged — if
a fact is not in the request, you may not use it, however prominently a search
hit displays it. Search informs *how* you write (register, continuity, what to
echo); the request alone governs *what* you may claim.
