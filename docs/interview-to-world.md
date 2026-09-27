# From an interview to a world, and its evals

`worldloom interview` builds a whole enterprise world from one interview: the
industry and the company, its lines of business, its employees and their
seniority, the processes each line of business runs and the systems each step
touches, the documents every stage files at every level, how the company
changes over time, and what an employee at each level would ask an agent to do.
The world is then built, narrated under fact constraints and rendered with the
enterprise realism profile, and its eval cases are generated from the
interviewed processes, with every DAG node traced back to the answer that
produced it.

Nothing here is a new engine. Every answer lands in a format an existing seam
already consumes, and every stage after the interview is the seam that already
owns it. This page states what already connected, what did not, and how the
pipeline closes the gap.

## What already existed, and what did not connect

Worldloom had every authoring layer as its own refusable loop, and the build,
narration, render and enterprise-eval stages downstream of them. Surveyed at the
start of this work:

| Piece | What it gave | Connected to |
|---|---|---|
| Company specification (`company.resolve`, `/worldloom-company`) | One refusable description; composes a `packs.Pack` when it names the company | `build --spec`, `sdk.described` |
| LOB cascade (`lob.open`/`accept`/`resolve`, `/worldloom-lob`) | Roles, responsibilities, slot bindings | The pack's `lobs`; `Blueprint.lob` |
| Process cascade (`process`, `/worldloom-process`) | Steps, minted kinds, ordered slots, an `EpisodeSpec` | The pack's `episodes`; `AuthoredEpisode` |
| Doctypes (`doctypes.lint`, `/worldloom-doctypes`) | Document types linted against the compiler | The pack's `artifact_types` |
| Pack kernel and pack interview (`packkit.authoring`, `/worldloom-packs`) | One layer authored by a harness, refused with findings until clean | One pack of one kind |
| Probe (`/worldloom-probe`) | Physics ranges by drill-down | The company specification's `physics` |
| Timeline (`timeline.Timeline`, `review`) | Closes, incidents, departures, reorganisations, reviewed before running | Built worlds, from Python |
| Lore (`packs.PackCommitment`) | Commitments dated `effective_from`, with founding milestones on the timeline | The pack's `lore` |
| Realism profiles (`enterprise/v1`) | Long-form documents, revision files, connector records with text | Every new build |
| Connector projections (`connector_data`) | Jira, email, ServiceNow, Salesforce, SharePoint, Confluence, Drive records sharing fact, event and artifact ids | `enterprise-evals`, `evalrun` |
| Enterprise DAG grammar (`enterprise-dag@1`) | `fan_in`, `conditional`, `for_each` maps, transforms, predicate-bound searches | `enterprise-evals build`, `housekeeping`, `evalrun` |
| Narration (`narrate`, `DeterministicProvider`, `narrate loop`) | Prose under fact constraints | Any compiled world |
| Studio company interview | One whole project proposal per turn | Studio projects |
| Industry programme (`worldloom industry programme`) | LOBs and process lines derived from the process catalogue | Seated requests and cases per industry |

What did not connect:

- **No interview spanned the layers.** Each cascade and the pack interview
  author one layer; nothing asked the questions in order, carried what one
  layer settled into the next layer's context, or resumed an interrupted
  session from a transcript. Studio's interview proposes a whole project in one
  turn, with no per-layer refusal.
- **No seniority.** Roles had reporting lines and functions but no level, so
  nothing could say "a manager's weekly status" or tie an eval's difficulty to
  who asks it.
- **No systems per step.** A process's events were projected to Jira and email
  wholesale and to ServiceNow and Salesforce by keyword; nothing let an author
  say "the signing step leaves a Salesforce case and a SharePoint list item".
- **No review chain.** An authored episode's documents had an author and no
  reviewer or approver.
- **History and processes did not compose.** `timeline.review` treats a second
  episode in a period as a duplicate close, so authored processes could not ride
  a reviewed timeline; the build command ran them only as per-period rounds.
- **Documents had no period of their own on the records.** Every projected
  document carried the corpus's last period as `reporting_period`, so "the
  pipeline review for February" could not be told apart from March's.
- **A rendered file was named two ways.** The served emulator names a record by
  its title (`connector_emulator._canonical_record`) while a compiled row's
  snapshot names it by `fields.name` (`enterprise_rows.runtime_records`), and a
  rendered SharePoint or Drive file's `name` is its file name, so a search over
  rendered files graded `result_mismatch` even for the reference agent. The
  interview projection makes the two agree on its own records; the underlying
  disagreement belongs to the serving layer and is left for its owners.
- **Eval cases came from templates.** `enterprise-evals build` crosses builtin
  workflow templates with the connectors a world grounds; nothing generated a
  gold DAG from a company's own processes, or tied a DAG's shape to the level of
  the employee asking.

## The pipeline

```text
interviewee (harness over the exec seam, or a script)
   |  one question at a time; each answer refused with findings until clean
   v
company -> lobs -> employees -> processes:<lob>... -> documents -> timeline -> evals
   |
   v  assemble: one packs.Pack (lobs, episodes, artifact_types, lore, roles) + a resolution
build (enterprise realism) -> timeline, with each process run every period
   -> narrate under fact constraints -> render -> validate
   -> cases per level (enterprise-dag@1) -> reference proof -> measurements
```

```bash
worldloom interview run ./interview --script examples/interviews/kestrel-vale.json
worldloom interview status ./interview
worldloom interview build ./interview ./out
worldloom interview measure ./out
worldloom evalrun run ./out/evals/director -o ./runs/director
```

### The layers, and the seam each answer feeds

| Question | Answer | Refused by |
|---|---|---|
| `company` | A company specification with `identity.company_name` | `company.from_document`, `company.resolve` conflicts, a pack must be composed |
| `lobs` | At least two LOB seeds with their roles | `lob.lint_seed`, the LOB cascade's roles stage (`lob.accept`), one manager per shared post |
| `employees` | A level for every role: `ic`, `manager`, `director`, `executive` | Nobody above their manager; the root is an executive; every level held |
| `processes:<lob>` | Episode specs, the systems each step touches, the LOB's responsibilities and seats | `episodes.lint`, `lob.lint_lob`, the compiler's authorship contract (`documents._DOMAIN_AUTHORS`), every step names systems it can keep |
| `documents` | Document types and a review chain per planned type | `doctypes.lint` and `packs.lint` on the assembled pack; approval goes up; manager, director and executive each author one |
| `timeline` | Periods, incident periods, org changes, policies | `packs.lint`; `timeline.review` against the built roster; a policy must take effect inside the history |
| `evals` | Intents: asker, reads, branch, per-entity map, delivery | The level contract below; every read names a step and system the processes declared; one read per system entity; each level's tool catalogue fits one served case set |

The request a harness answers is `worldloom.world-interview/v1`: the question,
the context earlier answers settled, the last refused draft and every finding
against it, the attempt number, the instructions (prompt keys
`world.interview.*`) and the answer's JSON Schema. The reply carries `answer`,
or up to five `questions` for the operator, which end the loop. The bundled
harness adapters recognise the schema, so `--harness` works as it does for
`narrate loop`.

### Deterministic offline, live for real use

`--script` runs a scripted interviewee: fixture answers per question, one per
attempt. `examples/interviews/kestrel-vale.json` answers every question twice,
first with an answer that layer refuses on purpose, then with a clean one, so a
scripted run exercises the refusal loop on every layer. Narration offline uses
the deterministic writer; `--narrate-exec` or `--narrate-harness` puts a live
writer through `narrate loop`'s contract instead.

### Resumable

Every round is appended to `transcript.jsonl` as it happens. Opening a
directory replays its accepted answers through the lints again (a transcript
that no longer lints is refused, never trusted) and restores the question in
progress with its last draft, findings and attempt count. `--stop-after N`
pauses on purpose; a spent round budget stops with the findings; running again
continues where it stopped, and the result is byte-identical to an interview
that was never interrupted. Lints and builds inside the interview run under
`registries.scoped()`, so an answer is judged the same in a fresh process as in
one that has built other companies.

## Change over time

The timeline answer becomes the reviewed history: each period's close (with
its incident when one was scheduled), then that period's org changes, with
every interviewed process run once per period after the close. Policies are
pack lore dated `effective_from`: each mints a milestone event and fact at its
date, which the projected systems record at that date, and a fact that cites
the commitment hands it to the writer as background. One gap remains, stated
rather than hidden: a lore *terminology* note reaches every narration request
whatever its date, because `narrative.compiler` does not yet gate terminology
by `effective_from`. Every projected record of a process step or a document
carries its own `period`, so a read at a stated period finds that period's
record and no other.

## Evals from the interviewed world

Each intent becomes one `PlannedEnterpriseQuery` in `enterprise-dag@1`, the
structure every other enterprise case uses, and passes through
`materialize_corpus` (under `strict_sources`), `validate_corpus`,
`compile_rows` and `evalrun.cases_from_corpus` unchanged. Every read is a
predicate-bound search (`bind="predicate"`) whose rule the request states: a
step's records for a period, or a document type for a period, optionally only
where the document carries a revision chain. The source's minimum is exactly
how many records match, so a case never asks for evidence the world lacks.

| Level | Shape | DAG |
|---|---|---|
| Individual contributor | `interview_ic_lookup` | One search on one system, the write, its readback |
| Manager | `interview_manager_fan_in` | Parallel searches on two or more systems, collected, written, verified |
| Director | `interview_director_conditional` | A document read at a period (revision-aware when asked) beside a system read; which write runs depends on a read's count; only the write that ran is verified |
| Executive | `interview_executive_map` | Searches across two or more LOBs, each mapped record by record (`for_each`), collected, projected to identifiers, deduplicated, written, verified |

Provenance: `interview_provenance` in each case's dimensions maps every DAG
node to the question whose answer produced it (a step read to
`processes:<lob>` and the system that answer declared, a document read to
`documents`, the transforms and writes to `evals`), and `provenance.jsonl`
beside each level's case set repeats it per case.

`interview build` writes one enterprise case set per level
(`evals/<level>/`), because one served case set admits a bounded tool
catalogue and a company's systems together exceed it; the evals lint keeps each
level inside the budget. It then runs the reference agent over every case and
refuses the build if any case fails: a case the reference cannot pass is a
defect found before an agent is evaluated on it. The gold plans are expressed
in the same grammar and row format as every other enterprise case, so a
solvability check over those rows applies to these unchanged.

## Measured: the scripted interview

One run of `examples/interviews/kestrel-vale.json` at seed 8128, byte-identical
across processes:

| Measure | Value |
|---|---|
| Questions / rounds | 9 questions, 18 rounds (every first answer refused, every second accepted) |
| LOBs / processes / steps | 3 / 3 / 8 |
| Employees | 25 people; 12 levelled roles, 3 at each level; 13 engine posts outside the ladder |
| Systems touched | Confluence, Drive, Jira, Outlook, Salesforce, ServiceNow, SharePoint, Slack |
| Records per system | Confluence 83, SharePoint 65, Drive 57, email 54, Jira 54, ServiceNow 16, Slack 12, Salesforce 10, Outlook 8 |
| Records carrying interview fields | 228 |
| Documents | 75 intents, 284 rendered files; interviewed types 4 each (one per period) at manager, director and executive level |
| Revisions | 132 revision files; 52 SharePoint and 52 Drive records with a revision chain |
| Timeline | 4 periods, 54 events (32 process steps, 3 policy milestones), 1 incident period, 1 departure, 2 policies |
| Facts | 2,457 |
| Cases | 12: 3 per level; reference agent 12 of 12 |
| DAGs | IC depth 4 width 1 (4 nodes); manager depth 4 width 2 to 3 (5 to 6 nodes); director depth 4 width 2, 4 conditional nodes each; executive depth 7 width 3, 3 `for_each` maps each (11 nodes) |
| Tools per case set | IC 58, manager 91, director 60, executive 84, against 94 admitted |

Reproduce with `worldloom interview build` and `worldloom interview measure`.

## Where to go next

- `/worldloom-interview` is the skill that drives this loop.
- Every layer's own skill (`/worldloom-company`, `/worldloom-lob`,
  `/worldloom-process`, `/worldloom-doctypes`) is where to read what that
  layer's answer may say.
- [Eval execution](eval-execution.md) for grading an agent over the case sets.
