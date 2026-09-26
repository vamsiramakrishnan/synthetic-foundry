"""``worldloom pack``: list, show, lint, install, interview and author packs of any kind.

The commands below are the kernel's (``worldloom.packkit``) and take a pack of
any registered kind; ``pack check`` beside them remains the company-pack lint
it always was. Every command speaks JSON on ``--json`` so a harness can drive
the whole cascade from a terminal, and every refusal names its findings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

Roots = Annotated[list[Path] | None, typer.Option("--root", help="A pack root searched before the user's and the shipped ones (repeatable).")]


def _emit(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))


def _refuse(message: str, findings: list[str] | None = None) -> None:
    from .cli import _refuse as refuse

    refuse("pack_rejected", message, findings=findings or [])


def install_commands(pack_app: typer.Typer) -> None:
    """Register the kernel's commands on the existing ``pack`` group."""

    @pack_app.command("kinds")
    def kinds_command() -> None:
        """The kinds of pack the product accepts, and what each controls."""
        from . import packkit

        _emit([{"kind": k.name, "default": k.default, "about": k.about} for k in packkit.kinds()])

    @pack_app.command("list")
    def list_command(kind: Annotated[str | None, typer.Argument(help="Only this kind.")] = None, root: Roots = None) -> None:
        """Every visible pack (a pack in a higher root shadows the same name below it)."""
        from .packkit import sources

        try:
            _emit([sources.as_data(item) for item in sources.discover(kind, roots=root or ())])
        except (KeyError, ValueError) as error:
            _refuse(str(error))

    @pack_app.command("show")
    def show_command(ref: Annotated[str, typer.Argument(help="kind:name[@digest] or a pack file.")], root: Roots = None) -> None:
        """The resolved pack: merged body, digest, the chain it layers on, and its findings."""
        from . import packkit

        try:
            _emit(packkit.show(ref, roots=root or ()))
        except (KeyError, ValueError) as error:
            _refuse(str(error).strip("'\""))

    @pack_app.command("lint")
    def lint_command(source: Annotated[Path, typer.Argument(help="A pack envelope file.")], root: Roots = None) -> None:
        """Resolve and lint a pack file without storing it; exits 2 on findings."""
        from . import packkit

        try:
            envelope = packkit.read_envelope(source)
        except (OSError, ValueError) as error:
            _refuse(str(error))
            return
        resolved, findings = packkit.check(envelope, roots=root or ())
        _emit({"ref": envelope.ref(), "digest": resolved.digest if resolved else None, "findings": findings})
        if findings:
            _refuse(f"pack {envelope.ref()} has {len(findings)} finding(s)", findings)

    @pack_app.command("install")
    def install_command(
        source: Annotated[Path, typer.Argument(help="A pack envelope file to upload.")],
        into: Annotated[Path | None, typer.Option("--into", help="Pack root to store it in (default: the user's).")] = None,
        replace: Annotated[bool, typer.Option("--replace", help="Overwrite a pack of the same name in that root.")] = False,
        root: Roots = None,
    ) -> None:
        """Upload a pack: lint it, refuse with every finding, or store it where it is found by name."""
        from . import packkit

        try:
            location, resolved = packkit.install(source, root=into, roots=root or (), replace=replace)
        except (OSError, ValueError, KeyError) as error:
            text = str(error)
            findings = [part.strip() for part in text.split(" rejected: ", 1)[-1].split("; ")] if " rejected: " in text else []
            _refuse(text, findings)
            return
        _emit({"installed": resolved.ref, "digest": resolved.digest, "location": str(location), "chain": list(resolved.chain)})

    @pack_app.command("tree")
    def tree_command(
        ref: Annotated[str, typer.Argument(help="A pack with a tree codec: agent:NAME[@digest] or a pack file.")],
        out: Annotated[Path, typer.Option("--out", "-o", help="Directory to write the tree into; must be empty or new.")],
        root: Roots = None,
    ) -> None:
        """Write a pack as its tree of files: for an agent pack, policy.json and its skills/ directory."""
        from . import packkit
        from .evalrun.policy import write_tree

        try:
            resolved = packkit.resolve(ref, roots=root or ())
            codec = packkit.kind(resolved.kind)
            if codec.to_tree is None:
                raise ValueError(f"a {resolved.kind} pack has no tree form; only kinds with a tree codec do")
            files = codec.to_tree(resolved.data)
            if out.exists() and (not out.is_dir() or any(out.iterdir())):
                raise ValueError(f"{out} exists and is not an empty directory; choose a new one")
            out.mkdir(parents=True, exist_ok=True)
            write_tree(files, out)
        except (KeyError, ValueError, OSError) as error:
            _refuse(str(error).strip("'\""))
            return
        _emit({"ref": resolved.ref, "digest": resolved.digest, "out": str(out), "files": sorted(files)})

    @pack_app.command("from-tree")
    def from_tree_command(
        directory: Annotated[Path, typer.Argument(help="A tree (policy.json and skills/), or a skills directory of <name>/SKILL.md.")],
        name: Annotated[str, typer.Option("--name", help="The agent pack's name.")],
        into: Annotated[Path | None, typer.Option("--into", help="Pack root to store it in (default: the user's).")] = None,
        base: Annotated[str, typer.Option("--base", help="Where policy.json comes from when DIRECTORY has none.")] = "agent:baseline",
        title: Annotated[str, typer.Option("--title")] = "",
        replace: Annotated[bool, typer.Option("--replace", help="Overwrite a pack of the same name in that root.")] = False,
        root: Roots = None,
    ) -> None:
        """Build an agent pack from a skill tree on disk, lint it, and install it; refused with every finding."""
        from . import packkit
        from .evalrun.policy import POLICY_FILE, SKILLS_ROOT, from_tree, read_tree, tree

        try:
            if not directory.is_dir():
                raise ValueError(f"{directory} is not a directory")
            held = read_tree(directory)
            if POLICY_FILE not in held and not any(path.startswith(f"{SKILLS_ROOT}/") for path in held):
                # A bare skills directory (`.claude/skills`): each entry is a skill.
                held = {f"{SKILLS_ROOT}/{path}": text for path, text in held.items()}
            if POLICY_FILE not in held:
                held[POLICY_FILE] = tree(packkit.resolve(base, kind_name="agent", roots=root or ()).data)[POLICY_FILE]
            envelope = packkit.PackEnvelope(kind="agent", name=name, title=title, body=from_tree(held))
            location, resolved = packkit.install(envelope, root=into, roots=root or (), replace=replace)
        except (KeyError, ValueError, OSError) as error:
            text = str(error).strip("'\"")
            findings = [part.strip() for part in text.split(" rejected: ", 1)[-1].split("; ")] if " rejected: " in text else []
            _refuse(text, findings)
            return
        _emit({"installed": resolved.ref, "digest": resolved.digest, "location": str(location),
               "files": sorted(resolved.body.files)})

    @pack_app.command("diff")
    def diff_command(
        ref_a: Annotated[str, typer.Argument(help="The pack before: kind:NAME[@digest] or a pack file.")],
        ref_b: Annotated[str, typer.Argument(help="The pack after, of the same kind.")],
        root: Roots = None,
    ) -> None:
        """Print the unified diff between two packs' trees (kinds with a tree codec, such as agent)."""
        from . import packkit
        from .packkit import diffs

        try:
            before = packkit.resolve(ref_a, roots=root or ())
            after = packkit.resolve(ref_b, roots=root or ())
            if before.kind != after.kind:
                raise ValueError(f"{before.ref} is a {before.kind} pack and {after.ref} a {after.kind} pack; diff two of one kind")
            codec = packkit.kind(before.kind)
            if codec.to_tree is None:
                raise ValueError(f"a {before.kind} pack has no tree form; only kinds with a tree codec diff")
            text = diffs.render(codec.to_tree(before.data), codec.to_tree(after.data))
        except (KeyError, ValueError) as error:
            _refuse(str(error).strip("'\""))
            return
        typer.echo(text, nl=False)

    interview_app = typer.Typer(no_args_is_help=True, help="Author a pack with your coding harness through files.")
    pack_app.add_typer(interview_app, name="interview")

    @interview_app.command("request")
    def interview_request(
        kind: Annotated[str, typer.Argument(help="The kind of pack to author (`worldloom pack kinds`).")],
        message: Annotated[str, typer.Option("--message", help="What the operator wants.")],
        out: Annotated[Path, typer.Option("--out", "-o")],
        name: Annotated[str, typer.Option("--name", help="The pack's name, when the operator has chosen one.")] = "",
        draft: Annotated[Path | None, typer.Option("--draft", help="A previous proposal to revise.")] = None,
        findings: Annotated[Path | None, typer.Option("--findings", help="The refusal to answer (from `interview accept`).")] = None,
        root: Roots = None,
    ) -> None:
        """Write the bounded request a harness answers with one pack proposal."""
        from . import packkit

        try:
            payload = packkit.request(
                kind, message, name=name,
                draft=json.loads(draft.read_text(encoding="utf-8")) if draft else None,
                findings=json.loads(findings.read_text(encoding="utf-8")).get("findings", []) if findings else (),
                roots=root or ())
        except (KeyError, ValueError, OSError) as error:
            _refuse(str(error))
            return
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _emit({"request": str(out), "request_id": payload["request_id"], "kind": kind})

    @interview_app.command("accept")
    def interview_accept(
        request_file: Annotated[Path, typer.Option("--request", help="The request file the harness answered.")],
        reply_file: Annotated[Path, typer.Option("--reply", help="The harness's reply.")],
        into: Annotated[Path | None, typer.Option("--into", help="Store an accepted pack in this root.")] = None,
        install: Annotated[bool, typer.Option("--install", help="Store an accepted pack (in --into, else the user's root).")] = False,
        replace: Annotated[bool, typer.Option("--replace")] = False,
        root: Roots = None,
    ) -> None:
        """Judge a reply: accepted (optionally stored), refused with findings, or questions for the operator."""
        from . import packkit

        payload = json.loads(request_file.read_text(encoding="utf-8"))
        reply = json.loads(reply_file.read_text(encoding="utf-8"))
        search = ((into,) if into else ()) + tuple(root or ())
        try:
            verdict = packkit.accept(payload, reply, roots=search)
        except ValueError as error:
            _refuse(str(error))
            return
        result: dict[str, Any] = {"status": verdict.status, "findings": list(verdict.findings),
                                  "questions": list(verdict.questions), "message": verdict.message,
                                  "proposal": verdict.envelope.dump() if verdict.envelope else None}
        if verdict.status == "accepted" and (install or into):
            assert verdict.envelope is not None
            location, resolved = packkit.install(verdict.envelope, root=into, roots=root or (), replace=replace)
            result.update(installed=resolved.ref, location=str(location), digest=resolved.digest)
        _emit(result)
        if verdict.status == "refused":
            raise typer.Exit(code=3)

    @pack_app.command("author")
    def author_command(
        kind: Annotated[str, typer.Argument(help="The kind of pack to author.")],
        message: Annotated[str, typer.Option("--message", help="What the operator wants.")],
        harness_command: Annotated[str, typer.Option("--harness-command", help="Adapter: JSON request on stdin, JSON reply on stdout.")],
        name: Annotated[str, typer.Option("--name")] = "",
        into: Annotated[Path | None, typer.Option("--into", help="Pack root to store the accepted pack in (default: the user's).")] = None,
        rounds: Annotated[int | None, typer.Option("--rounds", min=1, max=16, help="Refusal rounds before giving up.")] = None,
        replace: Annotated[bool, typer.Option("--replace")] = False,
        timeout: Annotated[float, typer.Option(min=1, max=3600)] = 600,
        root: Roots = None,
    ) -> None:
        """Interview a harness until it proposes a pack the lint accepts, then store it."""
        from . import packkit
        from .packkit.authoring import run_exec_exchange

        target = into or packkit.user_root()
        try:
            authored = packkit.author(kind, message, run_exec_exchange(harness_command, timeout=timeout), name=name,
                                      max_rounds=rounds or int(packkit.policy("pack.interview.max_rounds")),
                                      root=target, roots=root or (), replace=replace)
        except (KeyError, ValueError) as error:
            _refuse(str(error))
            return
        verdict = authored.verdict
        _emit({"status": verdict.status, "rounds": authored.rounds, "questions": list(verdict.questions),
               "findings": list(verdict.findings), "message": verdict.message,
               "location": str(authored.location) if authored.location else None})
        if verdict.status == "refused":
            raise typer.Exit(code=3)


__all__ = ["install_commands"]
