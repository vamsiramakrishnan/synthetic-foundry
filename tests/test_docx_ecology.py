from io import BytesIO

from docx import Document

from worldloom import MonthEndClose, RetailWorld
from worldloom.ecology import render


def _documents():  # type: ignore[no-untyped-def]
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    result = render(world, "docx")
    return [
        Document(BytesIO(item.payload))
        for item in result.world._rendered
        if item.path.endswith(".docx")
    ]


def test_ecology_docx_carries_lifecycle_revision_and_family_in_properties() -> None:
    documents = _documents()
    assert documents
    for document in documents:
        category = document.core_properties.category or ""
        assert "worldloom-realism=ecology/v1" in category
        assert "lifecycle=" in category
        assert "revision=" in category
        assert "family=" in category


def test_ecology_docx_does_not_print_control_metadata_into_body() -> None:
    documents = _documents()
    assert documents
    for document in documents:
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "worldloom-realism=ecology/v1" not in text
        assert "department_style=" not in text
        assert "style_seed=" not in text
