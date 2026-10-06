"""``worldloom telemetry …`` — the one place a customer's catalogue is opened.

Everything in :mod:`worldloom.telemetry` takes bytes and returns values. This
module is where a path is chosen, a file is read, and four files are written.
Keeping that here, and only here, means one line in the codebase decides which
customer file is read.

    worldloom telemetry company-template CATALOGUE --out company.json
        a company file to fill in; the importer never invents one

    worldloom telemetry import CATALOGUE --company company.json --out DIR
        DIR/project.json          accepted by `worldloom studio init`
        DIR/import-report.json    every journey, every finding, the split
        DIR/import-report.md      the same, for a person
        DIR/import-receipt.json   digests only, so a run can be proved later

Exit codes: 0 when a project was written. 3 when nothing could be built, or
when ``--strict`` was given and any hard finding exists. Refusals of the
inputs themselves — an unreadable catalogue, a missing company — exit 2, like
every other refusal in this CLI.

Imports stay inside the commands. ``cli.py`` loads this module at start-up,
and the start-up budget is a standing concern there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer

if TYPE_CHECKING:
    from .telemetry import ImportResult

telemetry_app = typer.Typer(
    no_args_is_help=True,
    help="Import a customer's CUJ catalogue as a Studio company project.")

#: Written by every import, in this order. Listed once so the overwrite check
#: and the writer can never disagree about which files an import owns.
PROJECT, REPORT_JSON, REPORT_MD, RECEIPT = (
    "project.json", "import-report.json", "import-report.md",
    "import-receipt.json")
_OUTPUTS = (PROJECT, REPORT_JSON, REPORT_MD, RECEIPT)

REPORT_SCHEMA = "worldloom.telemetry-import-report/v1"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n", encoding="utf-8")


def _refuse_existing(paths: list[Path], overwrite: bool) -> None:
    from .cli import _refuse

    taken = [path for path in paths if path.exists()]
    if taken and not overwrite:
        _refuse("destination_exists",
                f"[red]error:[/red] already exists: "
                f"{', '.join(str(path) for path in taken)}; pass --overwrite "
                "to replace",
                paths=[str(path) for path in taken])


def _read_catalogue(path: Path) -> bytes:
    from .cli import _refuse

    try:
        return path.read_bytes()
    except OSError as error:
        _refuse("catalogue_rejected",
                f"[red]error:[/red] cannot read catalogue {path}: "
                f"{error.strerror or error}")


def _refuse_catalogue(error: Any) -> NoReturn:
    """A ``CatalogueRefused`` as a CLI refusal, every reason included."""
    from rich.markup import escape

    from .cli import _refuse

    reasons = [finding.message for finding in error.report.hard_findings]
    _refuse(error.code,
            "[red]error:[/red] catalogue refused:\n  "
            + "\n  ".join(escape(reason) for reason in reasons),
            findings=[finding.model_dump(mode="json")
                      for finding in error.report.hard_findings])


def _company(path: Path | None, acknowledge_unmet: bool,
             ) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The company document, checked, and the limitations it acknowledges.

    Required, and never inferred. The catalogue knows how people use their
    tools and nothing about headcount, revenue, geography or name; a company
    guessed from it would be fiction sitting in a file that is otherwise
    evidence, with no way for a reader to tell the two apart.
    """
    from rich.markup import escape

    from .cli import _conflict_code, _refuse
    from .company import from_document, resolve

    if path is None:
        _refuse("company_required",
                "[red]error:[/red] --company is required. The catalogue says "
                "nothing about the company itself, and the importer will not "
                "invent one. Start from `worldloom telemetry company-template`.")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        spec = from_document(document)
    except (OSError, ValueError) as error:
        _refuse("company_required",
                f"[red]error:[/red] cannot use company file {path}: "
                f"{escape(str(error))}")
    if spec.identity is None or not (document.get("identity") or {}).get(
            "company_name"):
        _refuse("company_required",
                f"[red]error:[/red] {path} names no identity.company_name. "
                "A person decides what the company is called, not the importer.")

    resolution = resolve(spec)
    if resolution.conflicts:
        _refuse(_conflict_code(resolution.conflicts),
                "[red]error:[/red] the company file contradicts itself:\n  "
                + "\n  ".join(escape(str(conflict))
                              for conflict in resolution.conflicts),
                conflicts=[conflict.as_dict()
                           for conflict in resolution.conflicts])
    if resolution.unmet and not acknowledge_unmet:
        _refuse("company_unmet",
                "[red]error:[/red] the company file asks for things Worldloom "
                "cannot build:\n  "
                + "\n  ".join(escape(item) for item in resolution.unmet)
                + "\nPass --acknowledge-unmet to build without them.",
                unmet=list(resolution.unmet))
    return document, tuple(resolution.unmet) if acknowledge_unmet else ()


def _report(result: ImportResult, *, assumptions: dict[str, Any],
            written: bool) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA,
        "catalogue_id": result.catalogue_id,
        "accepted": result.report.accepted,
        "project_written": written,
        "assumptions": assumptions,
        "questions": result.counts.total,
        "share_lost": result.counts.share_lost,
        "journeys": [journey.model_dump(mode="json")
                     for journey in result.journeys],
        "findings": [finding.model_dump(mode="json")
                     for finding in result.report.findings],
    }


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _markdown(report: dict[str, Any]) -> str:
    built = [j for j in report["journeys"] if j["count"]]
    hard = [f for f in report["findings"] if f["severity"] == "hard"]
    info = [f for f in report["findings"] if f["severity"] == "info"]
    lines = [
        f"# Telemetry import — {report['catalogue_id']}",
        "",
        f"{len(report['journeys'])} journeys in the catalogue · "
        f"{len(built)} built · {report['questions']} questions · "
        f"{report['share_lost']:.1%} of real traffic not represented",
        "",
        f"Accepted: **{'yes' if report['accepted'] else 'no'}** "
        f"({len(hard)} hard, {len(info)} info). "
        f"Project written: **{'yes' if report['project_written'] else 'no'}**.",
        "",
        "## Assumptions",
        "",
        "The catalogue carries none of these, so each is a choice, not a "
        "measurement.",
        "",
        *(f"- **{key}**: {value}" for key, value in report["assumptions"].items()),
        "",
        "## Journeys",
        "",
        "| journey | label | group | share | questions |",
        "|---|---|---|---:|---:|",
        *(f"| `{j['cuj_id']}` | {_cell(j['label'])} | {j['group']} | "
          f"{j['share']:.3f} | {j['count']} |" for j in report["journeys"]),
        "",
        "## Findings",
        "",
    ]
    for title, group in (("Hard — something real was lost", hard),
                         ("Info — nothing is wrong", info)):
        lines += [f"### {title}", ""]
        lines += [f"- `{f['code']}` {('`' + f['cuj_id'] + '` ') if f['cuj_id'] else ''}"
                  f"— {_cell(f['message'])}" for f in group] or ["None."]
        lines.append("")
    return "\n".join(lines)


@telemetry_app.command("import")
def import_command(
    catalogue: Annotated[Path, typer.Argument(
        help="A cuj-catalogue/1 file from the customer telemetry miner.")],
    out: Annotated[Path, typer.Option(
        "--out", help="Directory for project.json and the import report.")],
    company: Annotated[Path | None, typer.Option(
        "--company",
        help="Company JSON. Required: the catalogue says nothing about the "
             "company itself.")] = None,
    cases: Annotated[int, typer.Option(
        "--cases", min=1, help="Total questions, shared by real traffic.")] = 200,
    seed: Annotated[int, typer.Option(
        "--seed", help="The company's seed in project.json.")] = 8128,
    persona: Annotated[str, typer.Option(
        "--persona", help="Who asks. The catalogue cannot say.")] = "employee",
    audience: Annotated[str, typer.Option(
        "--audience", help="Who the output is for.")] = "team",
    strict: Annotated[bool, typer.Option(
        "--strict", help="Exit 3 on any hard finding, and write no project.")] = False,
    overwrite: Annotated[bool, typer.Option(
        "--overwrite", help="Replace files a previous import wrote.")] = False,
    acknowledge_unmet: Annotated[bool, typer.Option(
        "--acknowledge-unmet",
        help="Build even though the company file asks for things Worldloom "
             "cannot build.")] = False,
    json_output: Annotated[bool, typer.Option(
        "--json", help="Print the report as JSON instead of a summary.")] = False,
) -> None:
    """Turn a CUJ catalogue into a project `worldloom studio init` accepts."""
    from .cli import _refuse
    from .studio.models import ProjectSpec
    from .telemetry import CatalogueRefused, import_catalogue

    document, acknowledged = _company(company, acknowledge_unmet)
    data = _read_catalogue(catalogue)
    _refuse_existing([out / name for name in _OUTPUTS], overwrite)

    try:
        result = import_catalogue(data, document, cases=cases,
                                  persona=persona, audience=audience)
    except CatalogueRefused as error:
        _refuse_catalogue(error)

    hard = result.report.hard_findings
    project = None
    if result.project is not None and not (strict and hard):
        project = ProjectSpec.model_validate({
            **result.project.model_dump(mode="json"),
            "seed": seed, "acknowledged_unmet": list(acknowledged)})

    assumptions = {"persona": persona, "audience": audience, "cases": cases,
                   "seed": seed}
    report = _report(result, assumptions=assumptions,
                     written=project is not None)

    out.mkdir(parents=True, exist_ok=True)
    # A stale project.json beside a fresh report would describe a different
    # import from the one it sits next to.
    (out / PROJECT).unlink(missing_ok=True)
    if project is not None:
        _write_json(out / PROJECT, project.model_dump(mode="json"))
    _write_json(out / REPORT_JSON, report)
    (out / REPORT_MD).write_text(_markdown(report), encoding="utf-8")
    _write_json(out / RECEIPT, result.receipt.model_dump(mode="json"))

    if result.project is None:
        codes = sorted({finding.code for finding in hard})
        _refuse("catalogue_uncompilable",
                f"[red]error:[/red] nothing in {catalogue} could be built "
                f"({', '.join(codes) or 'no buildable journeys'}); "
                f"see {out / REPORT_MD}",
                exit_code=3, codes=codes, report=str(out / REPORT_JSON))
    if strict and hard:
        codes = sorted({finding.code for finding in hard})
        _refuse("strict_findings",
                f"[red]error:[/red] --strict: {_count(len(hard), 'hard finding')} "
                f"({', '.join(codes)}); no project written. See {out / REPORT_MD}",
                exit_code=3, codes=codes, report=str(out / REPORT_JSON))

    if json_output:
        typer.echo(json.dumps(report, sort_keys=True))
        return
    built = [journey for journey in result.journeys if journey.count]
    typer.echo(f"wrote {out / PROJECT}: {len(built)} of {len(result.journeys)} "
               f"journeys, {result.counts.total} questions, "
               f"{result.counts.share_lost:.1%} of traffic not represented")
    typer.echo(f"      {_count(len(hard), 'hard finding')} and "
               f"{_count(len(result.report.info_findings), 'info finding')} — "
               f"see {out / REPORT_MD}")


@telemetry_app.command("company-template")
def company_template_command(
    catalogue: Annotated[Path, typer.Argument(
        help="A cuj-catalogue/1 file from the customer telemetry miner.")],
    out: Annotated[Path, typer.Option(
        "--out", help="Where to write the company file.")],
    overwrite: Annotated[bool, typer.Option(
        "--overwrite", help="Replace an existing file.")] = False,
) -> None:
    """Write a company file to fill in, suggested from the catalogue's hint."""
    from .archetypes import inspired_by, matched
    from .telemetry import CatalogueRefused, load_catalogue

    data = _read_catalogue(catalogue)
    _refuse_existing([out], overwrite)
    try:
        parsed, _ = load_catalogue(data)
    except CatalogueRefused as error:
        _refuse_catalogue(error)

    industry = parsed.industry_hint.industry if parsed.industry_hint else ""
    archetype = inspired_by(industry)
    recognised = bool(industry) and matched(industry) is not None
    document: dict[str, Any] = {
        "archetype": archetype.key,
        # Deliberately blank. The catalogue cannot say what the company is
        # called, and `import` refuses a file that leaves this empty.
        "identity": {"company_name": ""},
    }
    if industry:
        document["industry"] = industry

    out.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out, document)
    source = (f"matched from industry hint {industry!r}" if recognised
              else "the default — the catalogue's hint matched no archetype")
    typer.echo(f"wrote {out}: archetype {archetype.key} ({source})")
    typer.echo("      fill in identity.company_name, then run "
               "`worldloom telemetry import`")
