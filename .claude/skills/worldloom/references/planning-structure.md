# Proposing an artifact's structure

Loaded when you run `worldloom plan requests`. This is the handshake one layer
above prose: before you write anything, you decide what shape the document takes.

## Why this exists

Without it, structure comes from a hard-coded outline, so every CFO memo in every
period has the same four sections in the same order. A twelve-period corpus of 120
artifacts carried **11 distinct section shapes**. Structure is a judgment — what to
lead with, what this reader needs, what belongs in an appendix — and judgment is
the part you are here for.

Making the outline *random* would not fix it. A shuffled memo is not a memo. So you
propose a shape and the harness checks it against the artifact's grammar.

## The loop

```bash
worldloom plan requests ./corpus -o plans.json
#   you read plans.json and write your proposals back
worldloom plan accept ./corpus --from plans.json --model-id <your model>
```

Then the ordinary prose loop runs against the structure you chose:

```bash
worldloom narrate requests ./corpus -o requests.json
worldloom narrate accept ./corpus --from requests.json --model-id <your model>
```

## What a request gives you

Everything needed to answer it, and nothing to go looking for elsewhere:

| Field | Use |
| --- | --- |
| `artifact_type`, `audience`, `written_by`, `voice` | who is writing, to whom |
| `size_class` | how much room there is |
| `available_facts` | every fact you may cite, with the **subject named**, not just an id |
| `required_fact_ids` | facts this document exists to convey. Omitting one is a rejection |
| `vocabulary` | the semantic roles you may assign a beat, each with its purpose |
| `constraints.prose` | the artifact's grammar in plain English |
| `recent_headings` | headings this author already used on other documents |

`recent_headings` is the field that produces diversity rather than merely
structure. An author who can see they already wrote "Position" three times has a
reason to write "Where we landed" instead. Use it.

`constraints.prose` states the rule you must satisfy, for example:

> Must open with a beat filling 'position' or 'summary'; must include a beat
> filling each of 'evidence' and 'position'; 'position' must appear before
> 'explain_change'; 'evidence' must appear before 'decision'; needs at least 2
> beat(s).

A rejection you could not have predicted would be a bad handshake, so the rule is
always in the request.

## What you answer with

```json
{
  "plans": [
    {
      "id": "ART-0003/plan",
      "intent": "explain the month and ask for a decision on phasing",
      "emphasis": ["margin", "the delayed close"],
      "beats": [
        {
          "heading": "Where we landed",
          "purpose": "State the group result against plan and say plainly whether the month was acceptable.",
          "semantic_role": "position",
          "optional": false,
          "evidence": [{"fact_id": "FACT-0020", "role": "headline", "emphasis": 0.9}]
        }
      ]
    }
  ]
}
```

One entry per request, `id` copied exactly. Beats are ordered, and **the order is
the argument**.

## What you decide, and what you must not

**Yours:** the headings, which beats exist and in what order, which beats are
optional, what to foreground for this audience, each beat's semantic role.

**Not yours:** which facts are true, which rows are in a table, how a variance is
computed, or whether your own sequence is grammatical. You propose; the
deterministic layer accepts or rejects.

## Rejection codes

The whole set is reviewed at once and **nothing commits unless everything passes**
— a partial commit would leave a corpus half-planned with no record of which half.

| Code | Meaning |
| --- | --- |
| `ungrammatical` | the sequence fails the artifact's grammar. The grammar's own violation text is reported |
| `unknown_role` | a `semantic_role` no component provides. Use one from `vocabulary` |
| `unknown_fact` | evidence citing a fact outside `available_facts` |
| `required_fact_omitted` | a `required_fact_ids` entry no beat carries |
| `duplicate_heading` | two beats in one document share a heading |
| `heading_too_long` | over 60 characters. A heading that has become a sentence is not a heading |
| `empty_heading`, `empty_purpose` | a beat that says nothing about itself |
| `all_optional` | every beat droppable, so the document could compose to nothing |

`purpose` is not decoration. It reaches the narrative request later and is what
decides whether the prose argues or lists — a writer told "here are four metrics"
produces four correct sentences and nothing better.

## Writing headings worth having

The dullest correct answer is the section's own subject: "Position", "Drivers",
"Summary". They are never wrong and never memorable, and a corpus full of them is
the defect this handshake exists to fix.

Vary by what the document actually says this period. "Where we landed" when the
result is clean; "Why margin moved" when it is not; "The close ran late" when that
is the story. Check `recent_headings` and do not repeat yourself.

Match the voice. A service desk analyst writes "Current position", a CFO's
controller writes "Group result", and an RCA writes "What we now believe happened".
