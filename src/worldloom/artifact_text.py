"""What a rendered file *says*, read back out of its bytes.

Two readers need this and neither may trust the plan a file was rendered
from. A connector's ``get_file`` has to return the document's text, because
an agent asked to find a figure in a board paper can only find it in what the
file contains; and the realism measure has to count pages, slides and words
in what shipped, because a size read off the plan would measure the intention.

Standard library only (``zipfile``, ``xml.etree``, ``zlib``), so a corpus can
be measured and served on an install without the renderer extras. Each format
is read the way its own structure divides it: a Word document into its
top-level sections and explicit pages, a PDF into pages, a deck into slides
with their speaker notes, a workbook into sheets, Markdown and HTML into
headed sections.

**Pages in Word are an estimate, and say so.** A ``.docx`` has no pages until
a layout engine opens it. ``pages_equivalent`` lays the body out on the A4
geometry the renderers use (lines per page, characters per line, a table row
per line plus wrap) and honours every explicit page break; it is the number a
reader means by "a fifteen-page paper" to within a page or two, and it is
labelled an equivalent everywhere it is reported.
"""

from __future__ import annotations

import math
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

__all__ = ["Extract", "Unit", "extract"]

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_R = "{http://schemas.openxmlformats.org/package/2006/relationships}"

#: The A4 text block the Word and PDF renderers lay out on, in body lines and
#: characters, for the page equivalent.
_LINES_PER_PAGE = 46
_CHARS_PER_LINE = 92


@dataclass(frozen=True)
class Unit:
    """One division of a file: a section, a page, a slide or a sheet."""

    kind: str
    index: int
    title: str
    text: str
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "index": self.index, "title": self.title,
                               "words": len(self.text.split()), "text": self.text}
        if self.notes:
            out["notes"] = self.notes
        return out


@dataclass(frozen=True)
class Extract:
    format: str
    text: str
    units: tuple[Unit, ...] = ()
    pages: int = 0
    """Real pages for a PDF, the page equivalent for Word, zero otherwise."""
    tables: int = 0
    headings: int = 0
    notes: int = 0
    comments: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return len(self.text.split())

    def structure(self) -> dict[str, Any]:
        """The file's shape without its text: what a connector lists."""
        kind = self.units[0].kind if self.units else ""
        return {
            "format": self.format,
            "words": self.words,
            "pages": self.pages,
            "tables": self.tables,
            "headings": self.headings,
            "speaker_notes": self.notes,
            "comments": self.comments,
            "units": [{"kind": u.kind, "index": u.index, "title": u.title,
                       "words": len(u.text.split())} for u in self.units],
            "unit_kind": kind,
            **self.extra,
        }


def extract(path: str, payload: bytes) -> Extract | None:
    """The text and structure of one rendered file, or ``None`` for a format
    this module does not read."""
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    try:
        if suffix == "docx":
            return _docx(payload)
        if suffix == "pptx":
            return _pptx(payload)
        if suffix == "xlsx":
            return _xlsx(payload)
        if suffix == "pdf":
            return _pdf(payload)
        if suffix == "md":
            return _markdown(payload.decode("utf-8"))
        if suffix == "html":
            return _html(payload.decode("utf-8"))
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, UnicodeDecodeError, zlib.error):
        return None
    return None


# -- Word ------------------------------------------------------------------


def _para_text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_W}t"))


def _docx(payload: bytes) -> Extract:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        comments = 0
        if "word/comments.xml" in archive.namelist():
            comments = len(ElementTree.fromstring(archive.read("word/comments.xml")).findall(f"{_W}comment"))
    body = root.find(f"{_W}body")
    lines_used = 0.0
    pages = 1
    headings = 0
    tables = 0
    texts: list[str] = []
    units: list[Unit] = []
    current_title = ""
    current: list[str] = []

    def flush() -> None:
        if current_title or current:
            units.append(Unit("section", len(units) + 1, current_title, "\n".join(current).strip()))

    def consume(lines: float) -> None:
        nonlocal lines_used, pages
        lines_used += lines
        while lines_used > _LINES_PER_PAGE:
            pages += 1
            lines_used -= _LINES_PER_PAGE

    for child in list(body) if body is not None else []:
        if child.tag == f"{_W}p":
            text = _para_text(child)
            style = child.find(f"{_W}pPr/{_W}pStyle")
            style_name = style.get(f"{_W}val", "") if style is not None else ""
            is_heading = style_name.startswith("Heading") or style_name == "Title"
            if is_heading:
                headings += 1
            if style_name == "Heading1":
                flush()
                current_title, current = text, []
            elif text:
                current.append(text)
            if text:
                texts.append(text)
                consume((2.0 if is_heading else 0.4) + max(1, math.ceil(len(text) / _CHARS_PER_LINE)))
            else:
                consume(1.0)
            if child.find(f".//{_W}drawing") is not None:
                consume(16.0)
            for brk in child.iter(f"{_W}br"):
                if brk.get(f"{_W}type") == "page":
                    pages += 1
                    lines_used = 0.0
        elif child.tag == f"{_W}tbl":
            tables += 1
            for row in child.iter(f"{_W}tr"):
                cells = [_para_text(cell) for cell in row.iter(f"{_W}tc")]
                line = " | ".join(cells)
                if line.strip(" |"):
                    texts.append(line)
                    current.append(line)
                width = max(1, _CHARS_PER_LINE // max(1, len(cells)) - 2)
                consume(max([1] + [math.ceil(len(c) / width) for c in cells]) + 0.25)
            consume(1.0)
    flush()
    return Extract(format="docx", text="\n".join(texts), units=tuple(units), pages=pages,
                   tables=tables, headings=headings, comments=comments,
                   extra={"pages_are": "equivalent"})


# -- PowerPoint --------------------------------------------------------------


def _slide_number(name: str) -> int:
    match = re.search(r"(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _shape_paragraphs(root: ElementTree.Element) -> tuple[str, list[str]]:
    title = ""
    lines: list[str] = []
    for shape in root.iter(f"{_P}sp"):
        placeholder = shape.find(f".//{_P}nvPr/{_P}ph")
        kind = placeholder.get("type", "") if placeholder is not None else ""
        paragraphs = [
            "".join(node.text or "" for node in para.iter(f"{_A}t"))
            for para in shape.iter(f"{_A}p")
        ]
        paragraphs = [p for p in paragraphs if p.strip()]
        if kind in {"title", "ctrTitle"} and not title and paragraphs:
            title = " ".join(paragraphs)
            continue
        if kind in {"sldNum", "dt", "ftr"}:
            continue
        lines.extend(paragraphs)
    for frame in root.iter(f"{_A}tbl"):
        for row in frame.iter(f"{_A}tr"):
            cells = ["".join(n.text or "" for n in cell.iter(f"{_A}t")) for cell in row.iter(f"{_A}tc")]
            lines.append(" | ".join(cells))
    return title, lines


def _pptx(payload: bytes) -> Extract:
    units: list[Unit] = []
    notes_count = 0
    tables = 0
    charts = 0
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_slide_number)
        for name in slides:
            root = ElementTree.fromstring(archive.read(name))
            title, lines = _shape_paragraphs(root)
            tables += sum(1 for _ in root.iter(f"{_A}tbl"))
            charts += sum(1 for node in root.iter(f"{_A}graphicData")
                          if node.get("uri", "").endswith("/chart"))
            notes = ""
            rels = name.replace("slides/", "slides/_rels/") + ".rels"
            if rels in names:
                for rel in ElementTree.fromstring(archive.read(rels)).iter(f"{_PKG_R}Relationship"):
                    if rel.get("Type", "").endswith("/notesSlide"):
                        target = "ppt/" + rel.get("Target", "").replace("../", "")
                        if target in names:
                            _, note_lines = _shape_paragraphs(ElementTree.fromstring(archive.read(target)))
                            notes = "\n".join(note_lines).strip()
            if notes:
                notes_count += 1
            units.append(Unit("slide", _slide_number(name), title, "\n".join([title, *lines]).strip(), notes))
    text = "\n\n".join(u.text + (f"\nNotes: {u.notes}" if u.notes else "") for u in units)
    return Extract(format="pptx", text=text, units=tuple(units), tables=tables,
                   headings=sum(1 for u in units if u.title), notes=notes_count,
                   extra={"slides": len(units), "charts": charts})


# -- Excel -------------------------------------------------------------------


def _xlsx(payload: bytes) -> Extract:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{_S}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{_S}t")))
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{_PKG_R}Relationship")}
        units: list[Unit] = []
        for index, sheet in enumerate(workbook.iter(f"{_S}sheet"), start=1):
            target = targets.get(sheet.get(f"{_R}id"), "")
            part = "xl/" + target.lstrip("/").removeprefix("xl/")
            if part not in names:
                continue
            lines: list[str] = []
            for row in ElementTree.fromstring(archive.read(part)).iter(f"{_S}row"):
                values: list[str] = []
                for cell in row.iter(f"{_S}c"):
                    kind = cell.get("t")
                    value = cell.find(f"{_S}v")
                    if kind == "s" and value is not None and value.text is not None:
                        values.append(shared[int(value.text)])
                    elif kind == "inlineStr":
                        values.append("".join(n.text or "" for n in cell.iter(f"{_S}t")))
                    elif value is not None and value.text is not None:
                        values.append(value.text)
                if values:
                    lines.append(" | ".join(values))
            units.append(Unit("sheet", index, sheet.get("name", ""), "\n".join(lines)))
    return Extract(format="xlsx", text="\n\n".join(f"{u.title}\n{u.text}" for u in units),
                   units=tuple(units), tables=len(units), extra={"sheets": len(units)})


# -- PDF ---------------------------------------------------------------------

_OBJECT = re.compile(rb"(\d+) 0 obj(.*?)endobj", re.S)
_STRING = re.compile(rb"\((?:\\.|[^\\)])*\)\s*Tj|\[(?:[^\]]*)\]\s*TJ", re.S)
_LITERAL = re.compile(rb"\((?:\\.|[^\\)])*\)", re.S)
_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
            b"(": b"(", b")": b")", b"\\": b"\\"}


def _unescape(raw: bytes) -> str:
    out = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index:index + 1]
        if char == b"\\" and index + 1 < len(raw):
            nxt = raw[index + 1:index + 2]
            if nxt in _ESCAPES:
                out += _ESCAPES[nxt]
                index += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", raw[index + 1:index + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                index += 1 + len(octal.group(0))
                continue
            index += 1
            continue
        out += char
        index += 1
    return out.decode("cp1252", errors="replace")


def _pdf(payload: bytes) -> Extract:
    objects = {int(m.group(1)): m.group(2) for m in _OBJECT.finditer(payload)}
    kids: list[int] = []
    for body in objects.values():
        if re.search(rb"/Type\s*/Pages\b", body):
            match = re.search(rb"/Kids\s*\[([^\]]*)\]", body)
            if match and not kids:
                kids = [int(n) for n in re.findall(rb"(\d+)\s+0\s+R", match.group(1))]
    root_pages = [n for n in kids if re.search(rb"/Type\s*/Page\b", objects.get(n, b""))]
    if not root_pages:
        root_pages = sorted(n for n, body in objects.items() if re.search(rb"/Type\s*/Page\b", body))
    units: list[Unit] = []
    for index, number in enumerate(root_pages, start=1):
        body = objects[number]
        contents = re.findall(rb"/Contents\s+(\d+)\s+0\s+R", body)
        lines: list[str] = []
        for ref in contents:
            stream_obj = objects.get(int(ref), b"")
            match = re.search(rb"stream\r?\n(.*?)\r?\nendstream", stream_obj, re.S)
            if not match:
                continue
            data = match.group(1)
            if b"/FlateDecode" in stream_obj[:match.start()]:
                data = zlib.decompress(data)
            for op in _STRING.finditer(data):
                pieces = [_unescape(lit[1:-1]) for lit in _LITERAL.findall(op.group(0))]
                line = "".join(pieces).strip()
                if line:
                    lines.append(line)
        units.append(Unit("page", index, lines[0] if lines else "", "\n".join(lines)))
    outline = len(re.findall(rb"/Type\s*/Outlines\b", payload)) > 0
    return Extract(format="pdf", text="\n\n".join(u.text for u in units), units=tuple(units),
                   pages=len(units), extra={"outline": outline})


# -- Markdown and HTML -------------------------------------------------------


def _markdown(text: str) -> Extract:
    body = text
    front: dict[str, Any] = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            front = {"front_matter": True}
            body = text[end + 5:]
    units: list[Unit] = []
    title = ""
    current: list[str] = []
    headings = 0
    for line in body.splitlines():
        if line.startswith("#"):
            headings += 1
            if line.startswith("## ") or line.startswith("# "):
                if title or current:
                    units.append(Unit("section", len(units) + 1, title, "\n".join(current).strip()))
                title, current = line.lstrip("#").strip(), []
                continue
        current.append(line)
    if title or current:
        units.append(Unit("section", len(units) + 1, title, "\n".join(current).strip()))
    code = len(re.findall(r"^```", body, re.M)) // 2
    return Extract(format="markdown", text=body, units=tuple(units), headings=headings,
                   tables=len(re.findall(r"^\|(?:\s*-+\s*\|)+\s*$", body, re.M)),
                   extra={**front, "code_blocks": code,
                          "links": len(re.findall(r"\]\((?!http)[^)]+\)", body))})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.headings: list[str] = []
        self.tables = 0
        self.links = 0
        self._skip = 0
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script"}:
            self._skip += 1
        if tag == "table":
            self.tables += 1
        if tag == "a":
            self.links += 1
        if tag in {"h1", "h2"}:
            self._in_heading = True
            self.headings.append("")
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "br", "section", "nav"}:
            self.parts.append("\n")
        elif tag in {"td", "th", "span", "a"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"}:
            self._skip -= 1
        if tag in {"h1", "h2"}:
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)
        if self._in_heading and self.headings:
            self.headings[-1] += data


def _html(text: str) -> Extract:
    parser = _Text()
    parser.feed(text)
    body = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    body = re.sub(r"\n\s*\n+", "\n", body).strip()
    units = tuple(Unit("section", i, h.strip(), "") for i, h in enumerate(parser.headings, start=1))
    return Extract(format="html", text=body, units=units, headings=len(parser.headings),
                   tables=parser.tables, extra={"links": parser.links})
