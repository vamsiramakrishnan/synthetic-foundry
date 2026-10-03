# Generate and replay infographics

Worldloom can ask Nano Banana for an infographic using selected canonical facts.
The generated PNG is an external proposal. Worldloom checks its file structure,
size and dimensions, then records the exact bytes and an execution receipt.
Replay reads those bytes with no provider call.

This optional provider does not change the narration contract. The harness
still writes prose. No model is called by a normal corpus build or replay.

Install the optional client and image decoder:

```bash
pip install -e '.[visuals]'
```

Use a caller-owned Gemini client. The adapter invokes it once per cache miss;
authentication and underlying HTTP retries follow the client's configuration.
Worldloom does not make web-grounding calls or add a generation retry loop.
This adapter uses Gemini's `interactions.create` API. It does not claim Vertex
AI transport compatibility; that endpoint uses a different API surface.

## CLI

Select existing fact IDs from the corpus. `plan` makes no provider call:

```bash
worldloom visuals plan ./corpus --id revenue-close --title "Revenue close" --fact-id FACT_ID --out ./visual.json
worldloom visuals generate ./corpus --spec ./visual.json --store ./corpus/visuals --out ./revenue-close.png
worldloom visuals generate ./corpus --spec ./visual.json --store ./corpus/visuals --out ./revenue-close-copy.png --offline
```

Configure Gemini API authentication through the Google SDK, for example with
`GEMINI_API_KEY`. A cached request and `--offline` never initialize an SDK client.
`--config` accepts `NanoBananaConfig` JSON for model, resolution and aspect ratio.
An existing differing output is refused. The CLI reports the image digest,
replay status and `evidence_status`; it does not print credentials or private
source snapshots.

The CLI sets a 60-second request timeout and `retry_options.attempts=1`.
In the verified Google SDK 2.28.0, the Interactions layer interprets this as
one retry, allowing two HTTP attempts; its default allows four. Do not equate
one Worldloom invocation with exactly one billable request. A public zero-retry
override is not available in that SDK version. SDK callers own their transport
and retry configuration; Worldloom does not alter private SDK internals.

## Python

```python
from pathlib import Path

from google import genai
from worldloom import World
from worldloom.visuals import (
    NanoBananaConfig,
    NanoBananaProvider,
    VisualStore,
    generate_visual,
    plan_visual,
)

world = World.load("./corpus")
spec = plan_visual(
    world,
    visual_id="revenue-close",
    title="Revenue close",
    # Select actual fact IDs from this corpus, not values copied into a prompt.
    fact_ids=tuple(fact.id for fact in world.facts if fact.kind.startswith("financial.revenue."))[:12],
    brief="Compare actual revenue with budget. Label each reporting period.",
    style="Use readable labels and a restrained business palette.",
)
config = NanoBananaConfig(
    model="gemini-3.1-flash-image",  # Nano Banana 2
    aspect_ratio="16:9",
    image_size="2K",
)
store = VisualStore("./corpus/visuals")
client = genai.Client()  # Authentication is configured by the caller.
asset = generate_visual(
    world, spec, store=store, config=config,
    provider=NanoBananaProvider(client),
)
Path("revenue-close.png").write_bytes(asset.payload)

# Works without a client, API key or network. A cache miss refuses to proceed.
replayed = generate_visual(world, spec, store=store, config=config)
assert replayed.payload == asset.payload
assert replayed.replayed
```

Set `model="gemini-3-pro-image"` to select Nano Banana Pro. Model, deployment
identifier, image size, aspect ratio, resource limits, prompt version and every
source fact snapshot enter the request identity. `deployment_id` identifies a
caller-owned endpoint/project configuration without recording credentials. Set
it when that routing differs from the default Gemini API configuration.

The immutable specification captures each fact's value, unit, period, authority
and temporal provenance. Generation and replay reject a changed source world.
The provider receives a projection with business labels and values; canonical
fact IDs, event IDs and internal provenance stay in the private record.

## Attach to native files

`attach_visual` appends an image to a DOCX, PPTX or XLSX `NativeCorpusResult`.
The selected facts must already occur in that native file's grounded evidence.
It uses the existing workload inventory to verify native provenance, preserves
the existing evidence locators and values, and refreshes the source digest.

```python
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload
from worldloom.visuals import attach_visual

# native is an existing NativeCorpusResult produced from this world.
attached = attach_visual(native, asset, world=world)
Path("revenue-close.docx").write_bytes(attached.payload)  # For a DOCX source.

workload = plan_native_workload(
    world,
    {attached.manifest.artifact_id: attached},
    NativeWorkloadPlan(
        use_case_id="revenue-close",
        objective="Reconcile revenue against budget.",
    ),
)
```

Re-plan after attachment. An old task remains bound to the old file digest and
correctly rejects changed bytes. Qualified evidence and distinct-fact counts
do not increase when a visual is attached; the manifest reports
`unqualified_visual_count` separately. Keep the updated native manifest and
the visual store with the corpus.

## Acceptance and qualification

Every record has `evidence_status="unqualified"`. A readable image can still
misprint a number, use the wrong scale, omit a label or contradict its prompt.
The generated image is therefore available as a corpus attachment, but cannot
silently become a gold answer or qualified visual task. Visual qualification
must independently establish readable evidence, correct values and geometry,
and the absence of unintended text shortcuts before admitting such tasks.

The store contains:

```text
visuals/requests/<request-sha256>.json
visuals/blobs/<image-sha256>.png
```

Request records are evaluator-side material: they include canonical facts.
Only the intended image/native file belongs in a harness's public workspace.
Receipts reuse `worldloom.providers.Receipt` and contain digests. A ledger hit
checks the request, image digest, dimensions and receipt before returning.
Missing, tampered or oversized bytes cause a refusal; Worldloom does not call
the provider to silently repair a corrupt replay.

The adapter accepts a single PNG, defaults to a 20 MiB encoded-file budget and
a 32 megapixel decoded-image budget, and caps requests at 64 facts. The injected
SDK owns network timeout and transport buffering. Reproducibility means replay
of recorded bytes, not repeatability of a fresh model call.

The implementation follows Google's [image-generation API](https://ai.google.dev/gemini-api/docs/image-generation).
Tests use an injected client and cover exact replay, changed worlds, corrupt
records, bounds, private-ID projection and preserved native qualification in
all three Office formats. They do not measure live model accuracy or fidelity.
