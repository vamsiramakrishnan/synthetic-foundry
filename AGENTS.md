# Worldloom, for agents

You are the model. Worldloom is the harness.

This repository does not call a language model. It builds a coherent synthetic
enterprise deterministically, works out which documents that enterprise would
have, hands you a bounded request for each one, and then **checks what you wrote
against the facts**. If you restate a number, cite something you were not given,
or mention an entity that does not exist, your prose is rejected with the reason
and you try again.

That division is the whole design. You supply judgement and language. The harness
supplies truth, and refuses anything that contradicts it.

Written to be agent-neutral: everything below is shell commands and JSON files, so
it works from Claude Code, Antigravity, or any harness that can run a terminal.

This file is the contract. The deep material — every optional stage, every
why-argument — lives one file per topic under `docs/agents/`, and the routing
map at the bottom says when to read which. Read a topic file *before* using its
surface, not after it refuses you.

---

## Setup

```bash
pip install -e ".[dev]"          # from a checkout; released: pip install "worldloom[all]"
worldloom doctor
```

`worldloom doctor` says whether this installation can do what these docs
promise, and names the exact fix for anything it cannot: the Python floor
(read from the package's own metadata), each registered render format's
optional dependency (a ✗ names the pip extra, e.g. `pip install
'worldloom[xlsx]'`), the bundled `retail-close` corpus validating, and — in a
checkout — the generated command reference being current. Exit 0 all-green, 1
otherwise; `--json` emits the check list as data. It reads only this process
and this disk, no network ever. Run it once after install, and again whenever
a render format refuses.

If the ask is loose — an industry, a purpose, a hardness bar, but no seed or
shape yet chosen — start one level up from the loop below:
`.claude/skills/worldloom/references/designing.md` is the decision guide for
turning that kind of ask into a build (stock archetype vs. authoring an
industry pack, which hardness families to force, deterministic prose vs.
writing it yourself), and in Claude Code `/worldloom-design` drives the whole
thing end to end — decide, author, build, measure, iterate, deliver. The loop
below assumes those decisions are already made.

## The loop

```bash
# 1. Build a world. Same seed, same world, every time.
worldloom build --seed 8128 --incident --out ./corpus

# 1a. Optional: let each document's *outline* be derived rather than looked up.
#     Without this every document of a type carries the same headings forever,
#     which is a shape a retriever can learn instead of the content. Off by
#     default, recorded on the recipe, and replays byte-for-byte.
#
#     --section-omission drops optional sections; --outline-synthesis draws a
#     shape from what this company's own document types have in common. Neither
#     can make a document say less than it did: a synthesised outline must carry
#     at least what the authored one carried, and falls back when no draw does.
worldloom build --seed 8128 --section-omission 400 --variant-bias 1 \
    --outline-synthesis 600 --out ./corpus

# 1b. Optional: choose each document's shape before writing any of it. Without
#     this, structure comes from a fixed outline and every memo looks the same.
worldloom plan requests ./corpus -o plans.json
worldloom plan accept ./corpus --from plans.json --model-id <your model>

# 2. Ask what prose is needed.
worldloom narrate requests ./corpus -o requests.json

# 3. Read requests.json. Write responses.json. (This is your job — read
#    docs/agents/writing-responses.md first.)

# 4. Submit. Accepted prose is committed and recorded; rejected prose is returned
#    with the violated rule, and nothing is committed.
worldloom narrate accept ./corpus --from responses.json --model-id <your model>

# 5. Materialise it.
worldloom render ./corpus -f xlsx -f docx -f markdown -f jira -f confluence -f servicenow

# 6. Check the whole corpus agrees with itself.
worldloom validate ./corpus

# 7. Find out whether it is actually hard, not merely coherent.
worldloom evaluate ./corpus

# 7b. And whether it is hard for a retriever anyone would deploy, not only for
#     keyword matching. `all` adds a dense retriever beside BM25 and TF-IDF and
#     names, per family, whether it is genuinely hard or merely a lexical trap.
#     Optional extra; without it the dense column is skipped with a message.
worldloom evaluate ./corpus --retriever all --vectors ./corpus/vectors.json
```

```bash
# 8. Lay it out as a drive somebody could be pointed at, with its permissions.
worldloom workspace ./corpus -o ./drive
```

At any point, `worldloom status ./corpus` names the stage the corpus is at and
the exact command that comes next — resume from that rather than from memory.
`status`, `validate`, and every `accept` command take `--json` when you would
rather read data than parse a table.

Steps 3 and 4 repeat until every response is accepted. Rejection is normal and is
not a failure of the harness — it is the harness working.

---

## What the harness will not let you do

`worldloom validate` prints the number of checks it ran — tens of thousands on a
large world — and treats any of these as a defect, not a warning:

- A total that does not equal the sum of its parts
- A variance that is not actual less budget
- A percentage that does not match the amounts it describes
- A document citing a fact that did not yet exist when it was written
- A reference to an entity, event, or fact that does not exist
- A reporting line that cycles, or a service that owns itself
- An author who cannot see the document they wrote
- Lore that constrains nothing
- A fact a document was asked to carry and does not carry
- A table cell that names a fact and states nothing
- Fewer compiled documents than the plan asked for

If you are tempted to make one of these pass by editing the fixture or relaxing a
check: don't. A validator that can be talked out of failing is decoration. Fix the
thing it caught. The defect that forced the last three checks, and the JSON
refusal envelope for parsing failures as data, are in
[docs/agents/refusals-and-envelope.md](docs/agents/refusals-and-envelope.md).

## Determinism, and why it constrains you

A world regenerates byte-for-byte from its seed plus its generation ledger:

```bash
worldloom build --seed 8128 --incident --replay ./corpus -f markdown --out ./again
diff -r ./corpus ./again
```

The second command makes **no model call at all** — every request is served from
the ledger. CI enforces this on every push. Two consequences for you:

- **Never introduce a clock, `random`, or a UUID.** Ledger keys are content
  addresses. `hash()` is randomised per process and is not one either; use
  `worldloom.ids.content_key`.
- **Prompt text is versioned data.** Editing a prompt in place silently changes
  what a seed means. Bump the version in `src/worldloom/narrative/prompts.py`.

`worldloom verify`, `worldloom migrate`, and the schema-bump policy are in
[docs/agents/determinism.md](docs/agents/determinism.md).

## Before you commit

```bash
pytest -q
worldloom validate retail-close             # the reference corpus must stay coherent
worldloom docs --check                      # the docs still describe the CLI
```

CI additionally regenerates a corpus from its ledger and byte-compares it, so
anything non-deterministic fails there even when tests pass locally. The
argument for the docs gate, and the wider determinism sweep, are in
[docs/agents/working-on-the-harness.md](docs/agents/working-on-the-harness.md).

---

## Where to read more

One topic per file, under `docs/agents/`. Read the file *when* its situation
applies:

| Read | When |
| --- | --- |
| [writing-responses.md](docs/agents/writing-responses.md) | Before step 3 — the request/response contract, the rules and why each exists, and `worldloom search` |
| [workspace.md](docs/agents/workspace.md) | Laying the corpus out as a permissioned drive, or making it untidy with `--noise` |
| [one-type-several-arguments.md](docs/agents/one-type-several-arguments.md) | Documents of one type all share a skeleton, or you want the `topology` / `series` / `diversity` readings |
| [twins-and-mutation.md](docs/agents/twins-and-mutation.md) | Attributing a measured delta to one recorded value (`twin`), or mutating recipes without building (`mutate`) |
| [refine-not-here.md](docs/agents/refine-not-here.md) | Tempted to close a rewrite loop over the corpus, or wiring the read-only MCP tools |
| [fleets.md](docs/agents/fleets.md) | Building many companies, or asked for a fleet — `mosaic`, `spaces`, `fleet`, `evolve` |
| [company-specification.md](docs/agents/company-specification.md) | The corpus must be a *particular* kind of business, needs more divisions, or needs an industry pack or the banking vertical |
| [company-attributes.md](docs/agents/company-attributes.md) | Reaching for `--facet`, `--messiness`, `--locale`, `--timeline`, or keeping a derived world with `pack export` |
| [paperwork.md](docs/agents/paperwork.md) | Hiring and review rounds, standing policies, or who signed what |
| [probe.md](docs/agents/probe.md) | Deriving the physics by Socratic drill-down instead of typing ranges |
| [estate-composition.md](docs/agents/estate-composition.md) | Growing a service landscape with `--estate`, or authoring one through `compose` |
| [conversations.md](docs/agents/conversations.md) | Recording who came to know what, when — `--conversations` |
| [actors.md](docs/agents/actors.md) | Driving the incident's records one validated decision at a time — `--actors` |
| [refusals-and-envelope.md](docs/agents/refusals-and-envelope.md) | A check looks excessive, or a caller must parse refusals mechanically |
| [determinism.md](docs/agents/determinism.md) | Proving byte-identity with `verify`, migrating a corpus, or bumping the schema version |
| [working-on-the-harness.md](docs/agents/working-on-the-harness.md) | Changing the harness itself — where things are, the docs gate, the determinism sweep, retrieval hardness |
