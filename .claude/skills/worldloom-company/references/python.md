# Driving a company specification from Python: sdk.described and company.resolve.

```python
from worldloom import sdk, company

blueprint = sdk.described({"industry": "general insurance", "geo": "germany",
                           "facets": {"listing": "listed"}})
built = blueprint.build().episodes("2026-03")

resolution = company.resolve(company.from_document("company.json"))
resolution.ok, resolution.unmet, resolution.as_dict()
```

`sdk.described` returns an ordinary `Blueprint`, which is the point: cross it,
sweep it, disperse it, filter on what came out — everything
`.claude/skills/worldloom-sdk/SKILL.md` describes applies to a described
blueprint unchanged.

`company.resolve` is the same resolution with its `unmet` list intact, for when
you want to read what a description committed to and the engine did not honour
— the CLI prints those lines and moves on; the SDK hands you the list.

A probe composes here too: `worldloom probe resolve` emits terminal-parameter
overrides, and pasting them into the document's `physics` block puts the argued
ranges and the described company in one artifact that is refused as a whole.
