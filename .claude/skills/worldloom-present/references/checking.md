---
title: Rendered Profile Checks
description: Check a rendered profile by reading the file: page count, figure spelling, harness voice.
read-when: After the first render under a new profile.
tags: [worldloom, presentation, rendering, pdf, verification]
---

# Checking a rendered profile: read the file, do not trust the flag.

```bash
worldloom render ./corpus -f pdf --profile reader
python -c "from pypdf import PdfReader; print(len(PdfReader('corpus/artifacts/art-0003-cfo-variance-memo.pdf').pages))"
```

Two things worth checking by eye, because a lint cannot:

1. **Does a figure read like a memo?** `AUD 5,372.8m` does; `AUD 5,372,800
   thousands` does not. If prose still reads the second way under a `scaled`
   profile, the figure has no shorter exact spelling and the ledger wording is
   the honest answer.
2. **Does anything in the document address its own generator?** Phrases like
   "not part of the readable surface" or "resolved before prose" are the
   harness talking to itself. Under `reader` they should be gone; if one
   survives, it is in a section the IR did not flag `hidden`, which is a defect
   in the artifact type rather than in the profile.
