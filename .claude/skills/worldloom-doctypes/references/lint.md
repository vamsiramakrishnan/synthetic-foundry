# Reading the lint

Purpose: what `worldloom pack check` reports on an authored type, which
findings are refused, and why the rest are worth reading even though they
compile.

`worldloom pack check ./pack.json` runs it. Two findings are refused at build
time (`is reserved`, `already declared by a module`); the other fifteen
**compile**, which is why they are worth reading — each is a place where what
you wrote and what the engine does diverge. Samples:

```
artifact_types[3].sections[0] ('Outlook'): fact kind(s) 'esg.scope_three.' — no
document this engine declares is written about anything with that prefix. A
section whose prefixes match no fact is dropped rather than left empty, so this
does not fail: it compiles into a document that is carried, cited, and says
nothing.

artifact_types[3].sections[1] ('Outlook'): repeats the heading of section 0 — a
narrative request is keyed "<artifact id>/<heading>", so the two sections share
one request id and the second response overwrites the first.

artifact_types[2]: declares no `filing`, so nothing will ever plan one … the
type is declared, renderable, and inert.
```

`lore[N]: filing target 'X' names no artifact type` is the one to expect
first: lore asking for a document nobody declared resolves, plans nothing, and
reports success.

`examples/artifact-types/franchise-network-broken.json` fires every rule at
once — run `pack check` on it to see the full set before authoring anything.
