# Security policy

## Reporting a vulnerability

Report privately through GitHub security advisories:
**[Report a vulnerability](https://github.com/vamsiramakrishnan/worldloom/security/advisories/new)**,
not in a public issue. You should hear back within a week.

## What Worldloom is, for threat-modelling purposes

Worldloom is a local library and CLI that deterministically generates
**fictional, synthetic enterprise-shaped data**: invented companies, invented
people, invented figures. It operates no service, requires no API key, and
makes no network call, with one documented exception: the optional
`[embeddings]` extra, which downloads pinned model weights from Hugging Face.

## What is a vulnerability here

- Code execution or path traversal while loading untrusted input: a corpus
  directory, a pack/spec/physics JSON file, a `responses.json`, or anything
  else the CLI parses. These files are the tool's attack surface, because a
  user can reasonably be handed a corpus or a pack by someone else.
- `worldloom workspace` or `render` writing outside its `--out` directory.
- Dependency confusion or malicious-lookalike issues in the packaging.

## What is not a vulnerability here

- **Resemblance to a real company or person.** All output is fictional by
  construction; any resemblance is coincidental. (A generated name colliding
  with a real trademark is a naming bug, not a security issue; file it
  publicly.)
- **"Sensitive-looking" output.** The tool's purpose is enterprise-shaped
  documents: salaries, incidents, board papers. They are invented. Synthetic
  data that looks confidential is the product working, not leaking; there is
  no real-world data anywhere in the pipeline for it to leak.
- **Determinism.** Same seed, same corpus, for everyone, forever, is the
  central feature, not a predictability weakness. Nothing here is a secret
  derived from a seed.
- Bugs in what a corpus *says* (a total that doesn't add up, a broken
  reference): that is `worldloom validate`'s jurisdiction and an ordinary
  public bug report.
