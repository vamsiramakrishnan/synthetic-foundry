from worldloom.render import fonts


def test_pdf_italic_faces_use_valid_base14_names() -> None:
    assert fonts.pdf_italic("Helvetica") == "Helvetica-Oblique"
    assert fonts.pdf_italic("Courier") == "Courier-Oblique"
    assert fonts.pdf_italic("Times") == "Times-Italic"
