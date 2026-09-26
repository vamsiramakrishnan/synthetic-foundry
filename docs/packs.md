# Packs: every layer as data

A **pack** is one JSON document that supplies one layer of the product: how an
industry talks, the prompts a harness reads, the numeric defaults a run follows,
a company, a connector, a line of business, a document type, a presentation
profile or the policy of an agent under test. Every kind of pack is found, layered, checked, uploaded and authored by
the same mechanism, `worldloom.packkit`. A new kind is a registration and a
default file; it needs no new loader.

```bash
worldloom pack kinds                          # what can be a pack, and what each controls
worldloom pack list industry                  # every visible industry pack and where it comes from
worldloom pack show industry:banking          # the resolved pack: merged body, digest, chain, findings
worldloom pack lint hospital.json             # resolve and lint without storing
worldloom pack install hospital.json          # upload: lint, refuse with findings, or store by name
worldloom pack author industry --name hospital \
  --message "An acute hospital network" --harness-command 'python adapter.py'
worldloom --pack industry:hospital build --seed 8128 --out ./corpus
```

## The envelope

```json
{
  "schema": "worldloom.pack/v1",
  "kind": "industry",
  "name": "hospital",
  "title": "Acute hospital network",
  "extends": ["industry:healthcare"],
  "body": {"terms": {"site": "hospital", "customer": "patient"}}
}
```

A pack states only what differs. Its body is merged onto its `extends` chain,
and a pack with no `extends` layers on its kind's default (`industry:default`,
`prompts:default`, `policy:default`). Mappings merge deeply. Lists replace,
unless the kind names a key to merge them by (a company's `units` merge by
`key`). `null` removes a key. The merged body is validated against the kind's
model. The digest covers the kind, the name and that merged body, so
`industry:hospital@<digest>` names exactly one resolved pack. A pinned reference
refuses a pack whose content has changed.

## Where packs are found

Packs are searched in this order. A higher entry shadows the same `kind:name`
lower down:

1. roots the caller names: `--pack-root`, a Studio workspace's `packs/`;
2. each directory in `WORLDLOOM_PACK_PATH`;
3. the user's directory, `$WORLDLOOM_HOME/packs` (by default `~/.worldloom/packs`);
4. the packs shipped in `worldloom/_data/packs`.

Every root has the same layout: `<kind>/<name>.json`, or a directory
`<kind>/<name>/` holding `pack.json` plus body fragments merged in file-name
order. A pack that extends its own name reaches the pack it shadows. That is how
a user adjusts a shipped industry: write `industry/banking.json` with
`"extends": ["industry:banking"]` and change one term.

A pack named after its kind's default (`prompts/default.json` in the user's
root) customises every build under that root. It layers on the shipped default
it shadows, so it states only what it changes. It is linted against the shipped
default, recorded in each recipe it affects, and counted in a Studio snapshot's
identity. A Studio workspace does not accept one: a project changes through the
packs it chooses by name.

A connector pack is stricter about shadowing, because a shipped connector's
definition is part of every corpus that uses it. A connector pack with a new name
(a `zendesk` definition) is visible from any root, and the emulator, the served
surface and the enterprise specs all use it. A connector pack named like a
shipped connector replaces that connector only in two cases: when it is put in
force explicitly (`--pack connector:jira`), or when it lies in a root the run
names (`--pack-root`, or a Studio workspace). A copy in `~/.worldloom/packs` or
`WORLDLOOM_PACK_PATH` is ignored.

## Industry packs: colloquialising the product

An industry pack holds:

- the industry's words (`terms`);
- the phrases that recognise the industry in a company description (`aliases`);
- the engine it rides;
- an example company;
- the prompt and policy keys it overrides.

Every template in the product reaches a word through `{{term:site}}`. The case
and the plural are derived: `{{term:Site}}` gives `Branch`, `{{term:sites}}`
gives `branches`, and `{{term:SITES}}` gives `BRANCHES`. A pack still states an
irregular plural as a term of its own.

The default industry pack holds the words the product used before packs existed.
A build that puts no industry pack in force is therefore byte-identical to one
made before this mechanism.

## Prompts and policy

Every prompt, instruction and templated sentence is a key in `prompts:default`.
Every default that a build, compile or evaluation follows is a key in
`policy:default`. Code reads them with `packkit.text(key, **values)` and
`packkit.policy(key)`. An industry pack's own `prompts` and `policy` override
them for that industry only.

Overrides are linted:

- an unknown key is refused, with the nearby keys named;
- a prompt that introduces a `{placeholder}` its caller does not fill is refused;
- a `{{term:x}}` that names no term is refused;
- a policy value of the wrong type is refused.

`text` fills only the placeholders it is given and interprets nothing else, so a
prompt may contain JSON or a `{{fact:ID}}` example without escaping. A few keys,
such as a workflow's `prompt_template`, are passed by their callers to
`str.format`. `prompts:default` lists these under `formatted`, and an override
of one must parse as a format string: a literal brace is written `{{` or `}}`.
Term values may not contain braces. Numeric policy stays positive where the
shipped value is positive. An industry pack cannot change a serving limit
(`connectors.serving.*`); that belongs to a policy pack the operator chooses.

## Uploading and authoring

A pack reaches a root in one of two ways, and both run the same checks.

**Upload.** `worldloom pack install FILE [--into ROOT]`, or `POST /api/packs` in
Studio. The pack is resolved (so `extends` must name packs that exist), linted
by its kind, and then either refused with every finding or stored as
`<root>/<kind>/<name>.json`.

**Harness interview.** `worldloom pack author KIND --message ... --harness-command ...`
runs the refusal cycle:

1. Worldloom sends a bounded request. It carries the kind's model as a JSON
   Schema, the shipped default as an example, the visible packs of that kind,
   the operator's message, the current draft and the last refusal's findings.
2. The harness replies with questions or a proposal.
3. A proposal that fails the lint comes back with its findings, until it passes
   or the round budget (`policy: pack.interview.max_rounds`) runs out.
4. Questions stop the loop, because the operator answers them, not the harness.

`worldloom pack interview request` and `worldloom pack interview accept` do the
same exchange through files, for a harness you drive yourself. Only the accepted
envelope is stored. The conversation never is.

## Agent packs

An `agent` pack is the policy of the agent under test in `worldloom evalrun
run` and `worldloom evalrun plan`. A run used to measure a harness together with
whatever instructions it happened to carry, so two runs of one harness under
different instructions looked like one agent. As a pack, a policy is
content-addressed: each variant has its own digest, a harness can propose one
and be refused, and every run records which one it ran.

A policy holds:

- `system`: the agent's standing instruction;
- `turn_rules` and `plan_rules`: overlays on the shipped `evalrun.turn.rule.*`
  and `evalrun.plan.rule.*`, keyed by the rule's suffix. `01` replaces the
  shipped rule 01, a new key such as `10` adds a rule, and an empty string
  removes a shipped rule. Between agent packs, `null` removes a rule a parent
  added;
- `tools`: advice per tool, keyed by the tool's catalog name
  (`servicenow.get_record`), as a `description` and a list of `hints`;
- `planning`: how the agent should form a plan;
- `skills`: named procedures the agent can follow, as strings;
- `files`: real skills, as a tree of files in the layout coding harnesses use
  (see below);
- `max_turns`: the turn budget, when it differs from the policy default.

Rule `02` of each list is locked. It states the reply shapes (`call`, `ask`
and `answer` for a turn, `plan` for a planner), and the harness parses exactly
those shapes. A policy that could restate them would turn a policy variant into
a protocol variant, whose failures would read as the agent's. The lint refuses
an override or removal of a locked rule, and so does the overlay at run time.
It also refuses any text that writes a reply shape out as JSON. Policy text is
sent verbatim, so a `{placeholder}` or a `{{term:...}}` token is refused too,
and the total text is capped by the policy `evalrun.agent_pack.max_chars`.

```bash
worldloom evalrun run ./cases -o ./runs/careful --exec 'python agent.py' --agent-pack agent:careful
worldloom evalrun plan ./cases -o ./runs/careful-plan --harness codex --agent-pack ./careful.json
worldloom pack author agent --name careful \
  --message "A careful agent that reads before it writes" --harness-command 'python adapter.py'
```

`--agent-pack` takes `agent:name[@digest]` or a pack file, and it needs
`--exec` or `--harness`: the reference, lazy and scripted agents never read a
policy. Under a policy the `worldloom.evalrun-turn/v2` document gains an
`agent` block (`ref`, `digest`, `system`, `planning`, `skills`). Its
`instructions` are the overlaid rules, and each advised tool gains
`description` and `hints`. Without a policy the document is unchanged, byte for
byte. The plan document gains the same fields. The bundled `--harness` adapter
puts the `system` text ahead of its role prompt, between markers naming the
policy. The agent's name carries the policy
(`exec:python+agent:careful@<digest[:12]>`), and `run.json` records
`agent_pack` as `{ref, digest, chain}`. Advice for a tool that no connector
serves is not an error: it is noted once in each case's notes as a finding
about the policy.

### The skill tree

`files` maps relative paths to text. Every path lies under `skills/`:

- `skills/<name>/SKILL.md`: frontmatter with `name` (equal to the directory)
  and a one-line `description` saying when the skill applies, then the
  procedure;
- `skills/<name>/references/*.md`: material the skill points to;
- `skills/<name>/scripts/*.py` and `skills/<name>/scripts/*.sh`: code the
  skill runs.

The lint (`evalrun.policy.lint_files`) refuses a path that is absolute,
contains `..`, a backslash or a segment starting with `.`, or lies outside
that layout; a skill directory without a SKILL.md; frontmatter that is not
`name` and `description` on one line each, or whose name does not match its
directory; a Python script that does not parse; an empty shell script; a file
over `evalrun.agent_pack.max_file_bytes` or a tree over
`evalrun.agent_pack.max_tree_bytes`; and any line that looks like a
credential (a private key block, a known token prefix, or a literal assigned
to a secret-looking name, by the same name test the grader redacts commands
with). The finding names the file and the line and never repeats the value.
The lint parses scripts; it never runs one. String `skills` stay valid beside
the tree, but one name may not be both.

The tree is also how the whole policy is presented as files. `tree(body)`
returns `policy.json` (every field but `files`, as sorted JSON with a
two-space indent) plus the skill tree, and `from_tree` reads that back. This
is the `agent` kind's tree codec (`PackKind.to_tree` and `from_tree`).

**Delivery.** `ExecAgent` writes the tree once into a content-addressed
directory (`$WORLDLOOM_HOME/cache/agent-skills/<digest>/skills`, written
beside its final name and renamed into place) and the turn document's
`agent` block gains `skills_dir` and `skill_index`, a list of
`{name, description, path}`. The index is what the agent reads up front; a
body is opened only when its description fits the step. A policy without
`files` adds neither key, so its turn document is unchanged. The bundled
`--harness` adapters put the index ahead of the role prompt. `codex` runs in
its read-only sandbox, which can read files, so it gets the directory and
opens a SKILL.md itself. `claude` runs the evalrun seams with no tools at
all, so it could neither load a skill natively nor read one from disk, and
granting it file or skill tools would also let it read the cases' expected
answers; its prompt therefore carries each SKILL.md in full after the index,
with references and scripts named by path. The plan document does not carry
the tree.

**Revising by diff.** Because the kind has a tree codec, the pack interview
hands a harness the draft as `draft_tree`, and a proposal may carry `diff`, a
unified diff against that tree, instead of `body`. The diff is applied
strictly by `packkit.diffs`: `a/` and `b/` prefixes, `/dev/null` to create or
delete a file, and every hunk must match the draft exactly where its header
says, with no fuzz. A patch that does not apply comes back as a finding such
as `diff: hunk 2 of skills/verify/SKILL.md does not apply at line 14:
expected ..., found ...`, and so does a patch whose result the lint refuses.
A body proposal works as before.

**Boundary.** Generated code lives only in the agent pack's `skills/` tree.
`from_tree` refuses any path other than `policy.json` and `skills/...` before
reading anything, so nothing a proposer writes can name another place, and
the improvement loop writes only under its output directory and the pack root
it installs candidates into.

```bash
worldloom pack tree agent:careful -o ./careful-tree
worldloom pack from-tree ./careful-tree --name careful-2 --into ./packs
worldloom pack from-tree ./.claude/skills --name native --base agent:baseline
worldloom pack diff agent:careful agent:careful-2 --root ./packs
```

`pack tree` writes a pack's tree into a new or empty directory. `pack
from-tree` reads one back, from a tree with `policy.json` or from a bare
skills directory of `<name>/SKILL.md` (whose `policy.json` then comes from
`--base`), lints it and installs it. `pack diff` prints the unified diff
between two packs of a kind with a tree codec.

A harness proposes a policy through the same interview as any other pack:
`worldloom pack author agent` refuses a proposal with its findings until it
lints clean. `agent:baseline` ships as the example: today's rules, no advice,
and a neutral standing instruction.

**Proposer policies.** The harness that proposes revisions in `worldloom
evalrun improve` is itself governed by an `agent` pack, named with
`--proposer-pack`; `agent:proposer-baseline` ships and restates the
proposer's current instructions. A proposer reads only `system`, `planning`,
`skills` and the skill tree: its interview request gains the same `agent`
block a turn document does, the bundled adapters fence it ahead of the
interview role, and each authoring round records its reference and digest.
`worldloom evalrun improve-proposer` revises such a pack and keeps a revision
only when the agents it improves gain more on held-out cases (see
[Self-improvement](self-improvement.md#recursion-improving-the-improver)).

## Replay

A pack that changes what a seed generates must replay without its file.
`packkit.recorded()` returns the reference, digest, chain and merged body of every
non-default pack in force, and a recipe stores it. `packkit.use_recorded(...)`
puts those packs back in force from the stored bodies, and refuses a body that
no longer matches its digest. A default build records nothing, so its recipe is
unchanged.

## Kinds

| Kind | Body | Lint | Default |
| --- | --- | --- | --- |
| `industry` | `IndustryPack`: terms, aliases, engine, example, prompt and policy overrides | term keys, placeholders, known prompt and policy keys, engine | `industry:default` |
| `prompts` | `texts: {key: template}` | known keys, placeholders kept, known terms | `prompts:default` |
| `policy` | `values: {key: value}` | known keys, shipped types | `policy:default` |
| `company` | `packs.Pack` | `packs.lint` | none |
| `connector` | `ConnectorDefinition` | stored name matches the definition | none |
| `lob` | `lob.Lob` | `lob.lint_lob` | none |
| `doctype` | `doctypes.DocumentType` | `doctypes.lint` | none |
| `presentation` | `presentation.PresentationSeed` | `presentation.review` | none |
| `agent` | `evalrun.policy.AgentPolicy`: the agent under test's standing instruction, rule overlays, tool advice, skills, skill tree | `evalrun.policy.lint_policy`: non-empty system, key syntax, locked reply-shape rules, verbatim text, size cap, the skill tree's paths, frontmatter, scripts and secrets | none (`agent:baseline` ships as an example) |

To register a kind, call `packkit.register_kind(PackKind(name=..., model=...,
lint=..., about=...))`. If the kind has a default, ship it as
`_data/packs/<kind>/default/`. A kind that can be presented as files also
passes `to_tree` and `from_tree`; its interview then offers `draft_tree` and
takes a `diff`.
