# Releasing

A release is a tag. Everything else is automated, and everything the automation
checks is the same thing CI checks on every push, plus one check only a release
can make: the tag and the package must agree about the version.

## The procedure

1. **Bump the version in one place**: `src/worldloom/__init__.py`.
   `pyproject.toml` reads it from there (`[tool.hatch.version]`), and a built
   world stamps it into its `world.json`, so there is nowhere for two versions
   to disagree.

2. **Write the CHANGELOG entry.** What a user of the previous release needs to
   know, not a commit list. A change that alters what a seed generates belongs
   under its own heading. It is the one kind of change this project treats as
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

Publishing uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/):
no API token is stored in this repository. The workflow rehearses on TestPyPI
before it touches PyPI, so both indexes need a publisher, and each maps to a
GitHub environment of its own.

The `worldloom` name was unclaimed on both indexes when this was written. A
project that does not exist yet is registered through a *pending* publisher
(PyPI: your account, "Publishing", "Add a new pending publisher"); the first
upload creates the project and converts the publisher to an ordinary one.

| Field | PyPI | TestPyPI |
| --- | --- | --- |
| Project name | `worldloom` | `worldloom` |
| Owner | `vamsiramakrishnan` | `vamsiramakrishnan` |
| Repository | `worldloom` | `worldloom` |
| Workflow | `release.yml` | `release.yml` |
| Environment | `pypi` | `testpypi` |

In this repository's settings, create both environments, `pypi` and `testpypi`.
Restricting `pypi` to protected tags is worth the extra minute.

The `testpypi` job in `release.yml` exists to catch the one failure the wheel
smoke cannot: the upload itself. Once 0.1.0 has shipped, it can be deleted.

## The first release, in order

Each step depends on the one before it.

1. Rename the repository to `worldloom` (Settings, General, Repository name).
   GitHub redirects the old URLs; the badges, clone commands and the docs site
   base path already point at the new name.
2. Register the two pending publishers above against repository `worldloom`.
3. Create the `pypi` and `testpypi` environments.
4. Merge the release pull request.
5. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

`release.yml` then runs the matrix, the docs check, the golden-episode
validation and the wheel smoke; rehearses the upload on TestPyPI and installs
from it; and publishes to PyPI. The docs site redeploys from main on the next
push.

## What makes a release breaking

Two independent axes, and the second is the unusual one:

- **API**: the ordinary semver contract over `worldloom`'s public names.
- **Generation**: any change to what a seed produces: a generator edit, a
  prompt version bump, a new fact in an episode. Corpora stamp the version that
  generated them, and the CLI warns when a corpus is advanced under a different
  release, but the stamp only diagnoses; the CHANGELOG is where the change is
  declared. If a release changes generation, say so, prominently.

A corpus built under an old release stays loadable, queryable, renderable, and
validatable under the new one. That is the schema-version contract in
`corpus.py`, and it is separate from whether the same seed would regenerate it.
