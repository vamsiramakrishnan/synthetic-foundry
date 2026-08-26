# AlphaEvolve variation-policy receipt — 2026-08-19

## Scope

- Production seam: `src/worldloom/evolve.py:_propose_children`
- Control: value occurrence count, then content-addressed tie key
- Reviewed policy: varied-axis count, value occurrence count, then the same tie
  key
- Search corpus: 64 deterministic cases (`search-v1`)
- Holdout: 37 independently salted cases (`holdout-v1`)
- Adversarial: 4 named cases
- Managed AlphaEvolve run: not run; no cloud or spend claim

## Finding

The control was complete—it selected an admissible child—but did not always
select the least-varied axis. A four-slot replay near the repository's usual
seed touched only three axes in six of eight seeds checked during diagnosis.
The reviewed axis-first policy touched all four in every replay while retaining
value spreading and the existing deterministic tie.

On the frozen search matrix, the control agreed with the lexicographic oracle
on 20/64 cases; the reviewed policy agreed on 64/64 and reduced axis-reuse debt
from 116 to 17 (85.3%). On holdout it moved 6/37 to 37/37 and axis-reuse debt
86 to 8 (90.7%). The tradeoff is explicit: value-reuse debt rose 16 to 97 on
search and 10 to 58 on holdout, because avoiding an already-overused axis is
the primary objective and value spreading is subordinate within the selected
axis. This is a lexicographic improvement, not a Pareto claim.

The repository-local evaluator is the authoritative numeric receipt. Re-run:

```bash
python -m evals.alphaevolve.portfolio --local
pytest -q tests/test_alphaevolve.py tests/test_evolve.py
```

The integrated policy must achieve exact oracle agreement on all 64 search, 37
holdout, and 4 adversarial cases. The current production-shaped seed remains in
`variation_policy/program.py` so its comparison is reproducible.

## Promotion and limitations

The result supports one narrow claim: under a fixed child-build budget, the
evolution schedule balances categorical axes before reusing one. It does not
show that a generated fleet is more realistic, harder for a deployed
retriever, cheaper end to end, or superior on a managed AlphaEvolve run.

The production change is a reviewed translation, not generated source. Fleet
fitness still cannot steer generation; validation, replay, and both ledgers are
protected from the candidate. Full repository verification remains required
before release.
