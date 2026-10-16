"""Optional real-SDK contract, with every HTTP response served offline."""
from __future__ import annotations

import base64
import json
from io import BytesIO

import pytest
from PIL import Image

from worldloom import World
from worldloom.visuals import (
    NanoBananaProvider,
    VisualError,
    VisualStore,
    generate_visual,
    plan_visual,
)

genai = pytest.importorskip("google.genai", minversion="2.28.0")
httpx = pytest.importorskip("httpx")


def _specification():
    world = World.load("retail-close")
    spec = plan_visual(world, visual_id="sdk-contract", title="Business review", fact_ids=(world.facts[0].id,))
    return world, spec


def _image():
    buffer = BytesIO()
    Image.new("RGB", (16, 9), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _client(http):
    # Explicit fake key and invalid origin prevent environment configuration
    # from changing this test. MockTransport is the only request destination.
    return genai.Client(vertexai=False, api_key="worldloom-offline-test", http_options={
        "httpx_client": http, "base_url": "https://worldloom.invalid", "api_version": "v1beta",
        "timeout": 1000, "retry_options": {"attempts": 1, "initial_delay": 0, "max_delay": 0, "jitter": 0},
    })


def test_real_sdk_serializes_image_request_and_replays_its_response_offline(tmp_path) -> None:
    requests = []
    png = _image()

    def handle(request):
        requests.append(request)
        # The SDK derives output_image from actual model-output steps; the
        # HTTP response does not provide our adapter's convenience property.
        return httpx.Response(200, json={"id": "offline-image", "status": "completed", "steps": [{
            "type": "model_output", "content": [
                {"type": "text", "text": "Image generated."},
                {"type": "image", "mime_type": "image/png", "data": base64.b64encode(png).decode()},
            ],
        }]})

    world, spec = _specification()
    with httpx.Client(transport=httpx.MockTransport(handle)) as http, _client(http) as client:
        asset = generate_visual(world, spec, store=VisualStore(tmp_path), provider=NanoBananaProvider(client))
        assert asset.payload == png and not asset.replayed
        assert asset.record.evidence_status == "unqualified"
    replay = generate_visual(world, spec, store=VisualStore(tmp_path))
    assert replay.payload == png and replay.replayed and len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and str(request.url) == "https://worldloom.invalid/v1beta/interactions"
    body = json.loads(request.content)
    assert body["model"] == "gemini-3.1-flash-image"
    assert body["response_format"] == {
        "type": "image", "mime_type": "image/png", "aspect_ratio": "16:9", "image_size": "2K",
    }
    assert spec.title in str(body["input"])
    assert world.facts[0].id not in str(body["input"])
    assert "tools" not in body


@pytest.mark.parametrize("response", ["text-only", "refusal"])
def test_real_sdk_missing_image_or_refusal_never_enters_the_store(tmp_path, response) -> None:
    requests = []

    def handle(request):
        requests.append(request)
        if response == "refusal":
            return httpx.Response(400, json={"error": {
                "code": "INVALID_ARGUMENT", "message": "Offline test refusal.",
            }})
        return httpx.Response(200, json={"id": "offline-text", "status": "completed", "steps": [{
            "type": "model_output", "content": [{"type": "text", "text": "No image output."}],
        }]})

    world, spec = _specification()
    with httpx.Client(transport=httpx.MockTransport(handle)) as http, _client(http) as client:
        if response == "refusal":
            # Interactions currently uses a different exception hierarchy from
            # models.generate_content; verify the public HTTP status instead.
            with pytest.raises(Exception, match="400") as error:
                generate_visual(world, spec, store=VisualStore(tmp_path), provider=NanoBananaProvider(client))
            assert error.value.status_code == 400
        else:
            with pytest.raises(VisualError, match="no image data"):
                generate_visual(world, spec, store=VisualStore(tmp_path), provider=NanoBananaProvider(client))
    assert len(requests) == 1
    assert not list(tmp_path.rglob("*.json"))


def test_real_sdk_transient_failure_is_bounded_and_never_recorded(tmp_path) -> None:
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"code": "UNAVAILABLE", "message": "Offline transient failure."}})

    world, spec = _specification()
    with httpx.Client(transport=httpx.MockTransport(handle)) as http, _client(http) as client:
        with pytest.raises(Exception, match="503") as error:
            generate_visual(world, spec, store=VisualStore(tmp_path), provider=NanoBananaProvider(client))
        assert error.value.status_code == 503
    # In 2.28, attempts=1 is mapped to one retry by the Interactions bridge:
    # two requests. Permit the documented single-attempt behavior if fixed,
    # while guarding against returning to the default four-attempt behavior.
    assert 1 <= len(requests) <= 2
    assert not list(tmp_path.rglob("*.json"))
