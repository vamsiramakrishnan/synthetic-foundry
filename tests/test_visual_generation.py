from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

from worldloom.models import (
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    Quantity,
)
from worldloom.native_corpus import plan_native_corpus, render_native_corpus
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.native_reference import qualify_native_task
from worldloom.visuals import (
    NanoBananaConfig,
    NanoBananaProvider,
    VisualError,
    VisualRequest,
    VisualStore,
    attach_visual,
    generate_visual,
    plan_visual,
    visual_prompt,
)
from worldloom.world import World


def _world() -> World:
    facts = tuple(CanonicalFact(
        id=f"FACT-{kind.upper()}", kind=f"financial.revenue.{kind}", subject="CO-1", period="2026-01",
        value=Quantity(amount=amount, unit="AUD"), valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        authority=Authority.SYSTEM_OF_RECORD,
    ) for kind, amount in (("actual", 125), ("budget", 100)))
    return World(
        company=Company(id="CO-1", name="Northstar Retail", industry="retail", headquarters="Sydney",
                        fiscal_year_start_month=7, employees_total=100),
        _facts=facts,
        _artifact_irs=(ArtifactIR(id="ART-1", intent_id="INTENT-1", title="Revenue close", sections=[
            ArtifactSection(heading=f"Revenue {fact.kind.rsplit('.', 1)[-1]}",
                            body=f"Revenue evidence: {{{{fact:{fact.id}}}}}", fact_ids=[fact.id])
            for fact in facts
        ]),),
    )


def _spec(world: World):
    return plan_visual(world, visual_id="revenue-infographic", title="Revenue close",
                       fact_ids=tuple(fact.id for fact in world.facts))


def _png(width: int = 32, height: int = 18) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, format="PNG")
    return stream.getvalue()


class _Client:
    def __init__(self, payload: bytes | None = None) -> None:
        self.calls: list[dict] = []
        self.image = SimpleNamespace(data=base64.b64encode(payload or _png()).decode(), mime_type="image/png")
        self.interactions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_image=self.image)


def test_generate_replays_exact_bytes_offline_and_omits_private_ids_from_prompt(tmp_path) -> None:
    world, client = _world(), _Client()
    spec, store = _spec(world), VisualStore(tmp_path)
    first = generate_visual(world, spec, store=store, provider=NanoBananaProvider(client))
    replay = generate_visual(world, spec, store=VisualStore(tmp_path))
    cached = generate_visual(world, spec, store=store, provider=NanoBananaProvider(client))
    assert len(client.calls) == 1 and not first.replayed and replay.replayed and cached.replayed
    assert first.payload == replay.payload == _png()
    assert first.record == replay.record
    assert first.record.evidence_status == "unqualified"
    assert first.record.receipt.accepted_digest == first.record.image_sha256
    assert "125.0" in client.calls[0]["input"] and "Northstar Retail" in client.calls[0]["input"]
    for identifier in (world.company.id, *(fact.id for fact in world.facts), spec.visual_id):
        assert identifier not in client.calls[0]["input"]
    assert client.calls[0]["response_format"] == {
        "type": "image", "mime_type": "image/png", "aspect_ratio": "16:9", "image_size": "2K",
    }
    assert first.record.request.spec.facts[0].fact_id == world.facts[0].id


def test_snapshot_changes_refuse_before_provider_or_replay(tmp_path) -> None:
    world, client = _world(), _Client()
    spec, store = _spec(world), VisualStore(tmp_path)
    with pytest.raises(VisualError, match="unknown visual facts"):
        plan_visual(world, visual_id="x", title="Revenue", fact_ids=("missing",))
    changed = replace(world, _facts=(world.facts[0].model_copy(update={"value": Quantity(amount=999, unit="AUD")}), world.facts[1]))
    for current in (changed, replace(world, company=world.company.model_copy(update={"name": "Different company"}))):
        with pytest.raises(VisualError, match="snapshot no longer matches"):
            generate_visual(current, spec, store=store, provider=NanoBananaProvider(client))
    assert not client.calls
    generate_visual(world, spec, store=store, provider=NanoBananaProvider(client))
    with pytest.raises(VisualError, match="snapshot no longer matches"):
        generate_visual(changed, spec, store=store)


@pytest.mark.parametrize("changed", [
    {"model": "gemini-3-pro-image"}, {"deployment_id": "another-project"},
    {"image_size": "4K"}, {"aspect_ratio": "1:1"},
])
def test_each_provider_setting_changes_the_replay_key(tmp_path, changed) -> None:
    world = _world()
    spec, store = _spec(world), VisualStore(tmp_path)
    generate_visual(world, spec, store=store, provider=NanoBananaProvider(_Client()))
    with pytest.raises(VisualError, match="no recorded visual"):
        generate_visual(world, spec, store=store, config=NanoBananaConfig(**changed))


@pytest.mark.parametrize("failure", ["base64", "no-image", "mime", "size", "truncated", "pixels"])
def test_provider_candidates_are_bounded_and_readable_before_recording(tmp_path, failure) -> None:
    world, client = _world(), _Client()
    config = NanoBananaConfig(max_bytes=1024, max_pixels=1000)
    if failure == "base64":
        client.image.data = "invalid-base64"
    elif failure == "no-image":
        client.image = None
    elif failure == "mime":
        client.image.mime_type = "image/jpeg"
    elif failure == "size":
        client.image.data = "A" * 2048
    elif failure == "truncated":
        client.image.data = base64.b64encode(_png()[:-20]).decode()
    else:
        client.image.data = base64.b64encode(_png(100, 100)).decode()
    with pytest.raises(VisualError):
        generate_visual(world, _spec(world), store=VisualStore(tmp_path), config=config,
                        provider=NanoBananaProvider(client))
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("tamper", ["image", "receipt", "dimensions", "missing", "oversize"])
def test_corrupt_cache_refuses_without_new_provider_calls(tmp_path, tamper) -> None:
    world, client = _world(), _Client()
    spec, store = _spec(world), VisualStore(tmp_path)
    asset = generate_visual(world, spec, store=store, provider=NanoBananaProvider(client))
    request_path = next((tmp_path / "requests").glob("*.json"))
    image_path = next((tmp_path / "blobs").glob("*.png"))
    if tamper == "image":
        image_path.write_bytes(_png(20, 20))
    elif tamper == "missing":
        image_path.unlink()
    elif tamper == "oversize":
        with image_path.open("wb") as handle:
            handle.truncate(asset.record.request.config.max_bytes + 1)
    else:
        record = json.loads(request_path.read_text())
        if tamper == "receipt":
            record["receipt"]["accepted_digest"] = "0" * 64
        else:
            record["width"] = 900
        request_path.write_text(json.dumps(record))
    with pytest.raises(VisualError):
        generate_visual(world, spec, store=store, provider=NanoBananaProvider(client))
    assert len(client.calls) == 1


def test_prompt_and_ledger_are_stable_for_fact_selection_order(tmp_path) -> None:
    world = _world()
    reverse = plan_visual(world, visual_id="revenue-infographic", title="Revenue close",
                          fact_ids=tuple(reversed([fact.id for fact in world.facts])))
    first = VisualRequest(spec=_spec(world), config=NanoBananaConfig())
    second = VisualRequest(spec=reverse, config=NanoBananaConfig())
    assert first.key == second.key
    assert visual_prompt(first) == visual_prompt(second)
    store = VisualStore(tmp_path)
    asset = store.save(first, _png())
    with pytest.raises(VisualError, match="different recorded bytes"):
        store.save(first, _png(20, 20))
    assert store.load(first).payload == asset.payload


@pytest.mark.parametrize("format", ["docx", "pptx", "xlsx"])
def test_attached_visual_preserves_existing_qualified_native_tasks(tmp_path, format) -> None:
    world = _world()
    asset = generate_visual(world, _spec(world), store=VisualStore(tmp_path), provider=NanoBananaProvider(_Client()))
    plan = plan_native_corpus(world, artifact_id="revenue", format=format, title="Revenue close", minimum_units=2)
    native = render_native_corpus(world, plan)
    attached = attach_visual(native, asset, world=world)
    assert attached.payload == attach_visual(native, asset, world=world).payload
    assert attached.manifest.sha256 != native.manifest.sha256
    assert attached.manifest.evidence == native.manifest.evidence
    assert attached.manifest.distinct_fact_count == native.manifest.distinct_fact_count
    assert attached.manifest.content_units == native.manifest.content_units
    assert attached.manifest.native_metrics["unqualified_visual_count"] == 1
    with ZipFile(BytesIO(attached.payload)) as archive:
        assert asset.payload in [archive.read(name) for name in archive.namelist() if "/media/" in name]
    workload = NativeWorkloadPlan(use_case_id="visual-close", objective="Read the revenue evidence.",
                                  formats=(format,), operations=("read",), max_tasks=8)
    old = plan_native_workload(world, {"revenue": native}, workload)
    replanned = plan_native_workload(world, {"revenue": attached}, workload)
    assert old.tasks and len(replanned.tasks) == len(old.tasks)
    assert all(qualify_native_task(task, {"revenue": attached.payload}).passed for task in replanned.tasks)
    assert not qualify_native_task(old.tasks[0], {"revenue": attached.payload}).passed


def test_native_attachment_refuses_tampered_native_manifest(tmp_path) -> None:
    world = _world()
    asset = generate_visual(world, _spec(world), store=VisualStore(tmp_path), provider=NanoBananaProvider(_Client()))
    plan = plan_native_corpus(world, artifact_id="revenue", format="docx", title="Revenue close", minimum_units=2)
    native = render_native_corpus(world, plan)
    with pytest.raises(VisualError, match="do not match their manifest"):
        attach_visual(replace(native, payload=native.payload + b"corrupt"), asset, world=world)


def test_native_attachment_refuses_another_company_or_unrepresented_facts(tmp_path) -> None:
    world = _world()
    asset = generate_visual(world, _spec(world), store=VisualStore(tmp_path), provider=NanoBananaProvider(_Client()))
    plan = plan_native_corpus(world, artifact_id="revenue", format="docx", title="Revenue close", minimum_units=2)
    native = render_native_corpus(world, plan)
    foreign = replace(world, company=world.company.model_copy(update={"id": "CO-OTHER"}))
    with pytest.raises(VisualError, match="snapshot no longer matches"):
        attach_visual(native, asset, world=foreign)
    section = world._artifact_irs[0].sections[0]
    subset = replace(world, _artifact_irs=(world._artifact_irs[0].model_copy(update={"sections": [section]}),))
    subset_plan = plan_native_corpus(subset, artifact_id="one-fact", format="docx", title="Revenue actual", minimum_units=1)
    with pytest.raises(VisualError, match="must already be grounded"):
        attach_visual(render_native_corpus(subset, subset_plan), asset, world=world)
