# Releasing

A release is a tag. Everything else is automated, and everything the automation
checks is the same thing CI checks on every push — plus one check only a release
can make: the tag and the package must agree about the version.

## The procedure

1. **Bump the version in one place**: `src/worldloom/__init__.py`.
   `pyproject.toml` reads it from there (`[tool.hatch.version]`), and a built
   world stamps it into its `world.json`, so there is nowhere for two versions
   to disagree.

2. **Write the CHANGELOG entry.** What a user of the previous release needs to
   know, not a commit list. A change that alters what a seed generates belongs
   under its own heading — it is the one kind of change this project treats as
   breaking even when no API moved, because a corpus regenerated under the new
   release will not be byte-identical to one made under the old.

3. **Commit, tag, push the tag:**

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. `release.yml` runs the full test matrix, the docs check, the golden-episode
   validation, and the wheel smoke (bare install, degradation messages, all
   formats, byte-identical replay). If everything passes, it publishes to PyPI.

## One-time setup

Publishing uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) —
no API token is stored in this repository. On PyPI, under the `worldloom`
project's publishing settings, add a trusted publisher:

| Field | Value |
| --- | --- |
| Owner | `vamsiramakrishnan` |
| Repository | `synthetic-foundry` |
| Workflow | `release.yml` |
| Environment | `pypi` |

And in this repository's settings, create the `pypi` environment. Restricting it
to protected tags is worth the extra minute.

## What makes a release breaking

Two independent axes, and the second is the unusual one:

- **API**: the ordinary semver contract over `worldloom`'s public names.
- **Generation**: any change to what a seed produces — a generator edit, a
  prompt version bump, a new fact in an episode. Corpora stamp the version that
  generated them, and the CLI warns when a corpus is advanced under a different
  release, but the stamp only diagnoses; the CHANGELOG is where the change is
  declared. If a release changes generation, say so, prominently.

A corpus built under an old release stays loadable, queryable, renderable, and
validatable under the new one — that is the schema-version contract in
`corpus.py`, and it is separate from whether the same seed would regenerate it.
