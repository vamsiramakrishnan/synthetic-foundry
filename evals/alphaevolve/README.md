# AlphaEvolve optimization portfolio

This checkout-only portfolio applies AlphaEvolve to narrow Worldloom policy
seams. It does not let generated code write `src/worldloom`, alter a corpus,
change a validator, or redefine fleet fitness.

The controlled loop is:

1. freeze the current production policy as the seed;
2. expose one pure function inside one `EVOLVE-BLOCK`;
3. score it with model-free search cases outside the problem prompt;
4. require separate holdout and adversarial gates;
5. keep generated candidates quarantined;
6. translate a reviewed policy into ordinary production code and run the full
   Worldloom coherence, replay, determinism, and documentation gates.

The initial experiment, `variation-policy`, fixes a measured search-budget
defect in `worldloom evolve`: the previous policy minimized how often a value
had appeared, but did not minimize how often its axis had already been varied.
A wide axis could therefore take multiple child slots while narrower axes were
untouched. The reviewed policy ranks axis count, value count, then the existing
content-addressed tie key. It changes the search schedule only; it never feeds
fitness into generation and makes no realism or retrieval-quality claim.

## Local gates

```bash
python -m evals.alphaevolve.portfolio --list
python -m evals.alphaevolve.portfolio --local
python -m evals.alphaevolve.portfolio --ready-for-managed
python -m evals.alphaevolve.portfolio --promotion-report
python -m evals.alphaevolve.portfolio variation-policy --shadow
python -m evals.alphaevolve.portfolio --registry
```

The default and `--local` paths are offline and model-free. A local scorecard
reports search, holdout, and adversarial results separately. “Ready for
managed” means only that the experiment can safely be submitted; it is not a
claim that a managed winner exists or that production should change.

## Managed search

Managed search uses the official `alpha_evolve` client package, a configured
Gemini Enterprise engine, and an explicit spend confirmation:

```bash
python -m evals.alphaevolve.portfolio variation-policy \
  --managed --max-programs 12 --concurrency 2 --confirm-spend
```

Resume the same bounded resource rather than minting another experiment, or
fetch one generated program and run all local gates before reading it:

```bash
python -m evals.alphaevolve.portfolio variation-policy \
  --resume-experiment <full-resource-name> --max-programs 12 \
  --concurrency 2 --confirm-spend

python -m evals.alphaevolve.portfolio variation-policy \
  --inspect-experiment <full-resource-name> --program-id <program-id>
```

Required environment variables are `PROJECT_ID` (or
`GOOGLE_CLOUD_PROJECT`) and `GE_APP_ID`; `LOCATION`, `COLLECTION`, `ASSISTANT`,
`BASE_URL`, and `MODEL` are optional. No IAM change is made by this runner.
The bounds are enforced at 2–50 programs and 1–4 workers.

A managed result remains a hypothesis. Inspect its source, run all three local
gates, translate it into normal repository code, and verify the complete
Worldloom contract. Never copy generated source directly into `src/`.
