"""Markdown as it arrives from an engineering wiki export.

YAML front matter a static-site or wiki importer reads (id, owner, status,
version, labels, the pack and related pages), an "on this page" list, numbered
headings, tables, the figures' lineage as a YAML code block, relative links to
the sibling pages and files of the same pack, and the page history. A
post-incident review is exported as a postmortem, a knowledge article as a
runbook whose procedure is a numbered list; the wording is the narrated prose
either way, only its arrangement differs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ... import longform
from .. import Rendered
from .. import markdown as legacy

if TYPE_CHECKING:  # pragma: no cover
    from ...models import ArtifactIR
    from . import Context

#: Wiki templates by artifact type: the front-matter ``template`` and how the
#: body is arranged. Everything else is a page.
_TEMPLATES = {
    "incident_rca": "postmortem",
    "knowledge_article": "runbook",
    "working_note": "notes",
    "confluence_page": "status-page",
    "jira_issues": "engineering-log",
    "servicenow_incident": "incident-record",
    "meeting_minutes": "minutes",
}


def _yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).strip().replace(" ", "-")


def _relative(from_path: str, to_path: str) -> str:
    """A link from one file under ``artifacts/`` to another."""
    source = from_path.split("/")[:-1]
    target = to_path.split("/")
    common = 0
    while common < min(len(source), len(target) - 1) and source[common] == target[common]:
        common += 1
    return "/".join([".."] * (len(source) - common) + target[common:])


def _blocks(blocks: tuple[longform.Block, ...], ctx: Context, template: str) -> list[str]:
    out: list[str] = []
    for block in blocks:
        if block.kind == "prose":
            if template == "runbook":
                steps = longform.sentences(block.text)
                out.append("\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1)))
            elif block.segments:
                out.append("".join(old if new is None else f"~~{old}~~ **{new}**" for old, new in block.segments))
            else:
                out.append(block.text)
        elif block.kind == "note":
            out.append(f"> {block.text}")
        elif block.kind == "table" and block.table is not None:
            if block.table.key == "lineage":
                out.append(f"**Table {block.number}: {block.caption}**")
                out.append(_lineage_yaml(block.table))
            else:
                out.append(f"**Table {block.number}: {block.caption}**")
                out.append(legacy._table(block.table, ctx.locale))
            if block.source:
                out.append(f"*Source: {block.source}*")
        elif block.kind == "figure" and block.chart is not None:
            labels = ", ".join(
                (column.label if block.table and (column := block.table.column(key)) else key)
                for key in block.chart.series)
            out.append(f"**Figure {block.number}: {block.caption}** *({block.chart.kind.value} chart of {labels};"
                       " the plotted values are the table above)*")
    return out


def _lineage_yaml(table) -> str:  # type: ignore[no-untyped-def]
    lines = ["```yaml", "lineage:"]
    for row in table.rows:
        lines.append(f"  - fact: {row.label}")
        for column in table.columns:
            cell = row.cells.get(column.key)
            if cell is not None and cell.value not in (None, ""):
                lines.append(f"    {column.key}: {_yaml(str(cell.value))}")
    lines.append("```")
    return "\n".join(lines)


def render_page(doc: longform.LongDocument, ctx: Context, ir: ArtifactIR, path: str) -> bytes:
    template = _TEMPLATES.get(doc.artifact_type, "page")
    related_links: list[tuple[str, str, str]] = []
    irs = {item.id: item for item in ctx.world.artifact_irs}
    for related in doc.related:
        other = irs.get(related.artifact_id)
        if other is None:
            continue
        files = ctx.files(other)
        target = next((p for fmt, p in files if fmt == "markdown"), None) or (files[0][1] if files else None)
        if target:
            related_links.append((related.title, _relative(path, target), related.role))
    attachments = [(fmt, p) for fmt, p in ctx.files(ir) if fmt not in {"markdown", "html"}]

    front = [
        "---",
        f"title: {_yaml(doc.title)}",
        f"id: {doc.artifact_id}",
        f"reference: {doc.reference}",
        f"template: {template}",
        f"type: {_yaml(doc.genre)}",
        f"space: {doc.metadata.get('artifact_domain', '')}",
        f"author: {_yaml(doc.author.name)}",
        f"owner_title: {_yaml(doc.author.title)}",
    ]
    if doc.approver:
        front.append(f"approver: {_yaml(doc.approver.name)}")
    front += [
        f"status: {doc.revision.status.lower()}",
        f"version: {_yaml(doc.revision.version)}",
        f"classification: {_yaml(doc.classification)}",
        f"period: {_yaml(doc.period)}",
        f"last_updated: {doc.revision.at.strftime('%Y-%m-%dT%H:%M:00Z')}",
        "labels: [" + ", ".join(doc.labels) + "]",
    ]
    if doc.family is not None:
        front.append(f"pack: {doc.family.key}")
    if related_links:
        front.append("related:")
        front.extend(f"  - {link}" for _title, link, _role in related_links)
    front.append("---")

    parts = ["\n".join(front), f"# {doc.title}"]
    byline = [f"{doc.genre}", doc.company, doc.classification]
    parts.append("> " + " | ".join(byline) + "  \n> Owner: " + f"{doc.author.name}, {doc.author.title}"
                 + (f" | Approver: {doc.approver.name}" if doc.approver else "")
                 + f" | Version {doc.revision.version} ({doc.revision.status})"
                 + f" | Last updated {doc.revision.at.strftime('%d %b %Y')}")
    if doc.draft:
        parts.append("> **Draft for review.** Figures marked TBC were not yet confirmed at this version's date.")
    toc = [f"- [{label}](#{_anchor(label)})" for level, label in longform.contents(doc) if level == 1]
    if doc.long and toc:
        parts.append("**On this page**\n\n" + "\n".join(toc))
    for part in doc.all_parts():
        parts.append(f"## {part.label}")
        parts.extend(_blocks(part.blocks, ctx, template if not part.appendix else "page"))
        for child in part.children:
            parts.append(f"### {child.number} {child.heading}")
            parts.extend(_blocks(child.blocks, ctx, "page"))
    if related_links or doc.family is not None:
        lines = [f"- [{title}]({link}) ({role})" for title, link, role in related_links]
        if doc.family is not None:
            from . import FAMILIES_DIR

            lines.append(f"- [{doc.family.title}]({_relative(path, f'{FAMILIES_DIR}/{doc.family.key}/index.md')}) (pack index)")
        parts.append("## Related pages\n\n" + "\n".join(lines))
    if attachments:
        parts.append("## Attachments\n\n" + "\n".join(
            f"- [{p.rsplit('/', 1)[-1]}]({_relative(path, p)}) ({fmt})" for fmt, p in attachments))
    history = longform.history_rows(doc)
    parts.append("## Page history\n\n| Version | Date | Author | Status | Change |\n| --- | --- | --- | --- | --- |\n"
                 + "\n".join(f"| {v} | {d} | {a} | {s} | {c} |" for v, d, a, s, c in history))
    if doc.comments:
        parts.append("## Comments\n\n" + "\n\n".join(
            f"**{c.author.name}** ({c.at.strftime('%d %b %Y %H:%M')}), on section {c.part}: {c.text}\n"
            f"> {doc.author.name}: {c.resolution}" for c in doc.comments))
    return ("\n\n".join(parts).rstrip() + "\n").encode("utf-8")


def render_all(ctx: Context, only: set[str] | None = None) -> list[Rendered]:
    out: list[Rendered] = []
    for ir in ctx.world.artifact_irs:
        artifact_type = ctx.intent(ir).artifact_type
        if only is None and artifact_type in legacy._OWNED_ELSEWHERE:
            continue
        if only is not None and ir.id not in only:
            continue
        path = ctx.path(ir, "md")
        out.append(Rendered(artifact_id=ir.id, path=path, media_type="text/markdown",
                            payload=render_page(ctx.doc(ir), ctx, ir, path)))
    return out


def revisions(ctx: Context, *, skip_docx: bool) -> list[Rendered]:
    """Earlier and later versions of signed pages Word does not already carry."""
    from ..docx import HANDLES

    out: list[Rendered] = []
    for ir in ctx.world.artifact_irs:
        intent = ctx.intent(ir)
        if intent.artifact_type in legacy._OWNED_ELSEWHERE or intent.approver_id is None:
            continue
        if skip_docx and intent.artifact_type in HANDLES:
            continue
        for revision in ctx.history(ir):
            if revision.as_of is None:
                continue
            path = ctx.revision_path(ir, revision, "md")
            out.append(Rendered(artifact_id=ir.id, path=path, media_type="text/markdown",
                                payload=render_page(ctx.doc(ir, revision), ctx, ir, path)))
    return out


def families(ctx: Context) -> list[Rendered]:
    """One index page per pack: its members, their owners and their files."""
    from . import FAMILIES_DIR

    irs = {ir.id: ir for ir in ctx.world.artifact_irs}
    out: list[Rendered] = []
    for family in ctx.families:
        path = f"{FAMILIES_DIR}/{family.key}/index.md"
        lines = ["---", f"title: {_yaml(family.title)}", f"pack: {family.key}", f"period: {_yaml(family.period)}",
                 "members:"]
        lines.extend(f"  - {artifact_id}" for artifact_id, _role in family.members)
        lines += ["---", "", f"# {ctx.world.company.name}: {family.title}", "",
                  "| Reference | Document | Role | Owner | Files |", "| --- | --- | --- | --- | --- |"]
        for artifact_id, role in family.members:
            ir = irs.get(artifact_id)
            if ir is None:
                continue
            intent = ctx.intent(ir)
            owner = longform._person(ctx.world, intent.author_id)
            files = ", ".join(f"[{fmt}]({_relative(path, p)})" for fmt, p in ctx.files(ir))
            lines.append(f"| {artifact_id} | {ir.title} | {role} | {owner.name if owner else intent.author_id} | {files} |")
        if family.kind == "board" and "docx" in ctx.formats:
            lines += ["", f"Agenda: [agenda.docx]({_relative(path, f'{FAMILIES_DIR}/{family.key}/agenda.docx')})"]
        out.append(Rendered(artifact_id="", path=path, media_type="text/markdown",
                            payload=("\n".join(lines) + "\n").encode("utf-8")))
    return out
