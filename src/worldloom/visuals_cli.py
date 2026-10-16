"""Explicit image generation and offline replay over the visual SDK."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from .visuals.models import VisualRequest

visuals_app = typer.Typer(no_args_is_help=True,
    help="Plan fact-grounded infographics, generate with Nano Banana, and replay recorded image bytes.")


def _reject(error: Exception) -> None:
    from rich.markup import escape

    from .cli import _refuse
    _refuse("visual_rejected", escape(str(error)))


class _DefaultNanoBananaProvider:
    """Create the optional SDK client only when a recorded request is absent."""

    def generate(self, request: VisualRequest) -> bytes:
        from .visuals import NanoBananaProvider, VisualError
        try:
            from google import genai
        except ImportError as error:
            raise VisualError("Nano Banana generation requires worldloom[visuals]") from error
        try:
            # Pin the smallest supported retry budget. In google-genai 2.28,
            # Interactions interprets attempts=1 as one retry (two HTTP
            # attempts); the public SDK offers no zero-retry override.
            with genai.Client(http_options={"timeout": 60_000, "retry_options": {"attempts": 1}}) as client:
                return NanoBananaProvider(client).generate(request)
        except VisualError:
            raise
        except Exception as error:
            # SDK error payloads may contain request/credential details. The
            # CLI emits only the exception category; caller-owned SDK clients
            # remain available for detailed transport diagnostics.
            raise VisualError(f"Nano Banana request failed ({type(error).__name__}); check client configuration and quota") from error


@visuals_app.command("plan")
def visual_plan_command(
    corpus_path: Annotated[str, typer.Argument(help="Canonical company corpus.")],
    visual_id: Annotated[str, typer.Option("--id", help="Stable visual request name.")],
    title: Annotated[str, typer.Option("--title", help="Infographic title.")],
    fact_ids: Annotated[list[str], typer.Option("--fact-id", help="Existing canonical fact to depict; repeatable.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Write a VisualSpec JSON request.")],
    brief: Annotated[str, typer.Option(help="Presentation instructions; canonical facts remain authoritative.")] = "Present the supplied facts as a business infographic.",
    style: Annotated[str, typer.Option(help="Visual style instructions.")] = "Clear labels, restrained colors, readable type, no decorative numbers.",
) -> None:
    """Bind an infographic request to existing facts without calling a provider."""
    from .cli import _load
    from .quality_cli import _emit
    from .visuals import plan_visual

    try:
        spec = plan_visual(_load(corpus_path), visual_id=visual_id, title=title,
            fact_ids=tuple(fact_ids), brief=brief, style=style)
        _emit(spec.model_dump(mode="json"), out)
    except (ValueError, OSError) as error:
        _reject(error)


@visuals_app.command("generate")
def visual_generate_command(
    corpus_path: Annotated[str, typer.Argument(help="Canonical company corpus used to validate the fact snapshot.")],
    spec: Annotated[Path, typer.Option("--spec", help="VisualSpec JSON from visuals plan.")],
    store: Annotated[Path, typer.Option("--store", help="Recorded visual requests and image blobs; keep with the corpus.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Destination PNG; a differing existing file is refused.")],
    config: Annotated[Path | None, typer.Option("--config", help="NanoBananaConfig JSON; model, aspect ratio and resolution are replay inputs.")] = None,
    offline: Annotated[bool, typer.Option("--offline", help="Require a recorded result; never initialize an SDK client or call a provider.")] = False,
) -> None:
    """Replay first, or explicitly generate one unqualified PNG with Nano Banana."""
    from .cli import _load
    from .quality_cli import _document, _emit
    from .visuals import NanoBananaConfig, VisualSpec, VisualStore, generate_visual

    try:
        if out.suffix.lower() != ".png":
            raise ValueError("visual output must use the .png extension")
        # An existing output is never a reason to incur a second provider call.
        # Offline replay still permits an identical file to be re-materialized.
        asset = generate_visual(_load(corpus_path), VisualSpec.model_validate(_document(spec)),
            store=VisualStore(store), config=NanoBananaConfig.model_validate(_document(config)) if config else None,
            provider=None if offline or out.exists() else _DefaultNanoBananaProvider())
        if out.exists():
            if out.stat().st_size != len(asset.payload) or out.read_bytes() != asset.payload:
                raise ValueError("visual output already contains different bytes; choose another path")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(asset.payload)
        _emit({"path": str(out), "request_key": asset.record.request.key,
            "image_sha256": asset.record.image_sha256, "file_size_bytes": len(asset.payload),
            "replayed": asset.replayed, "evidence_status": asset.record.evidence_status})
    except (ValueError, OSError) as error:
        _reject(error)
