# The order of work — nine steps, each with the defect it prevents

Load this when starting the build. The order is dependency order: each step
consumes what the previous one decided.

1. **Decide what disagrees with what.** A vertical is worth building when two
   sources of truth can both be current and both be right about different
   questions. Retail's is a hypothesis versus a confirmed cause; banking's a
   filing versus its restatement; insurance's an actuarial estimate versus a
   booked reserve; procurement's an order versus a receipt versus an invoice.
   If nothing in your industry disagrees, you have a pack, not a vertical.

2. **Write the archetype.** Shape only — units, categories, sites, revenue,
   headcount. Keep revenue-per-head inside the envelope the registry already
   spans (`company.productivity_envelope`): an archetype outside it widens the
   envelope and quietly stops the scale check refusing what it was written to
   refuse.

3. **Write the org generator.** Copy `generators/insurance_org.py` and change
   the content, never the mechanism — `org_builder` is shared and its draw
   order is API. Forward `name_pools`, `headquarters`, `regions` and `locale`
   from the first commit; the insurance module shipped without them and was
   unconditionally Australian for its whole first life.
   **Make the reporting lines carry the disagreement.** If two documents are
   meant to be able to contradict each other forever, the people who write
   them should not report to the same person below the CEO — otherwise the
   corpus reads as one function contradicting itself.

4. **Write the figure generator, and size the trap by construction.** Draw in
   dependency order so the contest the vertical exists to pose *always* fires,
   and gate the multiple that guarantees it (`triangles._check_deficit_multiples`,
   `procurement_match._check_breach_multiple` are the two worked examples).
   Refuse physics that tunes the trap away rather than clamping it: a clamped
   range builds a valid corpus that no longer poses the question, and nothing
   tells the author.

5. **Write the episode generator.** Events and facts only; every number comes
   in from step 4, every timestamp is arithmetic on the period string, and the
   working calendar arrives as `locale_of(world.recipe)`. Decide each fact's
   authority deliberately — that field is what the benchmark is about.

6. **Write the documents.** Give the contested question **one document per
   answer** and make sure no single document holds two of them, or the
   authority family collapses into a lookup. Include a *clean* case in the same
   documents as the contested one, so the family cannot be passed by a rule
   about which document type to trust.

7. **Write the check group.** Every fact needs a check. Bucket by
   `(kind, period)` once and loop periods — the shape `validate.financial()`
   uses. Do **not** copy `banking._checks`, whose full-fact scans inside
   per-period loops make it 94% of validate's runtime at scale. Return
   `([], 0)` immediately on a world with none of your fact kinds.

8. **Write the benchmark.** End with the reachability gate
   (`cases.answerable`), and generate contrast cases beside inverted ones.

9. **Write the tests, and show every check firing.** A check that has never
   failed proves only that it compiles. `tests/test_procurement.py` is the
   current model: one tamper test per check, plus determinism, replay, and its
   own thin-waist scan over core for its own vocabulary.
