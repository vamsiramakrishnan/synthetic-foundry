"""Worldloom against Gemini Enterprise, through Eval Studio.

`GoogleCloudPlatform/gemini-enterprise-eval-studio` solves the part of this
problem that is genuinely hard and entirely uninteresting to build twice:
*reaching* a Gemini Enterprise instance. Workforce Identity Federation, OIDC
and SAML, token refresh, the `streamAssist` stream and its latency telemetry
(TTFT, TTFA, TTLT) are all there and work. Nothing in this package tries to
replace any of it.

What Eval Studio does not do is the two things either side of that call, and
both of them are Worldloom's.

**It does not populate the index.** Eval Studio selects data stores that
already exist in the customer's project; it has no ingestion path at all. Point
it at a company's real drive and you are asking questions whose answers nobody
holds. That is the failure mode this engine exists to remove: a corpus whose
every answer is derived from a canonical fact. `datastore` writes that corpus
as Discovery Engine documents, permissions included, which is the only way the
golden answers mean anything.

**It does not observe the run.** Its stream parser keeps
`answer.replies[].groundedContent.content.text` and discards the rest, so tool
calls and grounding metadata never leave the browser. `connector_trace`
grades eighteen assertion kinds and there is no wire to feed it. Every score
that comes back here is a judgement about a final answer, and this package says
so rather than implying a trace was checked.

Between those two, the fit is nearly exact and worth stating plainly: Eval
Studio reads a CSV of `query,golden`, and an `EvaluationCase` already carries
`question` and `expected_answer`. Two columns is also the whole of the wire.
Fact ids, required and distractor artifacts, the temporal cutoff, the asker and
the occasion — everything that makes a case checkable rather than merely
answerable — has no column. So `cases` does not simply dump the pair:

- It **shards by `evaluation_type`**, because Eval Studio applies one
  `autoRaterInstruction` to a whole run, and one similarity rubric grades an
  abstention and a citation wrongly in opposite directions. A model that
  confidently invents a February close delay scores well against
  "The corpus contains no February 2026 close delay" on semantic similarity,
  which is exactly backwards. `RUBRICS` gives each shape a grader that matches
  what the shape claims.
- It **respects the hundred-row cap**, which is not a setting: Eval Studio's
  CSV reader truncates with `results.data.slice(0, 100)`. A thousand-case set
  handed over whole silently becomes its first hundred rows, and the run
  reports a clean pass over the nine hundred it never sent.
- It writes the **provenance beside the pair**, and `results` joins it back,
  because Eval Studio builds its output rows from scratch and drops every extra
  column. Without the rejoin a result set cannot be sliced by the structure the
  corpus knows and the CSV could not carry.

Nothing here draws, reads a clock, or invents a value. Every document, ACL and
answer is derived from the manifest, the roster, the access policies and the
fact ledger, and where a corpus does not know something this writes nothing
rather than a plausible fiction -- the rule `workspace` already sets for the
same artifacts.
"""

from __future__ import annotations

from .cases import COLUMNS, ROW_LIMIT, RUBRICS, Shard, rows, shards
from .datastore import MEDIA_TYPES, UNSUPPORTED_MEDIA, Export, documents
from .results import Scorecard, Slice, read_results, score

__all__ = [
    # Cases out.
    "COLUMNS",
    "ROW_LIMIT",
    "RUBRICS",
    "Shard",
    "rows",
    "shards",
    # Corpus out.
    "MEDIA_TYPES",
    "UNSUPPORTED_MEDIA",
    "Export",
    "documents",
    # Results back.
    "Scorecard",
    "Slice",
    "read_results",
    "score",
]
