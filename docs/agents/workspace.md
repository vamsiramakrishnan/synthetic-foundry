---
title: Workspace layout
description: Lay a corpus out as a permissioned drive, and make it untidy the way real drives are.
read-when: Pointing an assistant or connector at the corpus as a drive, adding filesystem noise, or running the corpus against Gemini Enterprise.
tags: [workspace, permissions, filesystem-noise, layout, gemini-enterprise]
---

# Laying the corpus out as a drive

```bash
worldloom workspace ./corpus -o ./drive
```

A corpus exports as one flat `artifacts/` folder of numbered files, which is
right for the harness (it reads the manifest and never looks at a path) and
wrong for what the corpus is *for*. An enterprise assistant indexes the folder a
document sits in, the title somebody typed, who owns it and who it is shared
with, and this corpus knows every one of those and put none of them on the
filesystem: 293 files in one directory with identical permissions.

`workspace` writes the tree that knowledge implies. Documents are shelved by the
function that owns them (`Policies/`, `Finance/Close/2026-03/`,
`People/Performance/`), periodic ones filed under their period and standing ones
at the top of their shelf. Filenames are what a person would have typed and
carry the subject, so four reviews in a month are four names rather than `(2)`
through `(5)`. A policy revised in place sits beside its replacement marked
`(superseded)`; a monthly calendar that supersedes last month's is not marked,
because that is the ordinary life of a periodic document rather than a
retirement. `permissions.jsonl` is one row per file, owner and every address
permitted to open it, which is the half a connector actually needs, since a
tree with no permission table tests retrieval and cannot test access.

Nothing is invented: every folder, title, owner and reader is derived from the
manifest, the roster and the access policies, and the corpus itself is not
touched.

## Making it untidy, accountably

```bash
worldloom workspace ./corpus -o ./drive --noise neglected
```

`--noise` makes the drive untidy the way real drives are: `Copy of X`, a
document dragged into `Shared/` or `_Inbox/`, somebody's `X FINAL` beside the
real one, an `_Archive/` leftover. Every extra file is a **byte-identical copy
of real corpus content**, never invented text. A drive's junk is not fabricated
documents, it is the same documents saved again in the wrong place under the
wrong name, and that is what makes it hard: a retriever cannot tell the
copy from the original by reading it. A copy carries the permissions of what it
copies, so a misfiling is somewhere nobody would look and still readable only by
the people the original was.

Every junk file is **labelled** in `permissions.jsonl` with what kind it is and
what it duplicates. That is the difference between this and simply making
a mess: a benchmark scored against a drive it cannot account for cannot tell
"the assistant found the wrong copy" from "the assistant was wrong", and those
are different failures.

This is *filesystem* noise and not the same thing as `--messiness`, which is
content noise: a page nobody updated, two documents disagreeing, an author who
left. Both are real and they fail differently. A
corpus wanting a realistic archive wants both.

## Handing the drive to Gemini Enterprise

```bash
worldloom gemini-enterprise datastore ./corpus ./drive --uri-prefix gs://bucket/drive -o ./documents.jsonl
worldloom gemini-enterprise cases ./corpus -o ./shards
worldloom gemini-enterprise score ./corpus ./results.csv
```

[Eval Studio](https://github.com/GoogleCloudPlatform/gemini-enterprise-eval-studio)
reaches a Gemini Enterprise instance and times it, and does two things it does
not do: it selects data stores that already exist, so it has no way to put this
corpus in front of the assistant, and its stream parser keeps only the answer
text, so tool calls and grounding never leave the browser.

`datastore` reads a drive this page just wrote, **not a layout recomputed**, for
the reason `workspace` copies rendered files rather than re-rendering them: the
tree on disk is what gets uploaded, and a second layout is a second chance to
disagree with it. It emits Discovery Engine documents carrying `aclInfo` from
`permissions.jsonl`, which is what makes a permission failure observable at all.
Junk files matter here and are the reason document ids come from the path rather
than the artifact id: a copy shares the id of what it copies, and importing them
under it collapses the duplicates into one document.

`cases` shards the evaluation set by grading shape because Eval Studio applies
one auto-rater instruction per run, and one similarity rubric scores an
abstention backwards. `score` reads results back; its output carries no case id,
so the join is on the query text. Full loop and its failure modes:
[Gemini Enterprise](../gemini-enterprise.md).
