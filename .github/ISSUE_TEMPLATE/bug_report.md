---
name: Bug report
about: Something built, rendered, validated, or replayed wrongly
labels: bug
---

## What happened

<!-- What you saw, and what you expected instead. If `worldloom validate`
     reported it, paste the violation line — it names the rule. -->

## Reproduce it

Reproducibility is this tool's whole premise, so a bug report that carries the
seed and flags is usually fixable the same day:

```bash
# The exact command, including the seed and every flag, e.g.:
worldloom build --seed 8128 --incident --out ./corpus
```

- **Version**: `worldloom version` →
- **Python**: `python3 --version` →
- **OS**:

## If the corpus was built from more than flags

<!-- Attach or inline the recipe (`recipe.json` inside the corpus), and any
     pack / spec / physics file the build used. The recipe is how a corpus
     rebuilds itself; with it, we see exactly the world you saw. -->

## If the bug is a replay difference

<!-- Byte-identity failures are the highest-value reports we get. Paste the
     first differing file and, if you have it, the first differing line. -->
