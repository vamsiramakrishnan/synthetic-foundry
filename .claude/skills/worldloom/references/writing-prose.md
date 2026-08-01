# Writing prose

You are here because `worldloom narrate requests ./corpus -o requests.json` has
already run. This is the actual job: read `requests.json`, write `responses.json`,
submit it, and fix whatever comes back rejected. Everything below explains the
contract precisely enough that a rejection is fixable on the first read, not a
surprise to be worked around.

## The request

`requests.json` has a top-level `rules` array (read it — it is the same rules
below, generated from the same source, so if the two ever disagree trust the
JSON) and a `requests` array. One entry per section an artifact needs written.
Fields that matter:

| Field | What it is |
| --- | --- |
| `id` | `<artifact_id>/<section>`. Copy it exactly into your response — it is the join key. |
| `written_by`, `voice`, `audience` | Who is writing, in what register, for whom. |
| `purpose` | What this section has to accomplish. Not a summary of the facts — the job. |
| `background` | Standing context (from lore) you may reason from and allude to. Not citable, not a figure, and never assertable as a finding — see below. |
| `hierarchy` | Subject name to where it sits, e.g. `"division of Ardent Holdings"`. Lets you write "the largest division" instead of naming all four. |
| `knows_as_of` | When the document was written. See `not_yet_known` below. |
| `must_not_claim` | Phrases this document may not contain, verbatim. |
| `terminology` | The world's vocabulary notes, term → how it is used (e.g. legacy and new names for one thing that are not interchangeable). Advisory register guidance — follow it, but no validator rejects on it. |
| `target_words` | Roughly how long. Not a hard limit, but a two-sentence answer to a 200-word request is not doing the section's job either. |
| `facts` | The only facts you may use. Each carries `id`, `statement` (the value, already formatted — do not reformat it), `authority`, `valid_from`, `superseded`, `required`, and sometimes `prior_period_fact` (the ID of the same measure a period earlier, so a trend is two references, not a described movement). |

If a fact is not in this array, you do not have it — not from another request in
the same batch, not from having seen the corpus elsewhere. The request is the
whole boundary.

## The response

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

One entry per request, `id` matching exactly. `text` is the prose for that
section alone — no heading, no preamble, nothing that duplicates `section` or
`artifact_type`. `claims` is a separate structured layer: each claim is one
assertion your prose makes, paired with every fact ID that backs it. Claims are
not a citation list bolted onto the end — they are what makes the prose
checkable at all, because free text cannot be validated against a ledger and a
list of (assertion, supporting facts) pairs can. A claim with an empty
`supporting_fact_ids` is rejected outright, by schema, before it even reaches the
checks below: a claim citing nothing is not weak, it is invalid.

Submit with:

```bash
worldloom narrate accept ./corpus --from responses.json --model-id <your model>
```

The whole batch is reviewed together, not stopped at the first failure — you get
every violation across every section in one pass, and nothing commits unless all
of them clear. There is no partially-narrated corpus to worry about leaving
behind.

## Every rejection code

Grep `src/worldloom/narrative/claims.py` if you want to see these enforced
directly; this is what each one means and how to fix it.

**`bare_number`** — by far the most common. A digit run sitting outside a
`{{fact:ID}}` reference. Checked lexically (`src/worldloom/narrative/references.py`,
`BARE_NUMBER`): any `\d[\d,.]*` not immediately wrapped in `{{fact:...}}` fails,
no matter how it got there. This is why `"Revenue finished 2.48% below plan"` is
rejected even though every part of it is true — **percentages and dates are
figures too**, not just currency amounts. `"the third quarter"` is fine (no
digit); `"Q3 2026"` or `"finished 3 days late"` are not — replace the number with
the reference: `` finished {{fact:FACT-0019}} late ``. There is exactly one
reason this rule exists: a typed-out figure is a copy, and the renderer cannot
keep a copy in sync with the ledger the way it keeps a reference in sync. Fix:
find the digit, find the fact ID in your request whose `statement` produced that
value, replace the digit with `{{fact:THAT-ID}}`. If no fact in your request
carries that value, you should not be stating it at all — see `unsupported_claim`.

**`unsupported_claim`** — a claim in your response cites a fact ID not in this
request's `allowed_fact_ids`. Not "not in the corpus" — not in *this* request.
The same fact can be perfectly real and cited correctly by a different section
and still be wrong here, because the request is what bounds what this
particular author, writing this particular document, was given to work with.
Fix: either drop the claim, or find the fact actually in your `facts` list that
supports what you meant to say.

**`unresolvable_reference`** — a `{{fact:FACT-XXXX}}` in your `text` whose ID
does not exist in the fact ledger at all (typo, invented ID, or you copied an ID
from another request). Fix: match it against the `id` fields in your request's
`facts` array exactly.

**`required_fact_omitted`** — a fact marked `"required": true` never showed up,
either as a `{{fact:...}}` reference in the text or in a claim's
`supporting_fact_ids`. A `required` fact is why the artifact exists; skipping it
is skipping the point of the section, not a stylistic choice. Fix: work it in,
even if only in a subordinate clause.

**`not_yet_known`** — you cited a fact whose `valid_from` is after this request's
`knows_as_of`. This is the temporal-cutoff rule: `knows_as_of` is when the
document was written, and an author cannot cite something discovered later. A
triage page written at 09:26 cannot reference a root cause confirmed at 13:27,
even if that root cause is sitting right there in the ledger for other,
later-written documents to use. Fix: drop the citation, or reach for the
superseded/earlier fact that *was* known at that point (see below — this is
usually not a dead end, it is the interesting case).

**`forbidden_claim`** — your `text` contains one of `must_not_claim`'s phrases,
case-insensitively, as a substring. These exist so a document that is not the
place to draw a conclusion (a status page, a working note) does not draw it.
Fix: say what you were asked to say without using the forbidden wording — this
is usually a sign you reached for a conclusion above the document's pay grade,
not just a phrasing collision.

**`unknown_entity`** — a two-or-more-word capitalised run in your prose (a cheap
proxy for a proper noun) that does not match the world's actual company,
business unit, person, or system names. This only fires when the reviewer
supplies the world's entity list, which `narrate accept` always does. Fix: you
invented a name, or misspelled a real one — check it against `hierarchy` and
`subjects` in the request, or against `worldloom inspect ./corpus`.

## The two subtle ones

**`knows_as_of` and `not_yet_known` are about permission to refer, not about
truth.** The check is `valid_from <= knows_as_of` — whether the fact had come
into existence yet — never `holds_at(knows_as_of)`, whether the fact was
*current* at that moment. Those are different questions on purpose. If it were
`holds_at`, an RCA written after a hypothesis was superseded could never mention
that hypothesis at all, because by the time the RCA is written the hypothesis no
longer holds — and discussing a specific, falsified hypothesis is close to the
most realistic thing an RCA does. `valid_from <= cutoff` lets you cite it as
something that existed and was believed; the `superseded` flag (next) is what
stops you from asserting it as current.

**A `superseded: true` fact is a past belief, not a current one.** It was
recorded, it was true-as-far-as-anyone-knew at the time, and it was later
proved wrong. Write it as history: "the initial read was
`{{fact:FACT-0004}}`", "it was first recorded as...", "that did not hold" —
never as a flat present-tense assertion. This is exactly how a real incident RCA
talks about the hypothesis that turned out wrong: it is on the record, it
explains why the response looked the way it did at the time, and it is clearly
marked as superseded rather than restated as fact. Compare the two treatments of
the same fact across an incident's documents in
`examples/grocery-close/narration.json` — `ART-0004/Running note` (written while
the hypothesis is still live: "First read was `{{fact:FACT-0004}}` — that is
what the overnight picture suggested... It did not hold") versus `ART-0007/Root
cause` (written after confirmation, citing the same fact purely as the thing
that got ruled out). Same fact ID, opposite tense, both legitimate, because
`knows_as_of` differs.

## Quality, past the floor

Passing every check above is necessary and is not the job. The dullest possible
response is one sentence per fact, in the order given — it will pass, and it is
not what this is for.

**Sections are given different facts on purpose.** A section headed "By
business unit" was handed unit-level figures, not the group figure, specifically
so it argues at that level instead of restating the position a reader already
got from the section above it. If you find yourself repeating the group number
inside a unit-level section, you are probably being handed the wrong facts for
what you're about to say — check the `purpose` field again.

**Lead with the position, not the ledger order.** `facts` arrives in whatever
order the request builder produced; the strongest one is not necessarily first.
Real prose says what happened, then supports it — "Australian Food carries the
period" before the four divisions get their numbers, not four evenly-weighted
sentences with the verdict left for the reader to infer.

**Weight facts by what they're worth.** A division that landed on plan earns a
clause; the one that blew the largest hole in gross profit earns the paragraph.
`examples/grocery-close/narration.json` is worked, accepted-first-pass prose —
`ART-0003/By business unit` gives Australian Food three sentences and dispatches
New Zealand Food and General Merchandise in one ("Both behaved normally and
neither warrants time this month"), which is the shape a controller's memo
actually has.

**Use `prior_period_fact` for trend claims instead of describing a movement in
words.** "The third consecutive month of erosion" is not a sentence the harness
can check on its own; citing this period's margin and last period's margin side
by side is. If a fact in your request carries `prior_period_fact`, both IDs are
in `allowed_fact_ids` — cite both.

**Reason from `background`, don't cite it.** It's lore-derived standing context
(why the numbers look the way they do), explicitly not a figure and explicitly
not checkable against the ledger the way a fact is. You may allude to it — "a
promotional programme agreed jointly rather than set alone" — but never present
it as something the figures themselves establish, and never wrap it in
`{{fact:...}}` (it has no fact ID; there is nothing to reference).

**Match the register to `voice` and `audience`, at roughly `target_words`.** A
controller writing a variance memo to the CFO is not the same author as a
service desk analyst logging a working note, even when both are describing the
same incident. `written_by` and `voice` are handed to you precisely so you don't
have to guess; use them.

## The rejection cycle

Expect rejection on the first submission — the harness treats it as the
guardrail working, not as your failure. When `narrate accept` reports
violations:

1. Read the `code` and `detail` for each one. The detail names the offending
   text or fact ID directly.
2. Fix exactly that. Do not touch sections that were not named.
3. Resubmit the whole `responses.json` (the accepted ones are unaffected by
   resubmission; nothing commits until everything in the batch passes).

**Never respond to a rejection by editing the corpus, loosening a check in
`claims.py`, or dropping the fact that triggered it.** The violation is
information about your prose, not a bug report about the harness. If a
`required_fact_omitted` seems impossible to satisfy gracefully, that is a sign
to restructure the sentence, not to drop the requirement.

## When not to write it yourself

`worldloom build ... --narrate` (or `worldloom demo`) fills every section using
the built-in `DeterministicProvider` — no model, no network, template sentences
keyed on fact kind. It is useful for a smoke test of the pipeline, and it is
exactly what its own docstring says it is: "not a stand-in for a language
model... it exists to exercise the contract, not to write well." It gets every
rule right and produces one flat sentence per fact, always in the same shape.
Reach for it only when you need *a* corpus fast and prose quality does not
matter to what you're testing. The moment someone needs documents that read like
the real thing a controller or a service desk actually wrote — varied emphasis,
an argued position, register that shifts with the audience — that's the
narrate-requests / write / narrate-accept loop, and that's what this file is for.
