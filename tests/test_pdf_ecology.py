from worldloom import MonthEndClose, RetailWorld
from worldloom.ecology import render


def _pdfs():  # type: ignore[no-untyped-def]
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    result = render(world, "pdf")
    return [item.payload for item in result.world._rendered if item.path.endswith(".pdf")]


def test_ecology_pdf_embeds_machine_readable_lifecycle_keywords() -> None:
    payloads = _pdfs()
    assert payloads
    for payload in payloads:
        assert b"worldloom-realism=ecology/v1" in payload
        assert b"lifecycle=" in payload
        assert b"revision=" in payload
        assert b"family=" in payload


def test_ecology_pdf_control_metadata_is_not_visible_story_text() -> None:
    payloads = _pdfs()
    assert payloads
    for payload in payloads:
        # ReportLab writes Info metadata plainly while page streams are also
        # uncompressed. The marker should occur in metadata only once rather
        # than being repeated into the readable story.
        assert payload.count(b"worldloom-realism=ecology/v1") == 1
