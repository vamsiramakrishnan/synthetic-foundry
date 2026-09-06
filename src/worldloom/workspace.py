"""The corpus as a shared drive, rather than as a folder of numbered files.

A corpus exports to `artifacts/art-0001-delegation-of-authority.md` — one flat
directory, filenames carrying ids, and every file identical to the filesystem.
That is exactly right for the harness, which reads the manifest and never looks
at a path. It is wrong for the thing the corpus is *for*.

An enterprise assistant is pointed at a Drive or a SharePoint, and what it
indexes is not only content. It is the folder a document sits in, the title
somebody typed, who owns it, who it is shared with, when it was last touched,
and the fact that `Expense Policy` and `Expense Policy (superseded 2023)` are
two files on one shelf. Path and title carry a large share of retrieval signal,
and permission behaviour — does the assistant surface a document to somebody who
should not see it — is where these products most often fail interestingly.

This corpus already *knows* all of that. Every artifact carries an author, an
approver, an access policy with named members, a created date derived from its
own facts, and a supersession edge. None of it reached the filesystem: 293 files
in one folder with identical permissions.

``layout`` is that knowledge as a tree, and ``write`` puts it on disk beside a
machine-readable permission table a connector can load. Written to a *separate*
root rather than reorganising `artifacts/`, so nothing the harness reads moves
and a corpus exported before this existed is untouched.

**Nothing here invents.** Every folder, title, owner and reader is derived from
the manifest, the roster and the access policies. Where the corpus does not know
something — a last-modified distinct from a created date, a share with somebody
outside the company — this writes nothing rather than a plausible fiction.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["NOISE", "Placed", "domain_for", "email_for", "layout", "write"]


#: How untidy the drive is, and how many extra files each level puts on it, as
#: a fraction of the real ones.
#:
#: This is *filesystem* noise and deliberately not the same thing as
#: ``worldloom.messiness``, which is content noise — a page nobody updated, two
#: documents disagreeing, an author who left. Both are real and they fail
#: differently: a stale page is wrong, a duplicate is not wrong at all, it is
#: merely there twice. A corpus wanting a realistic archive wants both.
#:
#: Every extra file is a *copy of real corpus content*, never invented text. A
#: drive's junk is not fabricated documents; it is the same documents saved
#: again in the wrong place under the wrong name, and that is exactly what makes
#: it hard — a retriever cannot tell the copy from the original by reading it.
NOISE: dict[str, float] = {"none": 0.0, "lived_in": 0.12, "neglected": 0.35}

#: The shapes junk takes, in the order a round applies them.
#:
#: Ordered and closed, because the *kind* of junk is recorded per file and a
#: benchmark that could not tell a duplicate from a misfiling could not score
#: itself. Every one of these is something a real drive has and none of them is
#: an error: somebody duplicated a file, somebody dragged one into the wrong
#: folder, somebody saved a version with their name on it, somebody archived a
#: copy and left the original.
_NOISE_KINDS: tuple[str, ...] = ("copy", "misfiled", "versioned", "archived")


#: Which shelf a document type sits on, and the folder it lands in.
#:
#: Grouped the way a company's own drive is: by the function that owns the
#: paperwork, not by the engine that generated it. A reader looking for the
#: expense policy looks in Policies, and one looking for March's numbers looks
#: in Finance — neither of them knows or cares that both came out of the same
#: Python module.
#:
#: A type this table does not name lands in ``Other``, and that is deliberately
#: visible rather than defaulted into Finance: an unfiled document is what a
#: real drive has too, and hiding it in a plausible folder would make the tree
#: look tidier than the company is.
SHELVES: dict[str, str] = {
    # -- what a close produces ------------------------------------------
    "close_calendar": "Finance/Close",
    "finance_workbook": "Finance/Close",
    "cfo_variance_memo": "Finance/Close",
    "unit_close_commentary": "Finance/Close/Divisional",
    "executive_summary": "Executive",
    "peak_trading_review": "Executive",
    "meeting_minutes": "Finance/Close",
    # -- what a company answers to --------------------------------------
    "audit_committee_pack": "Executive/Board and Committees",
    "board_risk_committee_summary": "Executive/Board and Committees",
    "internal_audit_review": "Executive/Board and Committees",
    "sponsor_pack": "Executive/Board and Committees",
    "member_report": "Executive/Board and Committees",
    "ministerial_brief": "Executive/Board and Committees",
    # -- when something breaks ------------------------------------------
    "servicenow_incident": "Technology/Incidents",
    "incident_rca": "Technology/Incidents",
    "jira_issues": "Technology/Incidents",
    "confluence_page": "Technology/Knowledge Base",
    "knowledge_article": "Technology/Knowledge Base",
    "service_impact_assessment": "Technology/Incidents",
    "remediation_scope_review": "Technology/Change",
    "estate_change_notice": "Technology/Change",
    "working_note": "Finance/Close/Working Papers",
    "email_thread": "Correspondence",
    # -- the rules ------------------------------------------------------
    "delegation_of_authority": "Policies",
    "code_of_conduct": "Policies",
    "business_continuity_policy": "Policies",
    "expense_policy": "Policies",
    "travel_policy": "Policies",
    "leave_policy": "Policies",
    "remote_work_policy": "Policies",
    "information_security_policy": "Policies",
    "data_retention_policy": "Policies",
    "procurement_policy": "Policies",
    # -- people ---------------------------------------------------------
    "job_requisition": "People/Recruitment",
    "offer_letter": "People/Recruitment",
    "onboarding_checklist": "People/Onboarding",
    "performance_review": "People/Performance",
    "one_to_one_note": "People/Performance",
    "personnel_notice": "People",
    "routine_notice": "Correspondence",
    # -- the other verticals --------------------------------------------
    "capital_return": "Finance/Regulatory",
    "rwa_working_paper": "Finance/Regulatory/Working Papers",
    # Not Regulatory: the divisional pack reports how the bank traded, not what
    # it told the regulator, and a reader looking for branch numbers is not the
    # reader looking for the return.
    "divisional_performance_pack": "Finance/Performance",
    "second_line_challenge_memo": "Risk",
    "reserve_triangle_workbook": "Actuarial",
    "claims_emergence_note": "Actuarial/Working Papers",
    "actuarial_valuation_report": "Actuarial",
    "margin_decision_memo": "Finance",
    "purchase_order": "Procurement/Orders",
    "goods_receipt_note": "Procurement/Receipting",
    "supplier_invoice": "Procurement/Invoices",
    "match_exception_report": "Procurement/Exceptions",
    "payment_approval_memo": "Procurement/Exceptions",
    "vendor_master_change": "Procurement/Vendor Master",
    # Shelved with the orders rather than under Finance: it is the order book's
    # own position — what has been committed and not yet received — and the
    # person who goes looking for it is the person who raised the orders.
    "spend_and_commitment_workbook": "Procurement/Orders",
}

#: Types filed under the period they report on, inside their shelf.
#:
#: The distinction is not decorative and a real drive makes it too: a close pack
#: lives in a month's folder because there is one per month and nobody wants
#: sixty of them in a list, while a policy lives at the top of its shelf because
#: there is one of it and it is *current* until it is not. Filing a policy under
#: a month would say the wrong thing about it — that it expired with the month.
PERIODIC: frozenset[str] = frozenset({
    "close_calendar", "finance_workbook", "cfo_variance_memo",
    "unit_close_commentary", "executive_summary", "meeting_minutes",
    "working_note", "email_thread", "peak_trading_review",
    "audit_committee_pack", "sponsor_pack", "member_report",
    "ministerial_brief", "board_risk_committee_summary",
    "internal_audit_review", "capital_return", "rwa_working_paper",
    "divisional_performance_pack",
    "second_line_challenge_memo", "reserve_triangle_workbook",
    "claims_emergence_note", "actuarial_valuation_report",
    "margin_decision_memo", "purchase_order", "goods_receipt_note",
    "supplier_invoice", "match_exception_report", "payment_approval_memo",
    "spend_and_commitment_workbook",
    "job_requisition", "offer_letter", "onboarding_checklist",
    "performance_review", "one_to_one_note",
})

_SLUG = re.compile(r"[^A-Za-z0-9 ()&,'\-]+")
_SPACES = re.compile(r"\s+")

#: How long a filename gets before it is cut at a word boundary.
#:
#: Not a filesystem limit — those are far higher — but a *human* one. An
#: artifact's title is whatever the compiler put there, and for a communications
#: bundle that is the whole event summary: "Email thread Service operations
#: opened incident INC0035338 at priority P2 against inventory-valuation". No
#: person names a file that. Seventy is roughly where a real filename stops
#: being a name and starts being a sentence.
_TITLE_CAP = 70


def _clean(text: str) -> str:
    """*text*, as a filename a person would have typed.

    Accents folded rather than stripped, because a corpus in a German locale
    names its documents in German and `Rückstellung` becoming `Rckstellung` is a
    filename nobody typed. Punctuation a filesystem dislikes goes; parentheses,
    ampersands, commas, apostrophes and hyphens stay, because they are what a
    real filename has in it.
    """
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    tidy = _SPACES.sub(" ", _SLUG.sub("", ascii_only)).strip()
    if len(tidy) > _TITLE_CAP:
        # Cut at the last word boundary inside the cap, so a truncated name is
        # still readable rather than sliced mid-word. No ellipsis: a filename
        # ending in "..." reads as a placeholder somebody meant to finish.
        head = tidy[:_TITLE_CAP].rsplit(" ", 1)[0]
        tidy = head or tidy[:_TITLE_CAP]
    return tidy or "Untitled"


def domain_for(company_name: str) -> str:
    """A mail domain from the company's own name.

    Derived rather than stored, because no pack has ever declared one, and an
    address is what an access list is expressed in everywhere this corpus would
    be loaded. A domain is the smallest invention that makes an ACL usable, and
    it is a function of a name the corpus already has.
    """
    words = [w for w in _clean(company_name).lower().split() if w not in
             {"group", "holdings", "holding", "limited", "ltd", "plc", "the"}]
    stem = "".join(words) or "company"
    return f"{stem[:24]}.example"


def email_for(person: Any, domain: str) -> str:
    """``first.last@domain``, with a numeric suffix only where it must be.

    Uniqueness is the caller's business (``_addresses`` below) rather than this
    function's, because two people called Jordan Lee is a fact about the roster
    and disambiguating them needs the whole of it.
    """
    parts = [p for p in _clean(person.name).lower().split() if p]
    stem = ".".join(parts[:2]) if len(parts) > 1 else (parts[0] if parts else "person")
    return f"{stem}@{domain}"


def _addresses(people: Iterable[Any], domain: str) -> dict[str, str]:
    """One address per person, collisions broken by roster order.

    ``jordan.lee`` then ``jordan.lee2``, which is what a mail administrator
    actually does — and stable, because the roster order is.
    """
    out: dict[str, str] = {}
    taken: dict[str, int] = {}
    for person in people:
        base = email_for(person, domain)
        seen = taken.get(base, 0) + 1
        taken[base] = seen
        out[person.id] = base if seen == 1 else base.replace("@", f"{seen}@", 1)
    return out


@dataclass(frozen=True)
class Placed:
    """One file, where it goes and who may open it."""

    artifact_id: str
    path: str
    """Relative to the workspace root, folders included."""
    title: str
    owner: str
    """The author's address. A drive has one owner per file, and it is whoever
    created it — an approver is a reader with a signature, not an owner."""
    readers: tuple[str, ...]
    """Every address permitted, the owner included. Empty means *everyone* —
    which is what an unrestricted `All staff` policy says, and writing out four
    hundred and sixty addresses to say it would be a worse answer than the
    empty list a real ACL uses for "inherit from the drive"."""
    policy: str
    created: str
    superseded_by: str | None = None
    """The path of the file that replaced this one, when one did."""
    noise: str | None = None
    """What kind of junk this file is, or ``None`` for a real one.

    Recorded rather than hidden, and that is the whole difference between this
    and simply making a mess. A benchmark scored against a drive it cannot
    account for is a benchmark that cannot tell "the assistant found the wrong
    copy" from "the assistant was wrong", and those are different failures. The
    junk is indistinguishable *by reading it* — which is the point — and
    perfectly distinguishable in the manifest.
    """
    copy_of: str | None = None
    """The path this one duplicates, when it duplicates one."""


def _folder(artifact: Any, period: str | None) -> str:
    shelf = SHELVES.get(artifact.artifact_type, "Other")
    if period and artifact.artifact_type in PERIODIC:
        return f"{shelf}/{period}"
    return shelf


def _extension(path: str) -> str:
    suffix = Path(path).suffix
    return suffix or ".md"


def layout(world: Any) -> tuple[Placed, ...]:
    """Where every artifact goes, and who may open it. Writes nothing.

    Separated from ``write`` so the placement can be inspected, diffed and
    tested without a filesystem — and so a caller who wants the tree in some
    other system (a real Drive, a SharePoint) has the answer without having to
    reverse it out of a directory.
    """
    domain = domain_for(world.company.name)
    people = {p.id: p for p in world.people}
    address = _addresses(world.people, domain)
    policies = {p.id: p for p in world._access_policies}
    facts = {f.id: f for f in world.facts}

    # `supersedes` runs backwards — the *new* document names the old one — and
    # a shelf reads forwards, so the edge is inverted once here rather than
    # searched per file.
    replaced_by = {
        artifact.supersedes: artifact.id
        for artifact in world.artifacts if artifact.supersedes
    }

    # Which documents are superseded, resolved *before* any name is claimed.
    # It was applied afterwards and the marker arrived too late: the superseded
    # expense policy took `Expense Policy.md` first and the current one landed
    # as `Expense Policy (2).md`, so the shelf named the retired document as the
    # obvious one and the live document as an afterthought. Exactly backwards,
    # and exactly the mistake a reader would act on.
    # ...and only for a document that was *revised in place*. A monthly close
    # calendar supersedes last month's, which is the ordinary life of a
    # periodic document rather than a retirement: marking it would put
    # "(superseded)" on five of six calendars and teach a reader to ignore the
    # word. A policy revised in place is the case the marker exists for, and
    # `PERIODIC` is already the line between the two. The edge itself is
    # recorded either way, in `superseded_by`.
    by_type = {artifact.id: artifact.artifact_type for artifact in world.artifacts}
    retired = {
        artifact_id for artifact_id in replaced_by
        if by_type.get(artifact_id) not in PERIODIC
    }

    def subject_of(artifact: Any) -> str:
        """The one entity this document is about, when there is exactly one.

        A drive full of `Performance Review 2026-07 (2)` through `(5)` is a
        drive nobody can search, and the corpus knows the answer: those four
        documents are about four named people. Only when the supporting facts
        agree on a single subject — a document that cites the whole group and
        every division is *about* the group, and appending eight names would be
        worse than appending none.
        """
        subjects = {
            facts[f].subject for f in artifact.supporting_fact_ids if f in facts
        }
        if len(subjects) != 1:
            return ""
        only = next(iter(subjects))
        if only in people:
            return _clean(people[only].name)
        named = world.entity_names().get(only, "") if hasattr(world, "entity_names") else ""
        # A company-wide document is not "about" the company in a way worth
        # putting in a filename — every document here is.
        return "" if only.startswith("CO") else _clean(named)

    placed: dict[str, Placed] = {}
    used: set[str] = set()
    for artifact in world.artifacts:
        period = next(
            (facts[f].period for f in artifact.supporting_fact_ids
             if f in facts and facts[f].period), None,
        )
        folder = _folder(artifact, period)
        policy = policies.get(artifact.access_policy_id or "")

        readers: tuple[str, ...] = ()
        if policy is not None and (policy.allow_people or policy.allow_functions
                                   or policy.allow_business_units):
            readers = tuple(sorted({
                address[p.id] for p in world.people if policy.permits(p)
            }))

        title = _clean(artifact.title)
        about = subject_of(artifact)
        if about and about.lower() not in title.lower():
            title = f"{title} - {about}"
        # A period in the *name* as well as the folder, because a file lifted
        # out of its folder — attached to an email, dropped in a chat — has to
        # stay identifiable. That is the single most common way a real document
        # loses its context, and naming it defensively is what people do.
        if period and artifact.artifact_type in PERIODIC:
            title = f"{title} {period}"
        if artifact.id in retired:
            title = f"{title} (superseded)"

        extension = _extension(artifact.path)
        candidate = f"{folder}/{title}{extension}"
        n = 1
        while candidate.lower() in used:
            n += 1
            candidate = f"{folder}/{title} ({n}){extension}"
        used.add(candidate.lower())

        placed[artifact.id] = Placed(
            artifact_id=artifact.id,
            path=candidate,
            title=title,
            owner=address.get(artifact.author_id, ""),
            readers=readers,
            policy=policy.label if policy is not None else "All staff",
            created=artifact.created_at.isoformat(),
        )

    # The forward edge, now that every path is known: a superseded document
    # points at the one that replaced it, which is what lets a reader holding
    # the retired file find the live one without searching.
    return tuple(
        entry if entry.artifact_id not in replaced_by
        else Placed(
            artifact_id=entry.artifact_id, path=entry.path, title=entry.title,
            owner=entry.owner, readers=entry.readers, policy=entry.policy,
            created=entry.created,
            superseded_by=placed[replaced_by[entry.artifact_id]].path
            if replaced_by[entry.artifact_id] in placed else None,
        )
        for entry in placed.values()
    )


#: Where a misfiled document lands, and whose folder it was dragged into.
#:
#: Two shapes, because real drives have both: a company-wide dumping ground
#: nobody owns, and somebody's personal folder that everybody can see into.
_STRAY = ("Shared", "_Inbox")

#: What somebody appends when they save their own version.
_VERSION_MARKS = ("FINAL", "v2", "draft", "REVIEWED", "old")


def _noisy(entries: tuple[Placed, ...], *, level: str, seed: int) -> tuple[Placed, ...]:
    """*entries*, plus the junk a drive of this untidiness carries.

    Seeded off the world's own seed so a corpus's drive is the same drive every
    time — a benchmark whose distractors moved between runs would not be a
    benchmark. Drawn over the entries in path order rather than in draw order,
    for the reason every ordering decision here is made: the choice is seeded,
    the sequence is not.
    """
    from .rng import Rng

    share = NOISE.get(level)
    if share is None:
        raise ValueError(
            f"unknown noise level {level!r}; known: {', '.join(NOISE)}."
            " `none` is the default and adds nothing."
        )
    if not share or not entries:
        return entries

    rng = Rng(seed).derive("workspace/noise")
    ordered = sorted(entries, key=lambda e: e.path)
    wanted = max(1, round(len(ordered) * share))
    picked = sorted(rng.sample(range(len(ordered)), min(wanted, len(ordered))))

    out = list(entries)
    used = {e.path.lower() for e in entries}
    for n, index in enumerate(picked):
        source = ordered[index]
        kind = _NOISE_KINDS[n % len(_NOISE_KINDS)]
        folder, _, name = source.path.rpartition("/")
        stem, extension = Path(name).stem, Path(name).suffix
        draw = rng.derive(f"junk/{n}")

        if kind == "copy":
            path = f"{folder}/Copy of {stem}{extension}"
        elif kind == "misfiled":
            path = f"{draw.choice(_STRAY)}/{stem}{extension}"
        elif kind == "versioned":
            path = f"{folder}/{stem} {draw.choice(_VERSION_MARKS)}{extension}"
        else:
            # An archive folder at the top of the shelf, not beside the file:
            # somebody tidied a level and stopped.
            shelf = folder.split("/")[0]
            path = f"{shelf}/_Archive/{stem}{extension}"

        bump = 1
        candidate = path
        while candidate.lower() in used:
            bump += 1
            head, _, tail = path.rpartition(".")
            candidate = f"{head} ({bump}).{tail}" if head else f"{path} ({bump})"
        used.add(candidate.lower())

        out.append(Placed(
            artifact_id=source.artifact_id, path=candidate,
            title=Path(candidate).stem, owner=source.owner,
            # A copy carries the permissions of what it copies. That is what
            # makes a misfiled document interesting rather than merely untidy:
            # it is somewhere nobody would look and still readable only by the
            # people the original was readable by, so an assistant that finds it
            # has found something it was allowed to find.
            readers=source.readers, policy=source.policy, created=source.created,
            noise=kind, copy_of=source.path,
        ))
    return tuple(out)


def write(world: Any, destination: str | Path, *, overwrite: bool = False,
          noise: str = "none") -> Path:
    """Write the workspace tree and its permission table. Returns the root.

    Copies the rendered files rather than re-rendering them, so a workspace is
    the same bytes the corpus already validated — a second render is a second
    chance to disagree, and there would be nothing to say which was right.

    ``permissions.jsonl`` is one row per file, and it is the half of this that
    a connector actually needs: a tree with no permission table is a tree that
    tests retrieval and cannot test access.
    """
    if world.root is None:
        raise ValueError(
            "a workspace is written from a corpus on disk; export the corpus"
            " first, then point this at it"
        )
    source = Path(world.root) / "artifacts"
    if not source.is_dir():
        raise ValueError(
            f"{world.root} has no rendered artifacts to lay out; render the"
            " corpus in at least one format first — a workspace of empty"
            " folders would look like a corpus that had been indexed"
        )

    target = Path(destination)
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise FileExistsError(f"{target} is not empty; pass overwrite=True")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    manifest = {a.id: a for a in world.artifacts}
    rows: list[dict[str, Any]] = []
    written = 0
    entries = _noisy(layout(world), level=noise, seed=world.seed or 0)
    for entry in entries:
        artifact = manifest[entry.artifact_id]
        if not artifact.path:
            # Compiled but not rendered in the formats this corpus asked for —
            # a Jira bundle in a Markdown-only export. Recorded in the
            # permission table and not placed, because a row for a file that is
            # not there is a lie a connector would trip on.
            continue
        origin = Path(world.root) / artifact.path
        if not origin.is_file():
            continue
        destination_path = target / entry.path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination_path)
        written += 1
        rows.append({
            "path": entry.path,
            "artifact_id": entry.artifact_id,
            "title": entry.title,
            "owner": entry.owner,
            "readers": list(entry.readers),
            "policy": entry.policy,
            "created": entry.created,
            **({} if entry.superseded_by is None
               else {"superseded_by": entry.superseded_by}),
            **({} if entry.noise is None
               else {"noise": entry.noise, "copy_of": entry.copy_of}),
        })

    # newline pinned: this JSONL bypasses corpus.write_jsonl (it writes plain
    # dicts, not models), so it needs the same CRLF guard or a Windows-laid
    # workspace would differ byte-for-byte from a POSIX one.
    (target / "permissions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8", newline="\n",
    )
    if not written:
        raise ValueError(
            "nothing was placed: the manifest names no rendered file that"
            " exists on disk. Render the corpus before laying it out."
        )
    return target


def summarise(world: Any, *, noise: str = "none") -> Mapping[str, Any]:
    """What the layout came out as, for a caller that wants to print it."""
    entries = _noisy(layout(world), level=noise, seed=world.seed or 0)
    folders = {entry.path.rpartition("/")[0] for entry in entries}
    restricted = [e for e in entries if e.readers]
    return {
        "files": len(entries),
        "folders": len(folders),
        "deepest": max((entry.path.count("/") for entry in entries), default=0),
        "restricted": len(restricted),
        "distinct_owners": len({entry.owner for entry in entries if entry.owner}),
        "superseded": sum(1 for e in entries if e.superseded_by),
        "junk": sum(1 for e in entries if e.noise),
    }
