"""HTML as an intranet page (SharePoint or Confluence), not a standalone file.

Every page sits in a site: a header naming the company's intranet, a left
navigation of spaces (one per domain) listing every page in the corpus, and
breadcrumbs from the home page through the space and the pack to the page.
The page carries its metadata (owner, last modified, version, status, labels),
its contents, numbered sections with embedded tables and charts (the legacy
renderer's own table and SVG chart code), an attachments list naming the
sibling files of the same document, links to the other pages of its pack, the
page history, and the review comments with the author's replies.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

from ... import longform
from .. import Rendered
from .. import html as legacy

if TYPE_CHECKING:  # pragma: no cover
    from ...models import ArtifactIR
    from . import Context

_SITE_CSS = [
    "body { margin: 0; max-width: none; padding: 0; }",
    ".site-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 24px;"
    " border-bottom: 1px solid #ddd; }",
    ".site-header .site-name { font-weight: bold; }",
    ".site-header input { padding: 4px 8px; width: 260px; }",
    ".layout { display: flex; }",
    ".site-nav { width: 250px; padding: 16px; border-right: 1px solid #ddd; font-size: 0.9em; }",
    ".site-nav h3 { margin: 12px 0 4px; font-size: 1em; }",
    ".site-nav ul { list-style: none; padding-left: 8px; margin: 0; }",
    ".site-nav li.current { font-weight: bold; }",
    "main { flex: 1; padding: 16px 32px; max-width: 1000px; }",
    ".breadcrumbs { font-size: 0.85em; color: #666; margin-bottom: 8px; }",
    ".page-meta { font-size: 0.85em; color: #666; margin: 4px 0 12px; }",
    ".label { display: inline-block; border: 1px solid #ccc; border-radius: 3px; padding: 0 6px; margin-right: 4px; }",
    ".status { display: inline-block; padding: 1px 8px; border-radius: 3px; background: #eef; font-size: 0.8em; }",
    ".status.draft { background: #fff3cd; }",
    ".toc { border: 1px solid #ddd; padding: 8px 16px; font-size: 0.9em; }",
    ".comment { border-left: 3px solid #ccc; padding: 4px 12px; margin: 8px 0; }",
    ".comment .who { font-weight: bold; }",
    ".reply { margin-left: 24px; }",
    "caption { text-align: left; font-weight: bold; padding: 4px 0; }",
    ".source { font-size: 0.85em; color: #666; }",
    "ins { background: #e6ffed; } del { background: #ffeef0; }",
    ".site-footer { border-top: 1px solid #ddd; padding: 8px 24px; font-size: 0.8em; color: #666; }",
]


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")


def _blocks(blocks: tuple[longform.Block, ...], ctx: Context) -> list[str]:
    out: list[str] = []
    for block in blocks:
        if block.kind == "prose":
            if block.segments:
                out.append("<p>" + "".join(
                    _e(old) if new is None else f"<del>{_e(old)}</del> <ins>{_e(new)}</ins>"
                    for old, new in block.segments) + "</p>")
            else:
                out.append(f"<p>{_e(block.text)}</p>")
        elif block.kind == "note":
            out.append(f'<p class="note">{_e(block.text)}</p>')
        elif block.kind == "table" and block.table is not None:
            out.append(f'<div class="table-block" id="table-{_e(block.number)}">')
            out.append(f"<p><strong>Table {_e(block.number)}: {_e(block.caption)}</strong></p>")
            out.append(legacy._table_html(block.table, ctx.locale))
            if block.source:
                out.append(f'<p class="source">Source: {_e(block.source)}</p>')
            out.append("</div>")
        elif block.kind == "figure" and block.chart is not None:
            out.append('<figure class="chart-figure">')
            out.append(legacy._chart_svg(block.chart, block.table))
            out.append(f"<figcaption>Figure {_e(block.number)}: {_e(block.caption)}"
                       + (f" (source: {_e(block.source)})" if block.source else "") + "</figcaption>")
            out.append("</figure>")
    return out


def _relative(from_path: str, to_path: str) -> str:
    from .markdown import _relative as relative

    return relative(from_path, to_path)


def render_page(doc: longform.LongDocument, ctx: Context, ir: ArtifactIR, path: str,
                nav: dict[str, list[tuple[str, str, str]]]) -> bytes:
    company = ctx.world.company.name
    space = doc.metadata.get("artifact_domain", "") or ctx.intent(ir).domain
    space_label = space.replace("_", " ").capitalize()
    g = legacy._genome_for(ir)
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{_e(doc.title)} - {_e(space_label)} - {_e(company)} Intranet</title>",
        f'<meta name="author" content="{_e(doc.author.name)}">',
        f'<meta name="worldloom:artifact" content="{_e(doc.artifact_id)}">',
        f'<meta name="worldloom:version" content="{_e(doc.revision.version)}">',
        f'<meta name="keywords" content="{_e(", ".join(doc.labels))}">',
        "<style>",
        *legacy._css(g),
        *_SITE_CSS,
        "</style>",
        "</head>",
        "<body>",
        '<header class="site-header">',
        f'<span class="site-name">{_e(company)} Intranet</span>',
        '<form class="search" role="search"><input type="search" placeholder="Search this site" aria-label="Search"></form>',
        "</header>",
        '<div class="layout">',
        '<nav class="site-nav" aria-label="Site">',
        f'<p><a href="{_e(_relative(path, "artifacts/index.html"))}">Home</a></p>',
    ]
    for space_key in sorted(nav):
        parts.append(f"<h3>{_e(space_key.replace('_', ' ').capitalize())}</h3>")
        parts.append("<ul>")
        for artifact_id, title, target in nav[space_key]:
            current = ' class="current"' if artifact_id == doc.artifact_id else ""
            parts.append(f'<li{current}><a href="{_e(_relative(path, target))}">{_e(title)}</a></li>')
        parts.append("</ul>")
    parts.append("</nav>")
    parts.append("<main>")
    crumbs = [f'<a href="{_e(_relative(path, "artifacts/index.html"))}">Home</a>', _e(space_label)]
    if doc.family is not None:
        from . import FAMILIES_DIR

        crumbs.append(f'<a href="{_e(_relative(path, f"{FAMILIES_DIR}/{doc.family.key}/index.md"))}">'
                      f"{_e(doc.family.title)}</a>")
    crumbs.append(_e(doc.title))
    parts.append('<nav class="breadcrumbs" aria-label="Breadcrumb">' + " &rsaquo; ".join(crumbs) + "</nav>")
    parts.append(f"<h1>{_e(doc.title)}</h1>")
    status_class = "status draft" if doc.draft else "status"
    first = doc.history[0]
    parts.append(
        '<div class="page-meta">'
        f'<span class="{status_class}">{_e(doc.revision.status)}</span> '
        f"Created by {_e(first.by.name)} on {first.at.strftime('%d %b %Y')}, "
        f"last modified by {_e(doc.revision.by.name)} on {doc.revision.at.strftime('%d %b %Y %H:%M')} "
        f"| Version {_e(doc.revision.version)} | Owner: {_e(doc.author.name)}, {_e(doc.author.title)}"
        + (f" | Approver: {_e(doc.approver.name)}" if doc.approver else "")
        + f" | {_e(doc.classification)}<br>Labels: "
        + "".join(f'<span class="label">{_e(label)}</span>' for label in doc.labels)
        + "</div>")
    if doc.subtitle:
        parts.append(f"<p><em>{_e(doc.subtitle)}</em></p>")
    entries = [label for level, label in longform.contents(doc) if level == 1]
    if doc.long and entries:
        parts.append('<div class="toc"><strong>On this page</strong><ul>'
                     + "".join(f'<li><a href="#{_anchor(label)}">{_e(label)}</a></li>' for label in entries)
                     + "</ul></div>")
    for part in doc.all_parts():
        parts.append(f'<section id="{_anchor(part.label)}">')
        parts.append(f"<h2>{_e(part.label)}</h2>")
        parts.extend(_blocks(part.blocks, ctx))
        for child in part.children:
            parts.append(f"<h3>{_e(child.number)} {_e(child.heading)}</h3>")
            parts.extend(_blocks(child.blocks, ctx))
        parts.append("</section>")

    attachments = [(fmt, p) for fmt, p in ctx.files(ir) if fmt != "html"]
    for revision in doc.history:
        if revision.as_of is not None and ctx.intent(ir).artifact_type in _docx_types() and "docx" in ctx.formats:
            attachments.append(("docx", ctx.revision_path(ir, revision, "docx")))
    if attachments:
        parts.append('<section class="attachments"><h2>Attachments</h2><table><tr><th>File</th><th>Type</th></tr>')
        parts.extend(f'<tr><td><a href="{_e(_relative(path, p))}">{_e(p.rsplit("/", 1)[-1])}</a></td>'
                     f"<td>{_e(fmt)}</td></tr>" for fmt, p in attachments)
        parts.append("</table></section>")
    irs = {item.id: item for item in ctx.world.artifact_irs}
    related = [(r, irs[r.artifact_id]) for r in doc.related if r.artifact_id in irs]
    if related:
        parts.append('<section class="related"><h2>Related pages</h2><ul>')
        parts.extend(f'<li><a href="{_e(_relative(path, ctx.path(other, "html")))}">{_e(r.title)}</a>'
                     f" ({_e(r.role)})</li>" for r, other in related)
        parts.append("</ul></section>")
    parts.append('<section class="history"><h2>Page history</h2><table>'
                 "<tr><th>Version</th><th>Date</th><th>Author</th><th>Status</th><th>Change</th></tr>")
    parts.extend("<tr>" + "".join(f"<td>{_e(value)}</td>" for value in row) + "</tr>"
                 for row in longform.history_rows(doc))
    parts.append("</table></section>")
    if doc.comments:
        parts.append('<section class="comments"><h2>Comments</h2>')
        for comment in doc.comments:
            parts.append(
                f'<div class="comment"><span class="who">{_e(comment.author.name)}</span> '
                f'<span class="when">{comment.at.strftime("%d %b %Y %H:%M")}</span>'
                f" on section {_e(comment.part)}<p>{_e(comment.text)}</p>"
                f'<div class="reply"><span class="who">{_e(doc.author.name)}</span>'
                f"<p>{_e(comment.resolution)}</p></div></div>")
        parts.append("</section>")
    parts.append("</main>")
    parts.append("</div>")
    parts.append(f'<footer class="site-footer">{_e(company)} | {_e(doc.classification)} | '
                 f"{_e(doc.metadata.get('note', 'Synthetic corpus generated by Worldloom. Not a real company.'))}</footer>")
    parts.append("</body>")
    parts.append("</html>")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _docx_types() -> set[str]:
    from ..docx import HANDLES

    return set(HANDLES)


def render_all(ctx: Context) -> list[Rendered]:
    nav: dict[str, list[tuple[str, str, str]]] = {}
    for ir in ctx.world.artifact_irs:
        intent = ctx.intent(ir)
        nav.setdefault(intent.domain, []).append((ir.id, ir.title, ctx.path(ir, "html")))
    out: list[Rendered] = []
    for ir in ctx.world.artifact_irs:
        path = ctx.path(ir, "html")
        out.append(Rendered(artifact_id=ir.id, path=path, media_type="text/html",
                            payload=render_page(ctx.doc(ir), ctx, ir, path, nav)))
    # The site's home page: every space and its pages.
    home = ["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
            f"<title>{_e(ctx.world.company.name)} Intranet</title>", "</head>", "<body>",
            f"<h1>{_e(ctx.world.company.name)} Intranet</h1>"]
    for space_key in sorted(nav):
        home.append(f"<h2>{_e(space_key.replace('_', ' ').capitalize())}</h2><ul>")
        home.extend(f'<li><a href="{_e(_relative("artifacts/index.html", target))}">{_e(title)}</a></li>'
                    for _id, title, target in nav[space_key])
        home.append("</ul>")
    home += ["</body>", "</html>"]
    out.append(Rendered(artifact_id="", path="artifacts/index.html", media_type="text/html",
                        payload=("\n".join(home) + "\n").encode("utf-8")))
    return out
